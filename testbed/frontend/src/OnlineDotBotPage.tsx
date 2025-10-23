import { Dispatch, SetStateAction, useState } from "react";
import { API_URL, checkTokenActiveness, DotBotData, Token, TokenPayload } from "./App";

interface CalendarPageProps {
  dotbots: Record<string, DotBotData>;
  token: Token | null
}

export default function OnlineDotBotPage({ dotbots, token }: CalendarPageProps) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  return (
    <div className="animate-fadeIn">
      <h2 className="text-2xl font-semibold mb-6 text-gray-800">Data Table</h2>
      {token && checkTokenActiveness(token.payload) === "Active" && (<input
        type="file"
        accept=".bin"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        className="block w-full text-sm text-gray-600"
      />)}
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
                  <th className="py-3 px-4 text-left font-semibold w-1"></th>
                  <th className="py-3 px-4 text-left font-semibold w-1"></th>
                  <th className="py-3 px-4 text-left font-semibold w-1"></th>
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
                    <td className="py-3 px-4 border-t">
                      <FlashSingleBotButton device_id={id} token={token} loading={loading} setLoading={setLoading} file={file} />
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

interface FlashButtonProps extends StartStopButtonProps {
  file: File | null
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
      .finally(() => {
        setLoading(false);
      });
  };


  return (
    <div>
      <button
        className="w-min py-2 px-4 bg-green-600 text-white rounded-lg
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

    fetch(`${API_URL}/stop`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ devices }),
    })
      .finally(() => {
        setLoading(false);
      });
  };
  return (
    <div>
      <button
        className="w-min py-2 px-4 bg-red-600 text-white rounded-lg
               hover:bg-red-700 transition disabled:cursor-not-allowed
               disabled:bg-red-900"
        onClick={() => handleStop([device_id])}
        disabled={loading}
      >
        Stop
      </button>
    </div >
  );
}

function FlashSingleBotButton({ device_id, token, loading, setLoading, file }: FlashButtonProps) {
  const handleFlash = (file: File | null, devices: string[]) => {
    if (!token) {
      return;
    };
    if (!file) {
      return;
    }

    setLoading(true);

    const reader = new FileReader();

    reader.onload = () => {
      const base64 = (reader.result as string).split(",")[1];

      fetch(`${API_URL}/flash`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token.token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ firmware_b64: base64, devices }),
      })
        .finally(() => {
          setLoading(false);
        });
    };

    reader.readAsDataURL(file);
  };
  return (
    <div>
      <button
        className="w-min py-2 px-4 bg-[#1E91C7] text-white rounded-lg
               hover:bg-[#187AA3] transition disabled:cursor-not-allowed
               disabled:bg-[#135C7B]"
        onClick={() => handleFlash(file, [device_id])}
        disabled={loading || !file}
      >
        Flash
      </button>
    </div >
  );
}
