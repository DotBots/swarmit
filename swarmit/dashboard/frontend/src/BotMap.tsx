import React, { useState } from "react";
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
}

export const DotBotsMap: React.FC<DotBotsMapProps> = ({ dotbots, areaSize }: DotBotsMapProps) => {
  const mapSize = 1000;
  const gridWidth = `${mapSize + 1}px`;
  const gridHeight = `${mapSize * areaSize.height / areaSize.width + 1}px`;

  return (
    <div className={`${Object.keys(dotbots).length > 0 ? "visible" : "invisible"}`}>
      <div className="flex justify-center">
        <div style={{ height: gridHeight, width: gridWidth }}>
          <svg style={{ height: gridHeight, width: gridWidth }}>
            <defs>
              <pattern id={`grid${mapSize}`} width={`${500 * mapSize / areaSize!.width}`} height={`${500 * mapSize / areaSize!.width}`} patternUnits="userSpaceOnUse">
                <rect width={`${500 * mapSize / areaSize.width}`} height={`${500 * mapSize / areaSize!.width}`} fill={`url(#smallGrid${mapSize})`}/>
                <path d={`M ${500 * mapSize / areaSize!.width} 0 L 0 0 0 ${500 * mapSize / areaSize!.width}`} fill="none" stroke="gray" strokeWidth="1"/>
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
                <DotBotsMapPoint key={address} dotbot={dotbot} address={address} mapSize={mapSize} areaSize={areaSize} />
              ))}
          </svg>
        </div>
      </div>
    </div>
  );
};
