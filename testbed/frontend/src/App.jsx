import { useState, useCallback, useEffect } from "react";
import OnlineRobotPage from "./OnlineRobotPage";
import BlankPage from "./BlankPage";
import { useQrKey } from "./qrkey";
import { useSearchParams } from 'react-router-dom';

export default function InriaDashboard() {
  const [page, setPage] = useState(1);
  const [message, setMessage] = useState(null);
  const [dotbots, setDotbots] = useState([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const [ready, clientId, mqttData, setMqttData, publish, publishCommand, sendRequest] = useQrKey({
    // rootTopic: process.env.REACT_APP_ROOT_TOPIC, TODO
    rootTopic: "/pydotbot",
    setQrKeyMessage: setMessage,
    searchParams: searchParams,
    setSearchParams: setSearchParams,
  });

  const handleMessage = useCallback(() => {
    console.log(`Handle received message: ${JSON.stringify(message)}`)
    log.info(`Handle received message: ${JSON.stringify(message)}`);
    let payload = message.payload;
    if (message.topic === `/reply/${clientId}`) {
      // Received the list of dotbots
      if (payload.request === RequestType.DotBots) {
        setDotbots(payload.data);
      } else if (payload.request === RequestType.LH2CalibrationState) {
        setCalibrationState(payload.data.state);
      }
    } else if (message.topic === `/notify`) {
      // Process notifications
      if (payload.cmd === NotificationType.Update && dotbots && dotbots.length > 0) {
        let dotbotsTmp = dotbots.slice();
        for (let idx = 0; idx < dotbots.length; idx++) {
          if (dotbots[idx].address === payload.data.address) {
            if (payload.data.direction !== undefined && payload.data.direction !== null) {
              dotbotsTmp[idx].direction = payload.data.direction;
            }
            if (payload.data.lh2_position !== undefined && payload.data.lh2_position !== null) {
              const newPosition = {
                x: payload.data.lh2_position.x,
                y: payload.data.lh2_position.y
              };
              if (dotbotsTmp[idx].lh2_position && (dotbotsTmp[idx].position_history.length === 0 || lh2_distance(dotbotsTmp[idx].lh2_position, newPosition) > lh2_distance_threshold)) {
                dotbotsTmp[idx].position_history.push(newPosition);
              }
              dotbotsTmp[idx].lh2_position = newPosition;
            }
            if (payload.data.gps_position !== undefined && payload.data.gps_position !== null) {
              const newPosition = {
                latitude: payload.data.gps_position.latitude,
                longitude: payload.data.gps_position.longitude
              };
              if (dotbotsTmp[idx].gps_position !== undefined && dotbotsTmp[idx].gps_position !== null && (dotbotsTmp[idx].position_history.length === 0 || gps_distance(dotbotsTmp[idx].gps_position, newPosition) > gps_distance_threshold)) {
                dotbotsTmp[idx].position_history.push(newPosition);
              }
              dotbotsTmp[idx].gps_position = newPosition;
            }
            setDotbots(dotbotsTmp);
          }
        }
      } else if (payload.cmd === NotificationType.Reload) {
        log.info("Reload notification");
        sendRequest({ request: RequestType.DotBots, reply: `${clientId}` });
      }
    }
    setMessage(null);
  }, [clientId, dotbots, setDotbots, sendRequest, message, setMessage]
  );

  console.log(`dotbots: ${JSON.stringify(dotbots)}`);

  useEffect(() => {
    // Process incoming messages if any
    if (!message) {
      return;
    }
    handleMessage(message.topic, message.payload);
  }, [message, handleMessage]
  );

  console.log("mqttData");
  console.log(mqttData);

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-[#C9191E]/10 to-white">
      {/* Header */}
      <header className="bg-[#C9191E] text-white py-4 px-8 shadow-md flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-wide">Inria Dashboard</h1>
        <div className="text-sm opacity-80">inria.fr</div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-56 bg-white/70 backdrop-blur-md border-r border-gray-200 shadow-sm flex flex-col p-4 space-y-3">
          {["Home", "Research", "Projects", "Data Table"].map((label, i) => (
            <button
              key={label}
              onClick={() => setPage(i + 1)}
              className={`text-left px-4 py-2 rounded-xl font-medium transition-all ${page === i + 1
                ? "bg-[#C9191E] text-white shadow"
                : "text-gray-700 hover:bg-[#C9191E]/10"
                }`}
            >
              {label}
            </button>
          ))}
        </aside>

        {/* Main Content */}
        <main className="flex-1 p-8">
          {page === 1 && (
            < BlankPage />
          )}

          {page === 2 && (
            < BlankPage />
          )}

          {page === 3 && (
            < BlankPage />
          )}

          {page === 4 && (
            <OnlineRobotPage />
          )}
        </main>
      </div>
    </div>
  );
}
