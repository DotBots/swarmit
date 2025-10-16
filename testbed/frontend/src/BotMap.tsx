import React, { useEffect, useState } from "react";
import { ApplicationType, inactiveAddress } from "./constants";
import { DotBotData } from "./App";
// import logger from "./utils/logger";

// const log = logger.child({ module: "dotbot-map" });

interface Point {
  x: number;
  y: number;
}

// interface DotBot {
//   address: string;
//   status: number;
//   lh2_position: { x: string; y: string };
//   direction?: number;
//   rgb_led?: { red: number; green: number; blue: number };
//   waypoints: Point[];
//   waypoints_threshold: number;
//   position_history: Point[];
// }

interface DotBotsWaypointProps {
  index: number;
  point: Point;
  color: string;
  opacity: string;
  waypoints: Point[];
  threshold: number;
  mapSize: number;
}

const DotBotsWaypoint: React.FC<DotBotsWaypointProps> = ({
  index,
  point,
  color,
  opacity,
  waypoints,
  threshold,
  mapSize,
}) => {
  return (
    <>
      {index === 0 ? (
        <circle
          cx={point.x * mapSize}
          cy={point.y * mapSize}
          r={4}
          fill="none"
          stroke={color}
          strokeWidth={2}
          opacity={opacity}
        />
      ) : (
        <>
          <circle
            cx={point.x * mapSize}
            cy={point.y * mapSize}
            r={threshold * mapSize}
            fill={color}
            stroke="none"
            opacity="10%"
          />
          <line
            x1={waypoints[index - 1].x * mapSize}
            y1={waypoints[index - 1].y * mapSize}
            x2={point.x * mapSize}
            y2={point.y * mapSize}
            stroke={color}
            strokeWidth={2}
            strokeDasharray="2"
            opacity={opacity}
          />
          <rect
            x={point.x * mapSize - 2}
            y={point.y * mapSize - 2}
            width={4}
            height={4}
            fill={color}
            opacity={opacity}
          />
        </>
      )}
    </>
  );
};

interface DotBotsPositionProps {
  index: number;
  point: Point;
  color: string;
  opacity: string;
  history: Point[];
  mapSize: number;
}

const DotBotsPosition: React.FC<DotBotsPositionProps> = ({
  index,
  point,
  color,
  opacity,
  history,
  mapSize,
}) => {
  return (
    <>
      {index === 0 ? (
        <circle
          cx={point.x * mapSize}
          cy={point.y * mapSize}
          r={4}
          fill="none"
          stroke={color}
          strokeWidth={2}
          opacity={opacity}
        />
      ) : (
        <>
          <line
            x1={history[index - 1].x * mapSize}
            y1={history[index - 1].y * mapSize}
            x2={point.x * mapSize}
            y2={point.y * mapSize}
            stroke={color}
            strokeWidth={2}
            opacity={opacity}
          />
          <circle
            cx={point.x * mapSize}
            cy={point.y * mapSize}
            r={2}
            fill={color}
            opacity={opacity}
          />
        </>
      )}
    </>
  );
};

interface DotBotsMapPointProps {
  dotbot: DotBotData;
  // active: string;
  mapSize: number;
  // showHistory: boolean;
  // historySize: number;
  // updateActive: (addr: string) => void;
}

function DotBotsMapPoint({
  dotbot,
  // active,
  mapSize,
  // showHistory,
  // historySize,
  // updateActive
}: DotBotsMapPointProps) {
  const [hovered, setHovered] = useState(false);

  let rgbColor = "rgb(0, 0, 0)";
  // if (dotbot.rgb_led) {
  //   rgbColor = `rgb(${dotbot.rgb_led.red}, ${dotbot.rgb_led.green}, ${dotbot.rgb_led.blue})`;
  // }

  const posX = mapSize * dotbot.pos_x;
  const posY = mapSize * dotbot.pos_y;
  // const rotation = dotbot.direction ?? 0;
  // const isActive = dotbot.address === active || hovered;
  const isActive = true;
  const radius = isActive ? 8 : 5;
  const directionShift = isActive ? 2 : 1;
  const directionSize = isActive ? 8 : 5;
  const opacity = dotbot.status === "alive" ? "80%" : "20%";
  const waypointOpacity = dotbot.status === "alive" ? "50%" : "10%";

  const onMouseEnter = () => {
    if (dotbot.status !== "alive") return;
    setHovered(true);
  };

  const onMouseLeave = () => setHovered(false);

  return (
    <>
      {/* {dotbot.waypoints.length > 0 &&
        dotbot.waypoints.map((point, index) => (
          <DotBotsWaypoint
            key={`waypoint-${index}`}
            index={index}
            point={point}
            color={rgbColor}
            opacity={waypointOpacity}
            waypoints={dotbot.waypoints}
            threshold={dotbot.waypoints_threshold / 1000}
            mapSize={mapSize}
          />
        ))} */}

      {/* {showHistory && dotbot.position_history.length > 0 &&
        dotbot.position_history
          .slice(-historySize)
          .map((point, index) => (
            <DotBotsPosition
              key={`position-${index}`}
              index={index}
              point={point}
              color={rgbColor}
              opacity={opacity}
              history={dotbot.position_history.slice(-historySize)}
              mapSize={mapSize}
            />
          ))} */}

      <g
        // transform={`rotate(${rotation} ${posX} ${posY})`}
        stroke={"black"}
        // stroke={dotbot.address === active ? "black" : "none"}
        strokeWidth={1}
      >
        <circle
          cx={posX}
          cy={posY}
          r={radius}
          opacity={opacity}
          fill={rgbColor}
          className="cursor-pointer"
          // onClick={() =>
          //   updateActive(dotbot.address === active ? inactiveAddress : dotbot.address)
          // }
          onMouseEnter={onMouseEnter}
          onMouseLeave={onMouseLeave}
        >
          <title>{`${dotbot.device}@${posX}x${posY}`}</title>
        </circle>
        {/* {dotbot.direction && (
          <polygon
            points={`${posX - radius + 2},${posY + radius + directionShift} ${posX + radius - 2},${posY + radius + directionShift} ${posX},${posY + radius + directionSize + directionShift}`}
            fill={rgbColor}
            opacity={opacity}
          />
        )} */}
      </g>
    </>
  );
};

interface DotBotsMapProps {
  dotbots: Record<string, DotBotData>;
  // mapSize: number;
  // active: string;
  // calibrationState: string;
  // showHistory: boolean;
  // historySize: number;
  // publish: (topic: string, payload: any) => Promise<void>;
  // updateCalibrationState: (state: string) => void;
  // updateShowHistory: (checked: boolean, appType: ApplicationType) => void;
  // setHistorySize: (size: number) => void;
  // mapClicked: (x: number, y: number) => void;
  // updateActive: (addr: string) => void;
}

export const DotBotsMap: React.FC<DotBotsMapProps> = ({ dotbots }: DotBotsMapProps) => {
  const [displayGrid, setDisplayGrid] = useState(true);
  const [pointsChecked, setPointsChecked] = useState<boolean[]>([false, false, false, false]);

  const addCalibrationPointTopic = "lh2/add";
  const startCalibrationTopic = "lh2/start";

  // const pointClicked = async (index: number) => {
  //   const tmp = [...pointsChecked];
  //   tmp[index] = true;
  //   setPointsChecked(tmp);
  //   await props.publish(addCalibrationPointTopic, { index });
  // };

  // const calibrateClicked = async () => {
  //   // log.info(`Calibrate clicked ${props.calibrationState}`);
  //   if (["unknown", "done"].includes(props.calibrationState)) {
  //     setPointsChecked([false, false, false, false]);
  //     props.updateCalibrationState("running");
  //   } else if (props.calibrationState === "ready") {
  //     props.updateCalibrationState("done");
  //     await props.publish(startCalibrationTopic, "");
  //   }
  // };

  // const mapClicked = (event: React.MouseEvent<SVGRectElement>) => {
  //   const dim = event.currentTarget.getBoundingClientRect();
  //   const x = event.clientX - dim.left;
  //   const y = event.clientY - dim.top;
  //   props.mapClicked(x / props.mapSize, y / props.mapSize);
  // };

  // const coordinateToPixel = (coordinate: number) => {
  //   return props.mapSize * (coordinate + 0.5) - 5;
  // };

  const updateDisplayGrid = (event: React.ChangeEvent<HTMLInputElement>) => {
    setDisplayGrid(event.target.checked);
  };

  // useEffect(() => {
  //   if (pointsChecked.every((v) => v)) {
  //     props.updateCalibrationState("ready");
  //   } else if (
  //     ["unknown", "done"].includes(props.calibrationState) &&
  //     pointsChecked.every((v) => v)
  //   ) {
  //     setPointsChecked([false, false, false, false]);
  //   }
  // }, [pointsChecked, props]);

  let calibrationButtonLabel: React.ReactNode = "Start calibration";
  let calibrationButtonClass = "bg-blue-600 hover:bg-blue-700 text-white";

  // if (props.calibrationState === "running") {
  //   calibrationButtonLabel = (
  //     <>
  //       <span className="animate-spin mr-2">⚙️</span> Calibration in progress...
  //     </>
  //   );
  //   calibrationButtonClass = "bg-gray-400 cursor-not-allowed";
  // } else if (props.calibrationState === "ready") {
  //   calibrationButtonLabel = "Apply calibration";
  //   calibrationButtonClass = "bg-green-600 hover:bg-green-700 text-white";
  // } else if (props.calibrationState === "done") {
  //   calibrationButtonLabel = "Update calibration";
  // }

  const mapSize = 700;
  const gridSize = `${mapSize + 1}px`;
  const calibrationTextWidth = `${mapSize}px`;

  const referencePoints: Point[] = [
    { x: -0.1, y: 0.1 },
    { x: 0.1, y: 0.1 },
    { x: -0.1, y: -0.1 },
    { x: 0.1, y: -0.1 },
  ];

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
              fill={displayGrid ? `url(#grid${mapSize})` : "none"}
              stroke="gray"
              strokeWidth={1}
            // onClick={mapClicked}
            />

            {Object.entries(dotbots)
              .filter(([_address, dotbot]) => dotbot.status !== "dead")
              .map(([address, dotbot]) => (
                <DotBotsMapPoint key={address} dotbot={dotbot} mapSize={mapSize} />
              ))}

            {/* {["running", "ready"].includes(props.calibrationState) &&
              referencePoints.map((point, index) => (
                <rect
                  key={index}
                  x={coordinateToPixel(point.x)}
                  y={coordinateToPixel(point.y * -1)}
                  width={10}
                  height={10}
                  fill={pointsChecked[index] ? "green" : "grey"}
                  className="cursor-pointer"
                  onClick={() => pointClicked(index)}
                >
                  <title>{index + 1}</title>
                </rect>
              ))} */}
          </svg>
        </div>
      </div>

      {/* <div className="border rounded-lg shadow-md m-2">
        <div className="bg-gray-100 px-3 py-2 font-semibold border-b">Map settings</div>
        <div className="p-3 space-y-3">
          <div>
            <label className="flex items-center space-x-2">
              <input type="checkbox" checked={displayGrid} onChange={updateDisplayGrid} />
              <span>Display grid</span>
            </label>
          </div>
          <div>
            <label className="flex items-center space-x-2">
              <input
                type="checkbox"
                checked={props.showHistory}
                onChange={(e) => props.updateShowHistory(e.target.checked, ApplicationType.DotBot)}
              />
              <span>Display position history</span>
            </label>
          </div>
          <div>
            <label htmlFor="dotbotHistorySize" className="mr-2">
              Position history size:
            </label>
            <input
              type="number"
              id="dotbotHistorySize"
              min={10}
              max={1000}
              value={props.historySize}
              onChange={(e) => props.setHistorySize(Number(e.target.value))}
              className="border rounded px-2 py-1 w-24"
            />
          </div>
          <button
            className={`px-3 py-1 rounded text-sm ${calibrationButtonClass}`}
            onClick={calibrateClicked}
          >
            {calibrationButtonLabel}
          </button>
          {props.calibrationState === "running" && (
            <p style={{ width: calibrationTextWidth }}>
              Place a DotBot on the marks on the ground and once done, click the corresponding
              rectangle on the grid. Repeat the operation for each mark. Once all rectangles are
              green, click "Apply calibration".
            </p>
          )}
        </div>
      </div> */}
    </div>
  );
};
