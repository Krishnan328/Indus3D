/**
 * GCodeVisualizer.jsx
 * --------------------
 * Fixed vs patch4:
 *  - No longer depends on simMode flag for URL selection.
 *    Instead checks if filename starts with "sim_" — reliable
 *    regardless of WebSocket timing.
 *  - Added retry if fetch returns empty content (handles the
 *    rare first-tick race where gcode_str isn't built yet).
 *  - Proper cleanup on filename change.
 */

import React, { useState, useEffect, useRef } from "react";
import { Line } from "@react-three/drei";
import { useStore } from "./store";

const SIM_PREFIX = "sim_";

export function GCodeVisualizer() {
  const filename     = useStore((s) => s.telemetry.filename);
  const filePosition = useStore((s) => s.telemetry.file_position);

  const [allPaths,     setAllPaths]     = useState([]);
  const [visiblePaths, setVisiblePaths] = useState([]);
  const retryRef = useRef(null);

  // ── Fetch + parse whenever filename changes ───────────────────────────────
  useEffect(() => {
    if (!filename) {
      setAllPaths([]);
      useStore.setState({ gcodeLines: [] });
      return;
    }

    let cancelled = false;
    if (retryRef.current) clearTimeout(retryRef.current);

    const isSim = filename.startsWith(SIM_PREFIX);
    const HOST  = window.location.hostname;

    const url = isSim
      ? `http://${HOST}:5001/api/sim/gcode_file`
      : `http://${HOST}:7125/server/files/gcodes/${encodeURIComponent(filename)}`;

    const fetchAndParse = async (attempt = 0) => {
      if (cancelled) return;
      try {
        const res  = await fetch(url);
        const text = await res.text();

        if (!res.ok || !text.trim()) {
          // In sim mode the gcode might not be built yet on very first tick
          if (isSim && attempt < 5) {
            retryRef.current = setTimeout(() => fetchAndParse(attempt + 1), 400);
            return;
          }
          console.warn(`[GCodeVisualizer] empty response — ${url}`);
          return;
        }

        if (cancelled) return;

        const encoder     = new TextEncoder();
        const rawLines    = [];
        const parsedPaths = [];
        let currentPath   = [];
        let currentByte   = 0;
        let cx = 0, cy = 0, cz = 0, lastE = 0;

        const lines = text.split("\n");

        for (let idx = 0; idx < lines.length; idx++) {
          const rawLine        = lines[idx];
          const lineWithNL     = idx < lines.length - 1 ? rawLine + "\n" : rawLine;
          const lineByteLength = encoder.encode(lineWithNL).length;

          rawLines.push({ byte: currentByte, text: rawLine.trim() });

          const line = rawLine.trim();

          if (line.startsWith("G0") || line.startsWith("G1")) {
            const mx = line.match(/X([0-9.-]+)/);
            const my = line.match(/Y([0-9.-]+)/);
            const mz = line.match(/Z([0-9.-]+)/);
            const me = line.match(/E([0-9.-]+)/);

            if (mx) cx = parseFloat(mx[1]);
            if (my) cy = parseFloat(my[1]);
            if (mz) cz = parseFloat(mz[1]);

            let extruding = false;
            if (me) {
              const ce = parseFloat(me[1]);
              if (ce > lastE) extruding = true;
              lastE = ce;
            }

            // Scene scale: 1 unit = 10 mm
            const pt = [cx / 10, cz / 10, cy / 10];

            if (extruding) {
              currentPath.push({ byte: currentByte + lineByteLength, pt });
            } else {
              if (currentPath.length > 1) parsedPaths.push(currentPath);
              currentPath = [{ byte: currentByte + lineByteLength, pt }];
            }
          }

          currentByte += lineByteLength;
        }
        if (currentPath.length > 1) parsedPaths.push(currentPath);

        if (cancelled) return;

        setAllPaths(parsedPaths);
        useStore.setState({ gcodeLines: rawLines });

        console.log(
          `[GCodeVisualizer] ${isSim ? "SIM" : "LIVE"} — ` +
          `${rawLines.length} lines, ${parsedPaths.length} paths, ${currentByte} bytes`
        );
      } catch (e) {
        if (!cancelled) console.error("[GCodeVisualizer]", e);
      }
    };

    fetchAndParse();
    return () => {
      cancelled = true;
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [filename]);

  // ── Filter by file_position ───────────────────────────────────────────────
  useEffect(() => {
    if (!allPaths.length) { setVisiblePaths([]); return; }
    const filtered = allPaths
      .map(p  => p.filter(pt => pt.byte <= filePosition))
      .filter(p => p.length > 1);
    setVisiblePaths(filtered);
  }, [filePosition, allPaths]);

  if (!visiblePaths.length) return null;

  return (
    <group>
      {visiblePaths.map((path, i) => (
        <Line
          key={i}
          points={path.map(p => p.pt)}
          color="#f59e0b"
          lineWidth={2.5}
          transparent
          opacity={0.85}
        />
      ))}
    </group>
  );
}
