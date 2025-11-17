import React, { useState } from "react";
import { DotBotData, StatusType } from "./App";

interface DotBotsMapPointProps {
  dotbot: DotBotData;
  address: string;
  mapSize: number;
}

function DotBotsMapPoint({
  dotbot,
  address,
  mapSize,
}: DotBotsMapPointProps) {
  const posX = mapSize * dotbot.pos_x;
  const posY = mapSize * dotbot.pos_y;

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
}

export const DotBotsMap: React.FC<DotBotsMapProps> = ({ dotbots }: DotBotsMapProps) => {
  const mapSize = 700;
  const gridSize = `${mapSize + 1}px`;

  return (
    <div className={`${Object.keys(dotbots).length > 0 ? "visible" : "invisible"}`}>
      <div className="flex justify-center">
        <div style={{ height: gridSize, width: gridSize }}>
          <svg style={{ height: gridSize, width: gridSize }}>
            <defs>
              <pattern id={`smallGrid${mapSize}`} width={mapSize / 50} height={mapSize / 50} patternUnits="userSpaceOnUse">
                <path d={`M ${mapSize / 50} 0 L 0 0 0 ${mapSize / 50}`} fill="none" stroke="gray" strokeWidth={0.5} />
              </pattern>
              <pattern id={`grid${mapSize}`} width={mapSize / 5} height={mapSize / 5} patternUnits="userSpaceOnUse">
                <rect width={mapSize / 5} height={mapSize / 5} fill={`url(#smallGrid${mapSize})`} />
                <path d={`M ${mapSize / 5} 0 L 0 0 0 ${mapSize / 5}`} fill="none" stroke="gray" strokeWidth={1} />
              </pattern>
            </defs>

            <rect
              width="100%"
              height="100%"
              fill={`url(#grid${mapSize})`}
              stroke="gray"
              strokeWidth={1}
            />

            {Object.entries(dotbots)
              .map(([address, dotbot]) => (
                <DotBotsMapPoint key={address} dotbot={dotbot} address={address} mapSize={mapSize} />
              ))}
          </svg>
        </div>
      </div>
    </div>
  );
};
