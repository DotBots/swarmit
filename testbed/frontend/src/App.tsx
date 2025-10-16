import { useEffect, useState } from "react";
import OnlineDotBotPage from "./OnlineDotBotPage";
import CalendarPage from "./CalendarPage";
import HomePage from "./HomePage";
import LoginModal from "./Login";


export interface Token {
  token: string;
  payload: TokenPayload
}

export interface TokenPayload {
  iat: number; // issued at
  nbf: number; // not before
  exp: number; // expiration
}

export type DotBotData = {
  device: string;
  status: string;
  battery: number;
  pos_x: number;
  pos_y: number;
};

// Note: Storing a token in localStorage is not the most secure approach,
// as it can be exposed to XSS attacks. We accept this trade-off here because
// losing the JWT is low impact — generating a new one is cheap and does not
// compromise sensitive data.
export function usePersistedToken() {
  const [token, setToken] = useState<Token | null>(() => {
    const stored = localStorage.getItem("token");
    return stored ? JSON.parse(stored) : null;
  });

  useEffect(() => {
    if (token) {
      localStorage.setItem("token", JSON.stringify(token));
    } else {
      localStorage.removeItem("token");
    }
  }, [token]);

  return { token, setToken };
}

export default function InriaDashboard() {
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const [dotbots, setDotBots] = useState<Record<string, DotBotData>>({});
  const { token, setToken } = usePersistedToken();

  useEffect(() => {
    const fetchStatus = () => {
      fetch("http://localhost:8883/status")
        .then((res) => {
          if (!res.ok) throw new Error("network response was not ok");
          return res.json();
        })
        .then((json) => {
          setDotBots(json.response);
        })
        .catch((_err) => {
        });
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-[#1E91C7]/10 to-white">
      <header className="bg-[#1E91C7] text-white py-4 px-8 shadow-md flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-wide">OpenSwarm Testbed</h1>
        <div onClick={() => setOpen(true)} className="text-sm opacity-80">{token ? "Logged-in" : "Login"}</div>
      </header>

      <LoginModal open={open} setOpen={setOpen} token={token} setToken={setToken} />
      <div className="flex flex-1">
        <aside className="w-56 bg-white/70 backdrop-blur-md border-r border-gray-200 shadow-sm flex flex-col p-4 space-y-3">
          {["Home", "Calendar", "Data Table"].map((label, i) => (
            <button
              key={label}
              onClick={() => setPage(i + 1)}
              className={`text-left px-4 py-2 rounded-xl font-medium transition-all ${page === i + 1
                ? "bg-[#1E91C7] text-white shadow"
                : "text-gray-700 hover:bg-[#1E91C7]/10"
                }`}
            >
              {label}
            </button>
          ))}
        </aside>

        <main className="flex-1 p-8">
          {page === 1 && (
            < HomePage token={token} />
          )}

          {page === 2 && (
            < CalendarPage token={token} setToken={setToken} />
          )}

          {page === 3 && (
            <OnlineDotBotPage dotbots={dotbots} />
          )}
        </main>
      </div>
    </div>
  );
}
