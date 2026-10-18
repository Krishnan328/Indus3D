import React, { useRef, useState, useEffect, useMemo } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Environment, GizmoHelper, GizmoViewcube } from "@react-three/drei";
import * as THREE from "three";
import { useStore } from "./store";
import { PrintBed } from "./PrintBed";
import { GCodeVisualizerV2 } from "./GCodeVisualizerV2";
import { useThemeTokens, useIsBrutalist } from "./theme";
import { ErrorBoundary } from "./ErrorBoundary";

import { Box } from "@react-three/drei";

function ExcludeObjects() {
  const bed = useStore((s) => s.bed);
  const excludeObjectState = useStore(s => s.exclude_object) || {};
  const excludeObjectAction = useStore(s => s.excludeObject);

  if (!excludeObjectState || !excludeObjectState.objects) return null;

  const by = (bed.size_y_mm ?? 300) / 10;

  return excludeObjectState.objects.map((obj, i) => {
    let width = 20;
    let depth = 20;
    let cx = obj.center?.[0] || 0;
    let cy = obj.center?.[1] || 0;

    if (obj.polygon && obj.polygon.length > 0) {
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const [x, y] of obj.polygon) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
      width = maxX - minX;
      depth = maxY - minY;
      cx = minX + width / 2;
      cy = minY + depth / 2;
    }

    const sceneX = cx / 10;
    const sceneZ = by - cy / 10;
    const isExcluded = excludeObjectState.excluded_objects?.includes(obj.name);

    return (
      <Box
        key={obj.name || i}
        args={[width / 10, 0.4, depth / 10]}
        position={[sceneX, 0.2, sceneZ]}
        onClick={(e) => {
          e.stopPropagation();
          excludeObjectAction(obj.name);
        }}
        onPointerOver={(e) => { e.object.material.opacity = 0.8; document.body.style.cursor = 'pointer'; }}
        onPointerOut={(e) => { e.object.material.opacity = 0.3; document.body.style.cursor = 'auto'; }}
      >
        <meshBasicMaterial
          color={isExcluded ? "#ef4444" : "#3b82f6"}
          transparent
          opacity={0.3}
          wireframe={isExcluded}
        />
      </Box>
    );
  });
}


// ── Toolhead 3D object ──────────────────────────────────────────────────────
// Moved from App.jsx verbatim. Do not change the Y-flip mapping here without
// also changing it in GCodeVisualizerV2.jsx — see CLAUDE_CONTEXT.md.

// ── Digital Twin Reality Trail ──────────────────────────────────────────────
function DigitalTwinTrail() {
  const bed = useStore((s) => s.bed);
  const bx = (bed.size_x_mm ?? 300) / 10;
  const by = (bed.size_y_mm ?? 300) / 10;

  const trailRef = useRef();
  const trailPositions = useMemo(() => new Float32Array(5000 * 3), []);
  const trailColors = useMemo(() => new Float32Array(5000 * 3), []);
  const trailCount = useRef(0);
  const lastTrailPos = useRef(new THREE.Vector3());


  const trailGeom = useMemo(() => {
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(trailPositions, 3));
    geom.setAttribute('color', new THREE.BufferAttribute(trailColors, 3));
    geom.setDrawRange(0, 0);
    return geom;
  }, [trailPositions, trailColors]);

  useFrame(() => {
    const state = useStore.getState();
    if (!state.telemetry || !trailRef.current) return;

    const x = state.telemetry.live_x || 0;
    const y = state.telemetry.live_y || 0;
    const z = state.telemetry.live_z || 0;
    const isPrinting = state.telemetry.state === "printing";
    const fault = state.telemetry.fault;
    const temp = state.telemetry.ext_temp || 0;
    const target = state.telemetry.ext_target || 0;

    const sceneX = x / 10;
    const sceneY = (z / 10) + 0.1;
    const sceneZ = by - y / 10;

    const currentPos = new THREE.Vector3(sceneX, sceneY, sceneZ);

    // Always update last pos if not printing
    if (!isPrinting) {
      lastTrailPos.current.copy(currentPos);
      return;
    }

    if (currentPos.distanceTo(lastTrailPos.current) > 0.05) {
      if (trailCount.current < 5000) {
        const idx = trailCount.current * 3;
        trailPositions[idx] = sceneX;
        trailPositions[idx + 1] = sceneY;
        trailPositions[idx + 2] = sceneZ;

        let r = 0.13, g = 0.77, b = 0.36; // Green
        if (fault) {
           r = 0.93; g = 0.26; b = 0.26; // Red
        } else if (target > 0 && temp < target - 5) {
           r = 0.37; g = 0.64; b = 0.98; // Blue
        }

        trailColors[idx] = r;
        trailColors[idx + 1] = g;
        trailColors[idx + 2] = b;

        trailCount.current += 1;
        lastTrailPos.current.copy(currentPos);

        trailGeom.setDrawRange(0, trailCount.current);
        trailGeom.attributes.position.needsUpdate = true;
        trailGeom.attributes.color.needsUpdate = true;
      }
    }
  });

  return (
    <line ref={trailRef} geometry={trailGeom}>
      <lineBasicMaterial vertexColors linewidth={3} />
    </line>
  );
}

function Toolhead() {
  const fault      = useStore((s) => s.telemetry?.fault);
  const isPrinting = useStore((s) => s.telemetry?.state === "printing");
  const bed        = useStore((s) => s.bed);
  const meshRef    = useRef();

  const ox   = (bed.origin_center ? 0 : (bed.size_x_mm ?? 300) / 2) / 10;
  const oz   = (bed.origin_center ? 0 : (bed.size_y_mm ?? 300) / 2) / 10;
  const bedY = (bed.size_y_mm ?? 300) / 10;

  useFrame(() => {
    const { live_x: x, live_y: y, live_z: z } = useStore.getState().telemetry;
    if (!meshRef.current) return;
    meshRef.current.position.x = THREE.MathUtils.lerp(
      meshRef.current.position.x, (Number(x) || 0) / 10, 0.2);
    meshRef.current.position.y = THREE.MathUtils.lerp(
      meshRef.current.position.y, (Number(z) || 0) / 10 + 0.9, 0.2);
    meshRef.current.position.z = THREE.MathUtils.lerp(
      meshRef.current.position.z, bedY - (Number(y) || 0) / 10, 0.2);
  });

  const color = fault ? "#ef4444" : isPrinting ? "#3b82f6" : "#578396";
  return (
    <mesh ref={meshRef} position={[ox, 0.9, oz]}>
      <cylinderGeometry args={[0.15, 0.15, 1.2, 32]} />
      <meshPhysicalMaterial color={color} transmission={1} ior={1.5} thickness={1.5} roughness={0.15} transparent />
      <mesh position={[0, -0.75, 0]} rotation={[Math.PI, 0, 0]}>
        <coneGeometry args={[0.15, 0.3, 32]} />
        <meshStandardMaterial color={isPrinting ? "#fbbf24" : "#9ca3af"} metalness={0.9} roughness={0.2}
          emissive={isPrinting ? "#fbbf24" : "#000000"} emissiveIntensity={0.6} />
      </mesh>
    </mesh>
  );
}

function SceneContents({ isDarkMode, ox, oz }) {
  const showAxes = useStore((s) => s.uiPrefs.gcodeShowAxes);
  return (
    <>
      <ambientLight intensity={isDarkMode ? 0.3 : 0.8} />
      <directionalLight position={[10, 20, 10]} intensity={1.5} />
      <pointLight position={[ox, 10, oz]} intensity={0.5} />
      {/* <Environment preset="city" /> */}
      <PrintBed />
      <ExcludeObjects bed={useStore.getState().bed} />
      <Toolhead />
      <GCodeVisualizerV2 />
      <DigitalTwinTrail />
      {showAxes && <axesHelper args={[Math.max(ox, oz, 10) * 0.6]} />}
      <OrbitControls target={[ox, 0, oz]} maxPolarAngle={Math.PI / 2 - 0.05} makeDefault
        enableDamping dampingFactor={0.2} rotateSpeed={1.8} zoomSpeed={1.5} panSpeed={1.2} />
      <GizmoHelper alignment="bottom-right" margin={[80, 80]}>
        <GizmoViewcube color="white" strokeColor="gray" textColor="black" hoverColor="#60a5fa" opacity={0.8} />
      </GizmoHelper>
    </>
  );
}

// ── Viewport panel ───────────────────────────────────────────────────────────
// Default size is one grid cell (compact) — click Expand for a fullscreen
// overlay. Same Canvas/scene either way; only the container size changes.
export function Viewport({ isDarkMode }) {
  const [expanded, setExpanded] = useState(false);
  const bed = useStore((s) => s.bed);
  const simMode = useStore((s) => s.simMode);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const bx = (bed.size_x_mm ?? 300) / 10;
  const by = (bed.size_y_mm ?? 300) / 10;
  const ox = bed.origin_center ? 0 : bx / 2;
  const oz = bed.origin_center ? 0 : by / 2;

  const canvasBlock = (
    <ErrorBoundary>
      <Canvas camera={{ position: [ox, ox * 1.2 + 8, oz + 18], fov: 50 }}>
        <SceneContents isDarkMode={isDarkMode} ox={ox} oz={oz} />
      </Canvas>
    </ErrorBoundary>
  );

  const header = (
    <div className="flex items-center justify-between px-3 py-2 shrink-0">
      <span className={`${t.heading} ${brutalist ? "" : "opacity-70"}`}>
        Unified Digital Twin{simMode ? " — sim" : ""}
      </span>
      <button
        onClick={() => setExpanded((e) => !e)}
        title={expanded ? "Collapse" : "Expand"}
        className={`p-1 opacity-60 hover:opacity-100 transition-opacity`}
      >
        {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
      </button>
    </div>
  );

  if (expanded) {
    return (
      <div className="fixed inset-4 z-50 flex flex-col overflow-hidden bg-black/40 backdrop-blur-sm p-4">
        <div className={`flex-1 flex flex-col overflow-hidden ${t.panel}`}>
          {header}
          <div className="flex-1 min-h-0">{canvasBlock}</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`h-full flex flex-col overflow-hidden ${t.panel}`}>
      {header}
      <div className="flex-1 min-h-0 mx-3 mb-3">{canvasBlock}</div>
    </div>
  );
}
