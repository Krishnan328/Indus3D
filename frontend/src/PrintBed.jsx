import React from "react";
import { Grid } from "@react-three/drei";
import { useStore } from "./store";

export function PrintBed() {
  const bedTemp = useStore((s) => s.telemetry.bedTemp);
  const fault   = useStore((s) => s.telemetry.fault);
  const bed     = useStore((s) => s.bed);
  const simMode = useStore((s) => s.simMode);

  const bx = (bed.size_x_mm ?? 300) / 10;
  const by = (bed.size_y_mm ?? 300) / 10;
  const ox = bed.origin_center ? 0 : bx / 2;
  const oz = bed.origin_center ? 0 : by / 2;

  const color = fault        ? "#ef4444"
              : simMode      ? "#1e3a5f"
              : bedTemp > 50 ? "#f97316"
              : "#374151";

  return (
    <group>
      <mesh position={[ox, -0.5, oz]}>
        <boxGeometry args={[bx, 1, by]} />
        <meshStandardMaterial color={color} transparent opacity={0.6} />
      </mesh>
      <Grid
        position={[ox, 0.01, oz]}
        args={[bx, by]}
        cellSize={1} cellThickness={1} cellColor="#6b7280"
        sectionSize={5} sectionThickness={1.5} sectionColor="#4b5563"
      />
    </group>
  );
}
