import React, { useRef, useState } from "react";
import { Maximize2, Minimize2, Layers, Ban, Check, X, AlertTriangle } from "lucide-react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Environment, GizmoHelper, GizmoViewcube, Box, Html } from "@react-three/drei";
import * as THREE from "three";
import { useStore } from "./store";
import { PrintBed } from "./PrintBed";
import { GCodeVisualizerV2 } from "./GCodeVisualizerV2";
import { useThemeTokens, useIsBrutalist } from "./theme";
import { ErrorBoundary } from "./ErrorBoundary";

function ExcludeObjects() {
  const bed = useStore((s) => s.bed);
  const excludeObjectState = useStore((s) => s.exclude_object) || {};
  const excludeObjectAction = useStore((s) => s.excludeObject);
  const [hoveredName, setHoveredName] = useState(null);

  if (!excludeObjectState || !excludeObjectState.objects) return null;

  const by = (bed.size_y_mm ?? 300) / 10;

  return (
    <>
      {excludeObjectState.objects.map((obj, i) => {
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
          width = Math.max(maxX - minX, 10);
          depth = Math.max(maxY - minY, 10);
          cx = minX + width / 2;
          cy = minY + depth / 2;
        }

        const sceneX = cx / 10;
        const sceneZ = by - cy / 10;
        const isExcluded = excludeObjectState.excluded_objects?.includes(obj.name);
        const isHovered = hoveredName === obj.name;

        return (
          <group key={obj.name || i}>
            <Box
              args={[width / 10, 0.4, depth / 10]}
              position={[sceneX, 0.2, sceneZ]}
              onClick={(e) => {
                e.stopPropagation();
                if (window.confirm(`Exclude / Cancel print of object '${obj.name}'?`)) {
                  excludeObjectAction(obj.name);
                }
              }}
              onPointerOver={(e) => {
                e.stopPropagation();
                setHoveredName(obj.name);
                document.body.style.cursor = "pointer";
              }}
              onPointerOut={(e) => {
                e.stopPropagation();
                setHoveredName(null);
                document.body.style.cursor = "auto";
              }}
            >
              <meshBasicMaterial
                color={isExcluded ? "#ef4444" : isHovered ? "#60a5fa" : "#3b82f6"}
                transparent
                opacity={isExcluded ? 0.35 : isHovered ? 0.65 : 0.2}
                wireframe={isExcluded}
              />
            </Box>

            {isHovered && (
              <Html position={[sceneX, 0.8, sceneZ]} center distanceFactor={18} style={{ pointerEvents: "none" }}>
                <div className="bg-slate-900/90 border border-slate-700 text-white text-[11px] font-mono px-2 py-1 rounded shadow-lg whitespace-nowrap flex items-center gap-1.5 backdrop-blur-md">
                  <span className={`w-2 h-2 rounded-full ${isExcluded ? "bg-red-500" : "bg-emerald-400"}`} />
                  <span className="font-semibold">{obj.name}</span>
                  <span className="opacity-60 text-[9px]">({width.toFixed(0)}×{depth.toFixed(0)}mm)</span>
                  <span className={`text-[9px] px-1 py-0.5 rounded ${isExcluded ? "bg-red-500/20 text-red-300" : "bg-blue-500/20 text-blue-300"}`}>
                    {isExcluded ? "CANCELLED" : "CLICK TO CANCEL"}
                  </span>
                </div>
              </Html>
            )}
          </group>
        );
      })}
    </>
  );
}


// ── Toolhead 3D object ──────────────────────────────────────────────────────
// Moved from App.jsx verbatim. Do not change the Y-flip mapping here without
// also changing it in GCodeVisualizerV2.jsx — see CLAUDE_CONTEXT.md.

export const NOZZLE_STYLES = {
  brass: {
    name: "Brass",
    color: "#d97706",         // Warm golden brass
    metalness: 0.88,
    roughness: 0.28,
    hotColor: "#f59e0b",
    hotGlow: "#fbbf24",
  },
  "hardened steel": {
    name: "Hardened Steel",
    color: "#52525b",         // Gunmetal matte dark steel gray
    metalness: 0.78,
    roughness: 0.45,
    hotColor: "#ea580c",
    hotGlow: "#f97316",
  },
  "stainless steel": {
    name: "Stainless Steel",
    color: "#cbd5e1",         // Shiny polished silver-chrome
    metalness: 0.92,
    roughness: 0.18,
    hotColor: "#f59e0b",
    hotGlow: "#fbbf24",
  },
  "plated copper": {
    name: "Plated Copper",
    color: "#c2410c",         // Warm metallic reddish-copper
    metalness: 0.90,
    roughness: 0.20,
    hotColor: "#f97316",
    hotGlow: "#fb923c",
  },
  "tungsten carbide": {
    name: "Tungsten Carbide",
    color: "#1e293b",         // Deep dark anthracite / graphite
    metalness: 0.85,
    roughness: 0.32,
    hotColor: "#ea580c",
    hotGlow: "#f97316",
  },
  "ruby-tipped": {
    name: "Ruby-tipped",
    color: "#e11d48",         // Radiant jewel ruby red
    metalness: 0.35,
    roughness: 0.12,
    hotColor: "#f43f5e",
    hotGlow: "#fb7185",
  },
  "diamond-tipped": {
    name: "Diamond-tipped",
    color: "#7dd3fc",         // Crystalline ice-blue diamond
    metalness: 0.45,
    roughness: 0.08,
    hotColor: "#38bdf8",
    hotGlow: "#60a5fa",
  },
};

export function getNozzleStyle(rawMaterial) {
  const norm = String(rawMaterial || "").toLowerCase().trim();
  if (norm.includes("hardened") || (norm.includes("steel") && !norm.includes("stainless"))) {
    return NOZZLE_STYLES["hardened steel"];
  }
  if (norm.includes("stainless")) {
    return NOZZLE_STYLES["stainless steel"];
  }
  if (norm.includes("copper")) {
    return NOZZLE_STYLES["plated copper"];
  }
  if (norm.includes("tungsten") || norm.includes("carbide")) {
    return NOZZLE_STYLES["tungsten carbide"];
  }
  if (norm.includes("ruby")) {
    return NOZZLE_STYLES["ruby-tipped"];
  }
  if (norm.includes("diamond")) {
    return NOZZLE_STYLES["diamond-tipped"];
  }
  return NOZZLE_STYLES.brass;
}

// ── Digital Twin Reality Trail ──────────────────────────────────────────────
function DigitalTwinTrail() {
  const bed = useStore((s) => s.bed);

  const trailRef = useRef();
  const trailCount = useRef(0);
  const lastTrailPos = useRef(new THREE.Vector3());
  const trailDataRef = useRef(null);
  if (trailDataRef.current == null) {
    const positions = new Float32Array(5000 * 3);
    const colors = new Float32Array(5000 * 3);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.setDrawRange(0, 0);
    trailDataRef.current = { positions, colors, geometry };
  }

  useFrame(() => {
    const { positions, colors, geometry } = trailDataRef.current;
    const state = useStore.getState();
    if (!state.telemetry || !trailRef.current) return;

    // When a G-code model is loaded/printing, GCodeVisualizerV2 handles toolpath visualization.
    // Suppress DigitalTwinTrail so it doesn't draw spurious diagonal lines across the bed.
    if (state.telemetry.filename) {
      if (trailCount.current > 0) {
        trailCount.current = 0;
        geometry.setDrawRange(0, 0);
      }
      return;
    }

    const telem = state.telemetry;
    const currentBed = state.bed || bed;
    const bSizeX = currentBed.size_x_mm ?? 320;
    const bSizeY = currentBed.size_y_mm ?? 320;
    const bSizeZ = currentBed.size_z_mm ?? 380;
    const currentBy = bSizeY / 10;

    const rawX = Number.isFinite(telem.live_x) ? telem.live_x : (Number.isFinite(telem.x) ? telem.x : 0);
    const rawY = Number.isFinite(telem.live_y) ? telem.live_y : (Number.isFinite(telem.y) ? telem.y : 0);
    const rawZ = Number.isFinite(telem.live_z) ? telem.live_z : (Number.isFinite(telem.z) ? telem.z : 0);

    const x = Math.max(0, Math.min(bSizeX, Number(rawX) || 0));
    const y = Math.max(0, Math.min(bSizeY, Number(rawY) || 0));
    const z = Math.max(0, Math.min(bSizeZ, Number(rawZ) || 0));
    const isPrinting = telem.state === "printing";
    const fault = telem.fault;
    const temp = telem.extTemp ?? telem.ext_temp ?? 0;
    const target = telem.extTarget ?? telem.ext_target ?? 0;

    const sceneX = x / 10;
    const sceneY = (z / 10) + 0.1;
    const sceneZ = currentBy - y / 10;

    const currentPos = new THREE.Vector3(sceneX, sceneY, sceneZ);

    // Always update last pos and reset trail if not printing
    if (!isPrinting) {
      if (trailCount.current > 0) {
        trailCount.current = 0;
        geometry.setDrawRange(0, 0);
      }
      lastTrailPos.current.copy(currentPos);
      return;
    }

    const dist = currentPos.distanceTo(lastTrailPos.current);
    // Don't connect rapid travel jumps (> 15mm) with a spurious line
    if (dist > 1.5) {
      lastTrailPos.current.copy(currentPos);
      return;
    }

    if (dist > 0.05) {
      if (trailCount.current < 5000) {
        const idx = trailCount.current * 3;
        positions[idx] = sceneX;
        positions[idx + 1] = sceneY;
        positions[idx + 2] = sceneZ;

        let r = 0.13, g = 0.77, b = 0.36; // Green
        if (fault) {
           r = 0.93; g = 0.26; b = 0.26; // Red
        } else if (target > 0 && temp < target - 5) {
           r = 0.37; g = 0.64; b = 0.98; // Blue
        }

        colors[idx] = r;
        colors[idx + 1] = g;
        colors[idx + 2] = b;

        trailCount.current += 1;
        lastTrailPos.current.copy(currentPos);

        geometry.setDrawRange(0, trailCount.current);
        geometry.attributes.position.needsUpdate = true;
        geometry.attributes.color.needsUpdate = true;
      }
    }
  });

  return (
    <line ref={trailRef} geometry={trailDataRef.current.geometry}>
      <lineBasicMaterial vertexColors linewidth={3} />
    </line>
  );
}

function Toolhead() {
  const fault      = useStore((s) => s.telemetry?.fault);
  const isPrinting = useStore((s) => s.telemetry?.state === "printing");
  const extTemp    = useStore((s) => s.telemetry?.extTemp) || 0;
  const nozzleMat  = useStore((s) => s.maintenanceConfig?.nozzle_material) || "Brass";
  const bed        = useStore((s) => s.bed);
  const meshRef    = useRef();
  const shadowRef  = useRef();

  const ox   = (bed.origin_center ? 0 : (bed.size_x_mm ?? 320) / 2) / 10;
  const oz   = (bed.origin_center ? 0 : (bed.size_y_mm ?? 320) / 2) / 10;

  useFrame((_, delta) => {
    const state = useStore.getState();
    const telem = state.telemetry;
    const currentBed = state.bed || bed;
    if (!meshRef.current || !telem) return;

    const bSizeX = currentBed.size_x_mm ?? 320;
    const bSizeY = currentBed.size_y_mm ?? 320;
    const bSizeZ = currentBed.size_z_mm ?? 380;
    const currentBedY = bSizeY / 10;

    // Ground-truth live position (stepper kinematics from motion_report)
    const liveRawX = Number.isFinite(telem.live_x) ? telem.live_x : (Number.isFinite(telem.x) ? telem.x : 0);
    const liveRawY = Number.isFinite(telem.live_y) ? telem.live_y : (Number.isFinite(telem.y) ? telem.y : 0);
    const liveRawZ = Number.isFinite(telem.live_z) ? telem.live_z : (Number.isFinite(telem.z) ? telem.z : 0);

    const clampedLiveX = Math.max(0, Math.min(bSizeX, Number(liveRawX) || 0));
    const clampedLiveY = Math.max(0, Math.min(bSizeY, Number(liveRawY) || 0));
    const clampedLiveZ = Math.max(0, Math.min(bSizeZ, Number(liveRawZ) || 0));

    const liveX = clampedLiveX / 10;
    const liveY = clampedLiveZ / 10 + 0.9;
    const liveZ = currentBedY - clampedLiveY / 10;

    const currentPos = meshRef.current.position;

    // Snap on initial mount or extreme teleport (> 150 mm)
    const distToLive = Math.hypot(liveX - currentPos.x, liveY - currentPos.y, liveZ - currentPos.z);
    if (distToLive > 15.0 || isNaN(currentPos.x)) {
      currentPos.set(liveX, liveY, liveZ);
      if (shadowRef.current) {
        shadowRef.current.position.x = liveX;
        shadowRef.current.position.z = liveZ;
      }
      return;
    }

    const dt = Math.min(delta, 0.1);
    // Smooth 60 FPS exponential tracking to ground-truth physical toolhead
    const factor = 1.0 - Math.exp(-25 * dt);
    currentPos.x = THREE.MathUtils.lerp(currentPos.x, liveX, factor);
    currentPos.y = THREE.MathUtils.lerp(currentPos.y, liveY, factor);
    currentPos.z = THREE.MathUtils.lerp(currentPos.z, liveZ, factor);

    if (shadowRef.current) {
      shadowRef.current.position.x = currentPos.x;
      shadowRef.current.position.z = currentPos.z;
    }
  });

  const statusColor = fault ? "#ef4444" : isPrinting ? "#3b82f6" : "#10b981";
  const nozzleHot = isPrinting || extTemp > 50;
  const nozzleStyle = getNozzleStyle(nozzleMat);

  return (
    <group>
      {/* 1. Bed Surface Projection Reticle — shows exact (X, Y) spot on the bed */}
      <mesh ref={shadowRef} position={[ox, 0.02, oz]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.2, 0.32, 32]} />
        <meshBasicMaterial color={statusColor} transparent opacity={0.4} />
      </mesh>

      {/* 2. Toolhead 3D Assembly */}
      <group ref={meshRef} position={[ox, 0.9, oz]}>
        {/* Heatsink Body */}
        <mesh position={[0, 0.1, 0]}>
          <cylinderGeometry args={[0.35, 0.35, 0.8, 24]} />
          <meshStandardMaterial color="#1e293b" metalness={0.7} roughness={0.3} />
        </mesh>
        {/* Cooling Ribs Accent */}
        <mesh position={[0, 0.25, 0]}>
          <cylinderGeometry args={[0.4, 0.4, 0.08, 24]} />
          <meshStandardMaterial color="#334155" metalness={0.8} roughness={0.2} />
        </mesh>
        <mesh position={[0, -0.05, 0]}>
          <cylinderGeometry args={[0.4, 0.4, 0.08, 24]} />
          <meshStandardMaterial color="#334155" metalness={0.8} roughness={0.2} />
        </mesh>

        {/* Status Indicator LED Ring */}
        <mesh position={[0, 0.48, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.36, 0.04, 16, 32]} />
          <meshStandardMaterial
            color={statusColor}
            emissive={statusColor}
            emissiveIntensity={0.8}
            toneMapped={false}
          />
        </mesh>

        {/* Heater Block */}
        <mesh position={[0, -0.42, 0]}>
          <boxGeometry args={[0.55, 0.3, 0.45]} />
          <meshStandardMaterial color="#94a3b8" metalness={0.85} roughness={0.25} />
        </mesh>

        {/* Dynamic Material Nozzle Tip (preserves exact cone geometry: points down to Y = -0.90) */}
        <mesh position={[0, -0.675, 0]} rotation={[Math.PI, 0, 0]}>
          <coneGeometry args={[0.22, 0.45, 24]} />
          <meshStandardMaterial
            color={nozzleHot ? nozzleStyle.hotColor : nozzleStyle.color}
            metalness={nozzleStyle.metalness}
            roughness={nozzleStyle.roughness}
            emissive={nozzleHot ? nozzleStyle.hotGlow : "#000000"}
            emissiveIntensity={nozzleHot ? 0.65 : 0.0}
          />
        </mesh>
      </group>
    </group>
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
  const [showObjects, setShowObjects] = useState(false);
  const bed = useStore((s) => s.bed);
  const simMode = useStore((s) => s.simMode);
  const excludeObjectState = useStore((s) => s.exclude_object) || {};
  const excludeObjectAction = useStore((s) => s.excludeObject);
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();

  const bx = (bed.size_x_mm ?? 320) / 10;
  const by = (bed.size_y_mm ?? 320) / 10;
  const ox = bed.origin_center ? 0 : bx / 2;
  const oz = bed.origin_center ? 0 : by / 2;
  const nozzleMat = useStore((s) => s.maintenanceConfig?.nozzle_material) || "Brass";
  const nozzleStyle = getNozzleStyle(nozzleMat);

  const objects = excludeObjectState.objects || [];
  const excludedNames = excludeObjectState.excluded_objects || [];
  const activeCount = objects.filter((o) => !excludedNames.includes(o.name)).length;
  const totalCount = objects.length;

  const canvasBlock = (
    <ErrorBoundary>
      <Canvas camera={{ position: [ox, ox * 1.2 + 8, oz + 18], fov: 50 }}>
        <SceneContents isDarkMode={isDarkMode} ox={ox} oz={oz} />
      </Canvas>
    </ErrorBoundary>
  );

  const objectsDrawer = showObjects && totalCount > 0 && (
    <div className="absolute top-12 right-4 z-40 w-72 max-h-80 bg-slate-950/95 border border-slate-700/80 rounded-lg shadow-2xl p-3 flex flex-col backdrop-blur-md font-mono text-xs">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
        <span className="font-semibold text-slate-200 flex items-center gap-1.5">
          <Layers size={13} className="text-blue-400" /> Print Objects ({activeCount}/{totalCount})
        </span>
        <button
          onClick={() => setShowObjects(false)}
          className="text-slate-400 hover:text-white p-0.5"
        >
          <X size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-1.5 py-2 pr-1 custom-scrollbar">
        {objects.map((obj, idx) => {
          const isCancelled = excludedNames.includes(obj.name);
          return (
            <div
              key={obj.name || idx}
              className={`p-2 rounded border transition-colors flex items-center justify-between ${
                isCancelled
                  ? "bg-red-950/30 border-red-900/50 text-slate-400"
                  : "bg-slate-900/60 border-slate-800 text-slate-200"
              }`}
            >
              <div className="flex flex-col min-w-0 pr-2">
                <span className={`truncate font-medium ${isCancelled ? "line-through opacity-70" : ""}`}>
                  {obj.name}
                </span>
                <span className="text-[10px] text-slate-400">
                  {obj.center ? `pos: (${obj.center[0].toFixed(0)}, ${obj.center[1].toFixed(0)})` : "area defined"}
                </span>
              </div>
              <button
                disabled={isCancelled}
                onClick={() => {
                  if (window.confirm(`Exclude '${obj.name}' from printing?`)) {
                    excludeObjectAction(obj.name);
                  }
                }}
                className={`px-2 py-1 rounded text-[10px] font-semibold flex items-center gap-1 shrink-0 ${
                  isCancelled
                    ? "bg-slate-800 text-slate-500 cursor-not-allowed"
                    : "bg-red-500/20 text-red-400 hover:bg-red-500/40 border border-red-500/30"
                }`}
              >
                {isCancelled ? <Check size={10} /> : <Ban size={10} />}
                {isCancelled ? "Cancelled" : "Cancel"}
              </button>
            </div>
          );
        })}
      </div>
      <div className="pt-2 border-t border-slate-800 text-[10px] text-slate-400 flex items-center gap-1">
        <AlertTriangle size={11} className="text-amber-400 shrink-0" />
        <span>Click 3D bounding box or list button to cancel defect object</span>
      </div>
    </div>
  );

  const header = (
    <div className="flex items-center justify-between px-3 py-2 shrink-0">
      <div className="flex items-center gap-2">
        <span className={`${t.heading} ${brutalist ? "" : "opacity-70"}`}>
          Unified Digital Twin{simMode ? " — sim" : ""}
        </span>
        <span
          className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono border"
          style={{
            borderColor: `${nozzleStyle.color}66`,
            backgroundColor: `${nozzleStyle.color}18`,
            color: nozzleStyle.color,
          }}
          title={`Active Nozzle Material: ${nozzleStyle.name}`}
        >
          <span
            className="w-1.5 h-1.5 rounded-full inline-block shrink-0"
            style={{ backgroundColor: nozzleStyle.color }}
          />
          {nozzleStyle.name}
        </span>
        {totalCount > 0 && (
          <button
            onClick={() => setShowObjects((s) => !s)}
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono border transition-colors ${
              showObjects
                ? "bg-blue-500/30 border-blue-400 text-blue-200"
                : "bg-blue-500/10 border-blue-500/30 text-blue-400 hover:bg-blue-500/20"
            }`}
            title="Inspect and cancel individual objects in this print"
          >
            <Layers size={11} />
            Objects ({activeCount}/{totalCount})
          </button>
        )}
      </div>
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
        <div className={`flex-1 flex flex-col overflow-hidden relative ${t.panel}`}>
          {header}
          {objectsDrawer}
          <div className="flex-1 min-h-0">{canvasBlock}</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`h-full flex flex-col overflow-hidden relative ${t.panel}`}>
      {header}
      {objectsDrawer}
      <div className="flex-1 min-h-0 mx-3 mb-3">{canvasBlock}</div>
    </div>
  );
}
