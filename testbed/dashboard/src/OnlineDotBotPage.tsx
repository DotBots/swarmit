import { Dispatch, SetStateAction, useState } from "react";
import { API_URL, checkTokenActiveness, DotBotData, Token, TokenPayload } from "./App";

interface CalendarPageProps {
  dotbots: Record<string, DotBotData>;
  token: Token | null
}

export default function OnlineDotBotPage({ dotbots, token }: CalendarPageProps) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);

  const toggleSelection = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const allSelected =
    Object.keys(dotbots).length > 0 &&
    selected.length === Object.keys(dotbots).length;

  const toggleAll = () => {
    if (allSelected) setSelected([]);
    else setSelected(Object.keys(dotbots));
  };

  const isActive = token && checkTokenActiveness(token.payload) === "Active";

  const handleStart = () => {
    if (!token) {
      return;
    }
    setLoading(true);
    fetch(`${API_URL}/start`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ devices: selected }),
    })
      .finally(() => {
        setLoading(false);
      });
  };

  const handleStop = () => {
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
      body: JSON.stringify({ devices: selected }),
    })
      .finally(() => {
        setLoading(false);
      });
  };

  const handleFlash = () => {
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
        body: JSON.stringify({ firmware_b64: base64, devices: selected }),
      })
        .finally(() => {
          setLoading(false);
        });
    };

    reader.readAsDataURL(file);
  };

  return (
    <div className="animate-fadeIn">
      <h2 className="text-2xl font-semibold mb-6 text-gray-800">DotBots Info</h2>
      {Object.keys(dotbots).length === 0 ?
        <div className="bg-white rounded-2xl shadow p-8 text-center text-gray-500">
          No devices available
        </div> :
        <div><div className="overflow-x-auto bg-white rounded-2xl shadow"><table className="min-w-full border-collapse">
          <thead>
            <tr className="bg-[#1E91C7]/90 text-white">
              <th className="py-3 px-4 text-left font-semibold">Node Address</th>
              <th className="py-3 px-4 text-left font-semibold">Device</th>
              <th className="py-3 px-4 text-left font-semibold">Status</th>
              <th className="py-3 px-4 text-left font-semibold">Battery</th>
              <th className="py-3 px-4 text-left font-semibold">Pos (x, y)</th>
              {isActive && (
                <>
                  <th className="py-3 px-4 text-left font-semibold" onClick={toggleAll}>Action</th>
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
                {isActive && (
                  <>
                    <td className="py-3 px-4 border-t">
                      <input
                        type="checkbox"
                        checked={selected.includes(id)}
                        onChange={() => toggleSelection(id)}
                        className="h-4 w-4 text-[#1E91C7] focus:ring-[#1E91C7] border-gray-300 rounded cursor-pointer"
                      />
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
          {isActive &&
            (<ActionButtons
              handleStart={handleStart}
              handleStop={handleStop}
              handleFlash={handleFlash}
              loading={loading}
              hasFile={file !== null}
              selected={selected}
              setFile={setFile}
            />)}
        </div >}
    </div >
  );
}

interface ActionButtonsProps {
  handleStart: () => void;
  handleStop: () => void;
  handleFlash: () => void;
  loading: boolean;
  hasFile: boolean;
  selected: string[];
  setFile: Dispatch<SetStateAction<File | null>>;
}

function ActionButtons({ handleStart, handleStop, handleFlash, loading, hasFile, selected, setFile }: ActionButtonsProps) {

  return (
    <div className="w-fit bg-white rounded-2xl shadow p-6 mt-6 flex items-center justify-center gap-4">
      <div>
        <button
          className="w-min py-2 px-4 bg-green-600 text-white rounded-lg
               hover:bg-green-700 transition disabled:cursor-not-allowed
               disabled:bg-green-900"
          onClick={() => handleStart()}
          disabled={loading || selected.length === 0}
        >
          Start
        </button>
      </div >
      <div>
        <button
          className="w-min py-2 px-4 bg-red-600 text-white rounded-lg
               hover:bg-red-700 transition disabled:cursor-not-allowed
               disabled:bg-red-900"
          onClick={() => handleStop()}
          disabled={loading || selected.length === 0}
        >
          Stop
        </button>
      </div >
      <div>
        <button
          className="w-min py-2 px-4 bg-[#1E91C7] text-white rounded-lg
               hover:bg-[#187AA3] transition disabled:cursor-not-allowed
               disabled:bg-[#135C7B]"
          onClick={() => handleFlash()}
          disabled={loading || !hasFile || selected.length === 0}
        >
          Flash
        </button>
      </div >
      <input
        type="file"
        accept=".bin"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        className="block w-full text-sm text-gray-600"
      />



      <div
        role="status"
        className={`flex items-center justify-center ${loading ? "visible opacity-100 animate-spin" : "invisible opacity-0"
          }`}>
        <svg aria-hidden="true" className="w-8 h-8 text-gray-200 animate-spin dark:text-gray-600 fill-blue-600" viewBox="0 0 100 101" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M100 50.5908C100 78.2051 77.6142 100.591 50 100.591C22.3858 100.591 0 78.2051 0 50.5908C0 22.9766 22.3858 0.59082 50 0.59082C77.6142 0.59082 100 22.9766 100 50.5908ZM9.08144 50.5908C9.08144 73.1895 27.4013 91.5094 50 91.5094C72.5987 91.5094 90.9186 73.1895 90.9186 50.5908C90.9186 27.9921 72.5987 9.67226 50 9.67226C27.4013 9.67226 9.08144 27.9921 9.08144 50.5908Z" fill="currentColor" />
          <path d="M93.9676 39.0409C96.393 38.4038 97.8624 35.9116 97.0079 33.5539C95.2932 28.8227 92.871 24.3692 89.8167 20.348C85.8452 15.1192 80.8826 10.7238 75.2124 7.41289C69.5422 4.10194 63.2754 1.94025 56.7698 1.05124C51.7666 0.367541 46.6976 0.446843 41.7345 1.27873C39.2613 1.69328 37.813 4.19778 38.4501 6.62326C39.0873 9.04874 41.5694 10.4717 44.0505 10.1071C47.8511 9.54855 51.7191 9.52689 55.5402 10.0491C60.8642 10.7766 65.9928 12.5457 70.6331 15.2552C75.2735 17.9648 79.3347 21.5619 82.5849 25.841C84.9175 28.9121 86.7997 32.2913 88.1811 35.8758C89.083 38.2158 91.5421 39.6781 93.9676 39.0409Z" fill="currentFill" />
        </svg>
        <span className="sr-only">Loading...</span>
      </div>
    </div>
  );
}
