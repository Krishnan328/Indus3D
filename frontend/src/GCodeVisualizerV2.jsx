/**
 * GCodeVisualizer.jsx
 * --------------------
 * Fetches and renders the G-code toolpath in the 3D viewport.
 * 
 * PERFORMANCE FIX: React Component strictly bypasses render loop for filePosition updates.
 * Updates are handled by binary-searching a pre-calculated BufferAttribute via Zustand subscribe.
 */

import React, { useState, useEffect, useRef } from "react";
import * as THREE from "three";
import { useStore, API } from "./store";

const SIM_PREFIX = "sim_";

export function GCodeVisualizerV2() {
  // Only subscribe to variables that rarely change (filename, excludedObjects, bed).
  // DO NOT subscribe to file_position here, or it will crash React's reconciler with rapid re-renders!
  const filename        = useStore((s) => s.telemetry?.filename);
  const excludedObjectsRaw = useStore((s) => s.exclude_object?.excluded_objects);
  const excludedObjects = React.useMemo(() => excludedObjectsRaw || [], [excludedObjectsRaw]);
  const bed             = useStore((s) => s.bed);
  const colorByHeight    = useStore((s) => s.uiPrefs.gcodeColorByHeight);
  const showTravel       = useStore((s) => s.uiPrefs.gcodeShowTravel);

  const [allPaths, setAllPaths] = useState([]);
  const [travelSegments, setTravelSegments] = useState([]);
  const retryRef = useRef(null);
  const groupRef = useRef(null);
  const linesRef = useRef(null);
  const travelLinesRef = useRef(null);
  const frozenObjectsRef = useRef({});

  const bedY = (bed.size_y_mm ?? 300) / 10;

  // 1. Fetch and Parse GCode
  useEffect(() => {
    if (!filename) {
      useStore.setState({ gcodeLines: [] });
      return;
    }

    let cancelled = false;
    if (retryRef.current) clearTimeout(retryRef.current);

    const isSim = filename.startsWith(SIM_PREFIX);
    const url   = isSim
      ? `${API}/api/v1/sim/gcode_file`
      : `${API}/api/v1/printer/files/gcodes/${encodeURIComponent(filename)}`;

    const fetchAndParse = async (attempt = 0) => {
      if (cancelled) return;
      try {
        const res  = await fetch(url);
        const text = await res.text();

        if (!res.ok || !text.trim()) {
          if (isSim && attempt < 8) {
            retryRef.current = setTimeout(() => fetchAndParse(attempt + 1), 500);
          }
          return;
        }
        if (cancelled) return;

        const encoder     = new TextEncoder();
        const rawLines    = [];
        const parsedPaths = [];
        const travels     = []; // NEW: [ptA, ptB] pairs for non-extruding moves, for the optional travel overlay
        let currentPath   = [];
        let currentByte   = 0;
        let cx = 0, cy = 0, cz = 0, lastE = 0, isRelativeE = false;
        let currentObject = null;
        let lastPoint     = null; // NEW: most recent point regardless of extruding state

        const lines = text.split("\n");

        for (let idx = 0; idx < lines.length; idx++) {
          const rawLine        = lines[idx];
          const lineWithNL     = idx < lines.length - 1 ? rawLine + "\n" : rawLine;
          const lineByteLength = encoder.encode(lineWithNL).length;

          rawLines.push({ byte: currentByte, text: rawLine.trim() });
          const line = rawLine.trim();

          if (line.startsWith("M83")) isRelativeE = true;
          if (line.startsWith("M82")) isRelativeE = false;
          
          if (line.startsWith("EXCLUDE_OBJECT_START")) {
            const match = line.match(/NAME=([^ ]+)/);
            if (match) currentObject = match[1];
          }
          if (line.startsWith("EXCLUDE_OBJECT_END")) {
            currentObject = null;
          }

          if (line.startsWith("G0") || line.startsWith("G1") || line.startsWith("G2") || line.startsWith("G3")) {
            const mx = line.match(/X([0-9.-]+)/);
            const my = line.match(/Y([0-9.-]+)/);
            const mz = line.match(/Z([0-9.-]+)/);
            const me = line.match(/E([0-9.-]+)/);
            const mi = line.match(/I([0-9.-]+)/);
            const mj = line.match(/J([0-9.-]+)/);

            let prevX = cx, prevY = cy, prevZ = cz;
            if (mx) cx = parseFloat(mx[1]);
            if (my) cy = parseFloat(my[1]);
            if (mz) cz = parseFloat(mz[1]);

            let isArc = line.startsWith("G2") || line.startsWith("G3");
            let isCW = line.startsWith("G2");

            let extruding = false;
            let isExtrudingDelta = false;
            let deltaE = 0;
            if (me) {
              const ce = parseFloat(me[1]);
              if (isRelativeE) {
                if (ce > 0) { isExtrudingDelta = true; deltaE = ce; }
              } else {
                if (ce > lastE) { isExtrudingDelta = true; deltaE = ce - lastE; }
                lastE = ce;
              }
              
              if (isExtrudingDelta) {
                const dist = Math.sqrt((cx - prevX)**2 + (cy - prevY)**2 + (cz - prevZ)**2);
                if (dist > 0) {
                  if ((deltaE / dist) > 0.001) {
                    extruding = true;
                  }
                } else {
                  extruding = true;
                }
              }
            }

            const pointsToAdd = [];
            
            if (isArc && mi && mj) {
              const i = parseFloat(mi[1]);
              const j = parseFloat(mj[1]);
              const centerX = prevX + i;
              const centerY = prevY + j;
              
              let startAngle = Math.atan2(prevY - centerY, prevX - centerX);
              let endAngle = Math.atan2(cy - centerY, cx - centerX);
              
              if (isCW && endAngle > startAngle) endAngle -= 2 * Math.PI;
              if (!isCW && endAngle < startAngle) endAngle += 2 * Math.PI;
              if (Math.abs(endAngle - startAngle) < 0.0001) endAngle += isCW ? -2 * Math.PI : 2 * Math.PI;
              
              const radius = Math.sqrt(i*i + j*j);
              const angleDiff = Math.abs(endAngle - startAngle);
              const arcLength = radius * angleDiff;
              const segments = Math.max(1, Math.ceil(arcLength / 0.2));
              
              for (let step = 1; step <= segments; step++) {
                const t = step / segments;
                const angle = startAngle + (endAngle - startAngle) * t;
                const px = centerX + radius * Math.cos(angle);
                const py = centerY + radius * Math.sin(angle);
                const pz = prevZ + (cz - prevZ) * t;
                pointsToAdd.push([px, py, pz]);
              }
            } else {
              pointsToAdd.push([cx, cy, cz]);
            }

            for (const p of pointsToAdd) {
                const [px, py, pz] = p;
                const scene_x = px / 10;
                const scene_y = pz / 10;
                const scene_z = bedY - py / 10;
                const pt = [scene_x, scene_y, scene_z];
                const ptObj = { byte: currentByte + lineByteLength, pt, obj: currentObject };
                
                if (extruding) {
                  currentPath.push(ptObj);
                } else {
                  if (currentPath.length > 1) parsedPaths.push(currentPath);
                  currentPath = [ptObj];
                  if (lastPoint) travels.push([lastPoint, ptObj]);
                }
                lastPoint = ptObj;
            }
          }
          currentByte += lineByteLength;
        }
        if (currentPath.length > 1) parsedPaths.push(currentPath);

        if (cancelled) return;
        setAllPaths(parsedPaths);
        setTravelSegments(travels);
        useStore.setState({ gcodeLines: rawLines });
      } catch {
        if (!cancelled && isSim && attempt < 8) {
          retryRef.current = setTimeout(() => fetchAndParse(attempt + 1), 500);
        }
      }
    };

    fetchAndParse();
    return () => {
      cancelled = true;
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [filename, bedY]);

  // 2. Initialize the native Three.js Mesh ONCE
  useEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    
    const mat = new THREE.LineBasicMaterial({ color: 0x06b6d4, transparent: true, opacity: 0.6 });
    const geom = new THREE.BufferGeometry();
    const lines = new THREE.LineSegments(geom, mat);
    lines.frustumCulled = false;
    
    group.add(lines);
    linesRef.current = lines;

    // Travel-move overlay: a separate, static mesh (not affected by the
    // byte-based print-progress draw range below — see updateDrawRange).
    // Visibility only, toggled by uiPrefs.gcodeShowTravel.
    const travelMat = new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.35 });
    const travelGeom = new THREE.BufferGeometry();
    const travelLines = new THREE.LineSegments(travelGeom, travelMat);
    travelLines.frustumCulled = false;
    travelLines.visible = false;

    group.add(travelLines);
    travelLinesRef.current = travelLines;

    return () => {
      group.remove(lines);
      group.remove(travelLines);
      geom.dispose();
      mat.dispose();
      travelGeom.dispose();
      travelMat.dispose();
      linesRef.current = null;
      travelLinesRef.current = null;
    };
  }, []);

  // 3. Pre-calculate the massive vertex array and their byte offsets.
  // This only runs when the file is loaded, when an object is explicitly
  // cancelled by the user, or when a display toggle below changes.
  useEffect(() => {
    const lines = linesRef.current;
    if (!lines) return;
    const mat = lines.material;

    if (!allPaths || allPaths.length === 0) {
      lines.geometry.setDrawRange(0, 0);
      lines.userData.bytes = null;
      return;
    }

    // Freeze cancelled objects at the byte position they were cancelled
    const currentPos = useStore.getState().telemetry?.file_position || 0;
    for (const obj of excludedObjects) {
      if (frozenObjectsRef.current[obj] === undefined) {
        frozenObjectsRef.current[obj] = currentPos;
      }
    }

    const isValidPt = (pt) => {
      if (!pt.obj || !excludedObjects.includes(pt.obj)) return true;
      const frozenByte = frozenObjectsRef.current[pt.obj];
      return pt.byte <= frozenByte;
    };

    const validPaths = allPaths
      .map(p => p.filter(isValidPt))
      .filter(p => p.length > 1);

    let count = 0;
    for (let i = 0; i < validPaths.length; i++) {
      count += (validPaths[i].length - 1) * 2;
    }

    if (count === 0) {
      lines.geometry.setDrawRange(0, 0);
      lines.userData.bytes = null;
      return;
    }

    const arr = new Float32Array(count * 3);
    const bytes = new Float32Array(count);

    // Height range for the optional color-by-height gradient — computed
    // over the same points being drawn, so the gradient always spans the
    // full visible model regardless of exclude-object filtering.
    let minH = Infinity, maxH = -Infinity;
    if (colorByHeight) {
      for (let i = 0; i < validPaths.length; i++) {
        for (const pt of validPaths[i]) {
          const h = pt.pt[1];
          if (h < minH) minH = h;
          if (h > maxH) maxH = h;
        }
      }
    }
    const hRange = maxH - minH;
    const colors = colorByHeight ? new Float32Array(count * 3) : null;
    const tmpColor = colorByHeight ? new THREE.Color() : null;

    let idx = 0;
    let vIdx = 0;
    let cIdx = 0;
    for (let i = 0; i < validPaths.length; i++) {
      const p = validPaths[i];
      for (let j = 0; j < p.length - 1; j++) {
        const pt1 = p[j];
        const pt2 = p[j+1];
        
        arr[idx++] = pt1.pt[0]; arr[idx++] = pt1.pt[1]; arr[idx++] = pt1.pt[2];
        bytes[vIdx++] = pt1.byte;
        
        arr[idx++] = pt2.pt[0]; arr[idx++] = pt2.pt[1]; arr[idx++] = pt2.pt[2];
        bytes[vIdx++] = pt2.byte;

        if (colorByHeight) {
          // Blue (low) -> cyan -> green -> yellow -> red (high), the
          // classic "jet"-style height map most slicer viewers use.
          const t1 = hRange > 0 ? (pt1.pt[1] - minH) / hRange : 0;
          const t2 = hRange > 0 ? (pt2.pt[1] - minH) / hRange : 0;
          tmpColor.setHSL(0.66 * (1 - t1), 1, 0.5);
          colors[cIdx++] = tmpColor.r; colors[cIdx++] = tmpColor.g; colors[cIdx++] = tmpColor.b;
          tmpColor.setHSL(0.66 * (1 - t2), 1, 0.5);
          colors[cIdx++] = tmpColor.r; colors[cIdx++] = tmpColor.g; colors[cIdx++] = tmpColor.b;
        }
      }
    }

    lines.geometry.setAttribute('position', new THREE.BufferAttribute(arr, 3));
    if (colorByHeight) {
      lines.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    } else {
      lines.geometry.deleteAttribute('color');
    }
    if (mat.vertexColors !== colorByHeight) {
      mat.vertexColors = colorByHeight;
      mat.color.set(colorByHeight ? 0xffffff : 0x06b6d4);
      mat.needsUpdate = true;
    }
    lines.userData.bytes = bytes;

    // Travel-move overlay: a separate static mesh, filtered by the same
    // exclude-object rule as the extrusion path but not draw-range-synced
    // to print progress (travels are instantaneous jumps, not something a
    // live "how far are we" indicator needs to track segment-by-segment).
    const travelLines = travelLinesRef.current;
    if (travelLines) {
      travelLines.visible = !!showTravel;
      if (showTravel) {
        const validTravels = travelSegments.filter(([a, b]) => isValidPt(a) && isValidPt(b));
        const tArr = new Float32Array(validTravels.length * 6);
        let tIdx = 0;
        for (const [a, b] of validTravels) {
          tArr[tIdx++] = a.pt[0]; tArr[tIdx++] = a.pt[1]; tArr[tIdx++] = a.pt[2];
          tArr[tIdx++] = b.pt[0]; tArr[tIdx++] = b.pt[1]; tArr[tIdx++] = b.pt[2];
        }
        travelLines.geometry.setAttribute('position', new THREE.BufferAttribute(tArr, 3));
        travelLines.geometry.setDrawRange(0, validTravels.length * 2);
      }
    }
    
    // Immediately jump to the current position
    updateDrawRange(useStore.getState().telemetry.file_position);
  }, [allPaths, excludedObjects, colorByHeight, showTravel, travelSegments]);

  // 4. Update the visualizer 60 times a second using a binary search.
  // BYPASSES REACT RENDERING COMPLETELY. NO RECONCILIATION = NO CRASHES.
  function updateDrawRange(filePosition) {
    const lines = linesRef.current;
    if (!lines || !lines.userData || !lines.userData.bytes) return;
    
    const bytes = lines.userData.bytes;
    let low = 0;
    let high = bytes.length - 1;
    let maxIdx = -1;
    
    // Binary search for the last vertex that was printed
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (bytes[mid] <= filePosition) {
        maxIdx = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    
    if (maxIdx === -1) {
      lines.geometry.setDrawRange(0, 0);
    } else {
      lines.geometry.setDrawRange(0, maxIdx + 1);
    }
  }

  // ── Real-time interpolation ────────────────────────────────────────────────
  // Instead of snapping to file_position on every backend tick (which causes
  // bursts of lines appearing at once), we smoothly advance an interpolated
  // position at 60fps between telemetry updates.
  const interpRef = useRef({
    prevPos: 0,
    targetPos: 0,
    prevTime: performance.now(),
    targetTime: performance.now(),
  });

  // On each telemetry tick from the backend, record the new target.
  useEffect(() => {
    const unsub = useStore.subscribe((state) => {
      const fp = state.telemetry?.file_position;
      if (fp == null) return;
      const now = performance.now();
      const r = interpRef.current;
      // The new target is wherever the backend just told us we are.
      // The previous target becomes our new start point.
      r.prevPos  = r.targetPos;
      r.prevTime = r.targetTime ?? now;
      r.targetPos  = fp;
      r.targetTime = now;
    });
    return unsub;
  }, []);

  // Every animation frame, linearly interpolate toward the current target.
  // This makes lines appear one-by-one as the nozzle moves, not in bursts.
  useEffect(() => {
    let rafId;
    const tick = () => {
      const r = interpRef.current;
      const now = performance.now();
      const elapsed = now - r.prevTime;
      const window  = Math.max(1, r.targetTime - r.prevTime);
      const t = Math.min(1, elapsed / window);
      const interpPos = r.prevPos + (r.targetPos - r.prevPos) * t;
      updateDrawRange(interpPos);
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  // if (!filename) return null; // Removed to prevent groupRef from being null on mount

  return <group ref={groupRef} />;
}
