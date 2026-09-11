import React, { useEffect, useState } from "react";
import { Bounds, DotBotData, StatusType } from "./App";

interface DotBotsMapPointProps {
  dotbot: DotBotData;
  address: string;
  mapSize: number;
  bounds: Bounds;
}

function DotBotsMapPoint({
  dotbot,
  address,
  mapSize,
  bounds,
}: DotBotsMapPointProps) {
  // Positions arrive in frame coordinates, so the bounds origin comes off
  // before scaling into the drawn box.
  const posX = (mapSize * (dotbot.pos_x - bounds.x)) / bounds.w;
  const posY = (mapSize * (dotbot.pos_y - bounds.y)) / bounds.w;

  const getStatusColor = (status: StatusType) => {
    switch (status) {
      case "Bootloader":
        return "rgb(30, 145, 199)";
      case "Running":
        return "rgb(34, 197, 94)";
      case "Programming":
        return "rgb(249, 115, 22)";
      case "Stopping":
        return "rgb(239, 68, 68)";
      case "Resetting":
        return "rgb(168, 85, 247)";
      default:
        return "rgb(107, 114, 128)";
    }
  };

  return (
    <>
      <g
        stroke={"black"}
        strokeWidth={0.5}
      >
        <circle
          cx={posX}
          cy={posY}
          r={5}
          opacity="100%"
          fill={getStatusColor(dotbot.status)}
          className="cursor-pointer"
        >
          <title>{`Address: ${address}
Device: ${dotbot.device}
Status: ${dotbot.status}
Battery: ${dotbot.battery}
Position: ${posX}x${posY}`}</title>
        </circle>
      </g>
    </>
  );
};

interface DotBotsMapProps {
  dotbots: Record<string, DotBotData>;
  bounds: Bounds;
  // Frame coordinates of the calibration's placement points, as [x, y]
  // pairs. Empty means no calibration has been sent through this controller,
  // so there is nothing to mark.
  referencePoints: number[][];
}

export const DotBotsMap: React.FC<DotBotsMapProps> = ({ dotbots, bounds, referencePoints }: DotBotsMapProps) => {
  // Auto-scale the SVG so a tall arena (e.g. 1000x1800 from two stacked
  // LHs) still fits between the header and the controls card. Recompute on
  // window resize so the map stays sized after the user adjusts the window.
  const [viewportH, setViewportH] = useState<number>(
    typeof window !== "undefined" ? window.innerHeight : 800,
  );
  useEffect(() => {
    const onResize = () => setViewportH(window.innerHeight);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const aspect = bounds.h / bounds.w;
  const maxW = 700;
  // Reserve room for the header (~64), main padding (64), and the controls
  // card below the map (~360). Floor keeps the map usable on short windows.
  const maxH = Math.max(280, viewportH - 320);
  const mapSize = aspect * maxW > maxH ? Math.floor(maxH / aspect) : maxW;
  const gridWidth = `${mapSize + 1}px`;
  const gridHeight = `${mapSize * aspect + 1}px`;
  const isEmpty = Object.keys(dotbots).length === 0;

  // Graph-paper grid in frame millimetres: minor lines every 100 mm in
  // light gray, major every 500 mm in mid gray, so each major square has
  // 5x5 minor cells. The major pattern fills its background with the minor
  // pattern, so a single fill on the canvas-rect draws both layers.
  const pxMinor = (100 * mapSize) / bounds.w;
  const pxMajor = (500 * mapSize) / bounds.w;

  return (
    <div className="flex justify-center">
      <div className="relative bg-white rounded-2xl shadow p-4">
        <div style={{ height: gridHeight, width: gridWidth }}>
          <svg style={{ height: gridHeight, width: gridWidth }}>
            <defs>
              <pattern
                id={`minorGrid${mapSize}`}
                width={pxMinor}
                height={pxMinor}
                patternUnits="userSpaceOnUse"
              >
                <path
                  d={`M ${pxMinor} 0 L 0 0 0 ${pxMinor}`}
                  fill="none"
                  stroke="#bec0c4"
                  strokeWidth="1"
                />
              </pattern>
              <pattern
                id={`majorGrid${mapSize}`}
                width={pxMajor}
                height={pxMajor}
                patternUnits="userSpaceOnUse"
              >
                <rect
                  width={pxMajor}
                  height={pxMajor}
                  fill={`url(#minorGrid${mapSize})`}
                />
                <path
                  d={`M ${pxMajor} 0 L 0 0 0 ${pxMajor}`}
                  fill="none"
                  stroke="#787d86"
                  strokeWidth="1.5"
                />
              </pattern>
            </defs>

            <rect
              width="100%"
              height="100%"
              fill={`url(#majorGrid${mapSize})`}
              stroke="#9ca3af"
              strokeWidth={1.5}
            />

            {/* One cross per calibration point, at the frame coordinates the
                placements recorded. Where the points went is what sets the
                accuracy, so the marks come from the calibration and never
                from the drawn rectangle. */}
            {referencePoints.map(([px, py]) => {
                const x = ((px - bounds.x) * mapSize) / bounds.w;
                const y = ((py - bounds.y) * mapSize) / bounds.w;
                return (
                  <g key={`${px}-${py}`} pointerEvents="none">
                    <line x1={x - 5} y1={y} x2={x + 5} y2={y} stroke="#6b7280" strokeWidth={1.5} />
                    <line x1={x} y1={y - 5} x2={x} y2={y + 5} stroke="#6b7280" strokeWidth={1.5} />
                  </g>
                );
              })}

            {Object.entries(dotbots)
              .map(([address, dotbot]) => (
                <DotBotsMapPoint key={address} dotbot={dotbot} address={address} mapSize={mapSize} bounds={bounds} />
              ))}
          </svg>
        </div>
        {isEmpty && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <span className="bg-white/80 backdrop-blur-sm rounded-lg px-4 py-2 text-sm text-gray-500 shadow-sm">
              No devices detected yet
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
