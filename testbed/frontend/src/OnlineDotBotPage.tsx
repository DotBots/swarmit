import { Dispatch, SetStateAction, useState } from "react";
import { API_URL, checkTokenActiveness, DotBotData, Token, TokenPayload } from "./App";

interface CalendarPageProps {
  dotbots: Record<string, DotBotData>;
  token: Token | null
}

export default function OnlineDotBotPage({ dotbots, token }: CalendarPageProps) {
  const [loading, setLoading] = useState(false);
  return (
    <div className="animate-fadeIn">
      <h2 className="text-2xl font-semibold mb-6 text-gray-800">Data Table</h2>
      <div className="overflow-x-auto bg-white rounded-2xl shadow">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="bg-[#1E91C7]/90 text-white">
              <th className="py-3 px-4 text-left font-semibold">Node Address</th>
              <th className="py-3 px-4 text-left font-semibold">Device</th>
              <th className="py-3 px-4 text-left font-semibold">Status</th>
              <th className="py-3 px-4 text-left font-semibold">Battery</th>
              <th className="py-3 px-4 text-left font-semibold">Pos (x, y)</th>
              {token && checkTokenActiveness(token.payload) === "Active" && (
                <>
                  <th className="py-3 px-4 text-left font-semibold">Start</th>
                  <th className="py-3 px-4 text-left font-semibold">Stop</th>
                </>
              )}

            </tr>
          </thead>
          <tbody>
            {dotbots && Object.entries(dotbots).map(([id, bot], i) => (
              <tr
                key={id}
                className={`hover:bg-[#1E91C7]/5 transition-colors ${i % 2 === 0 ? "bg-gray-50" : "bg-white"
                  }`}
              >
                <td className="py-3 px-4 border-t">{id}</td>
                <td className="py-3 px-4 border-t">{bot.device}</td>
                <td className="py-3 px-4 border-t">{bot.status}</td>
                <td className="py-3 px-4 border-t">{`${bot.battery}V`}</td>
                <td className="py-3 px-4 border-t">{`(${bot.pos_x}, ${bot.pos_y})`}</td>
                {token && checkTokenActiveness(token.payload) === "Active" && (
                  <>
                    <td className="py-3 px-4 border-t">
                      <StartSingleBotButton device_id={id} token={token} loading={loading} setLoading={setLoading} />
                    </td>
                    <td className="py-3 px-4 border-t">
                      <StopSingleBotButton device_id={id} token={token} loading={loading} setLoading={setLoading} />
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface StartStopButtonProps {
  device_id: string;
  token: Token;
  loading: boolean;
  setLoading: Dispatch<SetStateAction<boolean>>;
}


function StartSingleBotButton({ device_id, token, loading, setLoading }: StartStopButtonProps) {
  const handleStart = (devices: string[]) => {
    if (!token) {
      // setMessage("Please fill a token first");
      return;
    }
    setLoading(true);
    // setMessage("Starting...");

    fetch(`${API_URL}/start`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ devices }),
    })
      .then((res) => {
        if (res.ok) {
          // setMessage("Testbed started successfully");
        } else {
          return res.json()
            .then((data) => {
              // setMessage(`Error: ${data.detail || "Failed to start testbed"}`);
            })
            .catch(() => {
              // setMessage("Failed to start testbed");
            });
        }
      })
      .catch(() => {
        // setMessage(`Error: couldn't authorize token`);
      })
      .finally(() => {
        setLoading(false);
      });
  };


  return (
    <div>
      <button
        className="w-full py-2 px-4 bg-green-600 text-white rounded-lg
               hover:bg-green-700 transition disabled:cursor-not-allowed
               disabled:bg-green-900"
        onClick={() => handleStart([device_id])}
        disabled={loading}
      >
        Start
      </button>
    </div >
  );
}

function StopSingleBotButton({ device_id, token, loading, setLoading }: StartStopButtonProps) {
  const handleStop = (devices: string[]) => {
    if (!token) {
      return;
    }
    setLoading(true);
    // setMessage("Stopping...");

    fetch(`${API_URL}/stop`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ devices }),
    })
      .then((res) => {
        if (res.ok) {
          // setMessage("Testbed stopped successfully");
        } else {
          return res.json()
            .then((data) => {
              // setMessage(`Error: ${data.detail || "Failed to stop testbed"}`);
            })
            .catch(() => {
              // setMessage("Failed to stop testbed");
            });
        }
      })
      .catch(() => {
        // setMessage(`Error: couldn't authorize token`);
      })
      .finally(() => {
        setLoading(false);
      });
  };
  return (
    <div>
      <button
        className="w-full py-2 px-4 bg-red-600 text-white rounded-lg
               hover:bg-red-700 transition disabled:cursor-not-allowed
               disabled:bg-red-900"
        onClick={() => handleStop([device_id])}
        disabled={loading}
      >
        Start
      </button>
    </div >
  );
}

