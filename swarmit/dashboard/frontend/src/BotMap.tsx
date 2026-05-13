import React, { useEffect, useState } from "react";
import { DotBotData, StatusType } from "./App";

interface DotBotsMapPointProps {
  dotbot: DotBotData;
  address: string;
  mapSize: number;
  areaSize: {
    width: number;
    height: number;
  };
}

function DotBotsMapPoint({
  dotbot,
  address,
  mapSize,
  areaSize,
}: DotBotsMapPointProps) {
  const posX = mapSize * dotbot.pos_x / areaSize!.width;
  const posY = mapSize * dotbot.pos_y / areaSize!.width;

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
  areaSize: {
    width: number;
    height: number;
  };
  // LH2 calibration distance in mm (the -d value passed to dotbot-calibration).
  // Used to place the 4 reference points at (2d..3d, 2d..3d) in arena coords.
  // 0 means "unknown" → don't render the reference points.
  calibrationDistance: number;
}

export const DotBotsMap: React.FC<DotBotsMapProps> = ({ dotbots, areaSize, calibrationDistance }: DotBotsMapProps) => {
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

  const aspect = areaSize.height / areaSize.width;
  const maxW = 700;
  // Reserve room for the header (~64), main padding (64), and the controls
  // card below the map (~360). Floor keeps the map usable on short windows.
  const maxH = Math.max(280, viewportH - 320);
  const mapSize = aspect * maxW > maxH ? Math.floor(maxH / aspect) : maxW;
  const gridWidth = `${mapSize + 1}px`;
  const gridHeight = `${mapSize * aspect + 1}px`;
  const isEmpty = Object.keys(dotbots).length === 0;

  // Graph-paper grid: minor lines every d (one calibration step) in light
  // gray, major lines every 5d (one LH2 coverage square) in mid gray. So
  // each major square has 5x5 minor cells. The major pattern fills its
  // background with the minor pattern, so a single fill on the canvas-rect
  // draws both layers.
  const minorMm = calibrationDistance > 0 ? calibrationDistance : 100;
  const majorMm = calibrationDistance > 0 ? 5 * calibrationDistance : 500;
  const pxMinor = (minorMm * mapSize) / areaSize.width;
  const pxMajor = (majorMm * mapSize) / areaSize.width;

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

            {/* LH2 calibration reference points: + marks at (2d, 2d),
                (3d, 2d), (2d, 3d), (3d, 3d) in arena (mm) coordinates.
                These positions are fixed by REFERENCE_POINTS_DEFAULT in
                dotbot_lh2_calibration/lighthouse2.py and are independent of
                LH count — even in multi-LH setups every LH is calibrated
                against the same 4 physical points within LH0's coverage. */}
            {calibrationDistance > 0 &&
              [
                [2, 2], [3, 2], [2, 3], [3, 3],
              ].map(([fx, fy]) => {
                const x = (fx * calibrationDistance * mapSize) / areaSize.width;
                const y = (fy * calibrationDistance * mapSize) / areaSize.width;
                return (
                  <g key={`${fx}-${fy}`} pointerEvents="none">
                    <line x1={x - 5} y1={y} x2={x + 5} y2={y} stroke="#6b7280" strokeWidth={1.5} />
                    <line x1={x} y1={y - 5} x2={x} y2={y + 5} stroke="#6b7280" strokeWidth={1.5} />
                  </g>
                );
              })}

            {Object.entries(dotbots)
              .map(([address, dotbot]) => (
                <DotBotsMapPoint key={address} dotbot={dotbot} address={address} mapSize={mapSize} areaSize={areaSize} />
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
