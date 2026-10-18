import React, { useEffect, useState, useMemo } from "react";
import * as THREE from "three";
import { Grid, Line } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { useStore, API } from "./store";

export function PrintBed() {
  const bedTemp   = useStore((s) => s.telemetry?.bedTemp);
  const fault     = useStore((s) => s.telemetry?.fault);
  const bed       = useStore((s) => s.bed);
  const simMode   = useStore((s) => s.simMode);
  const collision = useStore((s) => s.telemetry?.bed_collision_hazard);

  const bx = (bed?.size_x_mm ?? 300) / 10;
  const by = (bed?.size_y_mm ?? 300) / 10;
  const ox = bed?.origin_center ? 0 : bx / 2;
  const oz = bed?.origin_center ? 0 : by / 2;

  const [stlGeometry, setStlGeometry] = useState(null);

  // Load custom bed STL model if configured
  useEffect(() => {
    if (!bed?.has_custom_model) {
      setStlGeometry(null);
      return;
    }

    let isMounted = true;
    let loadedGeometry = null;
    const loader = new STLLoader();
    loader.load(
      `${API}/api/v1/bed/model?t=${Date.now()}`,
      (geometry) => {
        if (!isMounted) { geometry.dispose(); return; }
        geometry.computeVertexNormals();
        // Scale from mm to Three.js world units (10mm = 1 unit)
        geometry.scale(0.1, 0.1, 0.1);
        loadedGeometry = geometry;
        setStlGeometry(geometry);
      },
      undefined,
      (err) => {
        console.warn("Could not load custom bed STL:", err);
        if (isMounted) setStlGeometry(null);
      }
    );

    return () => {
      isMounted = false;
      // Dispose geometry to prevent GPU memory leak
      if (loadedGeometry) loadedGeometry.dispose();
    };
  }, [bed?.has_custom_model, bed?.custom_model_filename]);

  const color = fault        ? "#ef4444"
              : collision    ? "#b91c1c"
              : simMode      ? "#1e3a5f"
              : bedTemp > 50 ? "#f97316"
              : "#374151";

  // Parse exclusion zones into renderable bounding boxes / centers
  // IMPORTANT: printer Y → Three.js -Z  (same flip as Viewport.jsx: sceneZ = by - y/10)
  const exclusionZones = useMemo(() => {
    if (!bed?.bed_exclude_area || !Array.isArray(bed.bed_exclude_area)) return [];

    return bed.bed_exclude_area.map((poly, idx) => {
      if (!Array.isArray(poly) || poly.length < 3) return null;
      const xs = poly.map((p) => p[0] / 10);
      const ys = poly.map((p) => by - p[1] / 10);   // Y-flip to match scene coords
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);

      const w = Math.max(0.4, maxX - minX);
      const d = Math.max(0.4, maxY - minY);
      const cx = minX + w / 2;
      const cz = minY + d / 2;   // already flipped above

      return { id: idx, cx, cz, w, d };
    }).filter(Boolean);
  }, [bed?.bed_exclude_area, by]);

  // Printable perimeter line points (Y-flipped to match scene coords)
  const perimeterPoints = useMemo(() => {
    if (!bed?.printable_area || !Array.isArray(bed.printable_area) || bed.printable_area.length < 3) {
      return null;
    }
    const pts = bed.printable_area.map((p) => new THREE.Vector3(p[0] / 10, 0.02, by - p[1] / 10));
    // Close the loop
    pts.push(pts[0].clone());
    return pts;
  }, [bed?.printable_area, by]);

  return (
    <group>
      {/* 1. Physical Bed Geometry: Custom STL or Procedural Slab */}
      {stlGeometry ? (
        <mesh
          geometry={stlGeometry}
          position={[0, 0, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <meshStandardMaterial
            color="#64748b"
            roughness={0.4}
            metalness={0.6}
          />
        </mesh>
      ) : (
        <mesh position={[ox, -0.5, oz]}>
          <boxGeometry args={[bx, 1, by]} />
          <meshStandardMaterial color={color} transparent opacity={0.6} />
        </mesh>
      )}

      {/* 2. Calibration Grid */}
      <Grid
        position={[ox, 0.01, oz]}
        args={[bx, by]}
        cellSize={1} cellThickness={1} cellColor="#6b7280"
        sectionSize={5} sectionThickness={1.5} sectionColor="#4b5563"
      />

      {/* 3. Printable Area Perimeter Outline */}
      {perimeterPoints && (
        <Line
          points={perimeterPoints}
          color="#10b981"
          lineWidth={2}
          dashed={false}
        />
      )}

      {/* 4. Hardware Exclusion Zones (Bed Leveling Screws & Clips) */}
      {exclusionZones.map((zone) => (
        <group key={zone.id} position={[zone.cx, 0.03, zone.cz]}>
          {/* Keepout floor patch */}
          <mesh position={[0, 0.02, 0]}>
            <boxGeometry args={[zone.w, 0.05, zone.d]} />
            <meshStandardMaterial
              color={collision ? "#ef4444" : "#dc2626"}
              transparent
              opacity={0.65}
            />
          </mesh>

          {/* Screw head / Clamp hardware cylinder */}
          <mesh position={[0, 0.15, 0]}>
            <cylinderGeometry
              args={[
                Math.min(zone.w, zone.d) * 0.35,
                Math.min(zone.w, zone.d) * 0.35,
                0.3,
                16
              ]}
            />
            <meshStandardMaterial
              color="#7f1d1d"
              metalness={0.8}
              roughness={0.2}
            />
          </mesh>
        </group>
      ))}
    </group>
  );
}
