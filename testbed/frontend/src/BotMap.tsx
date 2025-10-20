import React, { useState } from "react";
import { DotBotData } from "./App";

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

  // const posX = mapSize * 0.5;
  // const posY = mapSize * 0.5;

  return (
    <>
      <g
        stroke={"black"}
        strokeWidth={1}
      >
        <circle
          cx={posX}
          cy={posY}
          r={5}
          opacity="100%"
          fill="rgb(0, 0, 0)"
          className="cursor-pointer"
        >
          <title>{`${address}@${posX}x${posY}`}</title>
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
              .filter(([_address, dotbot]) => dotbot.status !== "dead")
              .map(([address, dotbot]) => (
                <DotBotsMapPoint key={address} dotbot={dotbot} address={address} mapSize={mapSize} />
              ))}
          </svg>
        </div>
      </div>
    </div>
  );
};
