import { useEffect, useState } from "react";
import OnlineDotBotPage from "./OnlineDotBotPage";
import CalendarPage from "./CalendarPage";
import HomePage from "./HomePage";
import LoginModal from "./Login";

export const API_URL = import.meta.env.BACKEND_API_URL || "http://localhost:8883";

export interface Token {
  token: string;
  payload: TokenPayload
}

export interface TokenPayload {
  iat: number; // issued at
  nbf: number; // not before
  exp: number; // expiration
}

export type StatusType =
  | "Bootloader"
  | "Running"
  | "Stopping"
  | "Resetting"
  | "Programming";

type DeviceType =
  | "Unknown"
  | "DotBotV3"
  | "DotBotV2"
  | "nRF5340DK"
  | "nRF52840DK";

export type DotBotData = {
  device: DeviceType;
  status: StatusType;
  battery: number;
  pos_x: number;
  pos_y: number;
};

type SettingsType = {
  network_id: string;
};

export type tokenActivenessType =
  | "NoToken"
  | "Active"
  | "NotValidYet"
  | "Expired"

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

export interface SettingsResponse {
  response: {
    network_id: number;
  };
}


export default function InriaDashboard() {
  const [page, setPage] = useState<number>(1);
  const [openLoginPopup, setOpenLoginPopup] = useState<boolean>(false);
  const [dotbots, setDotBots] = useState<Record<string, DotBotData>>({});
  const { token, setToken } = usePersistedToken();
  const [tokenActiveness, setTokenActiveness] = useState<tokenActivenessType>("NoToken");
  const [settings, setSettings] = useState<SettingsType | null>(null);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await fetch(`${API_URL}/settings`);
        if (!res.ok) throw new Error("Network response was not ok");

        const json: SettingsResponse = await res.json();
        const settings: SettingsType = {
          network_id: json.response.network_id.toString(16),
        };
        setSettings(settings);
      } catch (err) {
        console.error("Error fetching settings:", err);
      }
    };

    fetchSettings();
  }, []);


  useEffect(() => {
    if (!token) return;
    let canceled = false;
    const checkActiveness = () => {
      if (canceled) return;

      const active = checkTokenActiveness(token.payload);
      setTokenActiveness(active);
      if (active === "NotValidYet") {
        const now = Math.floor(Date.now() / 1000);
        const diff = token.payload.nbf - now;
        setTimeout(checkActiveness, diff * 1000);
      } else if (active === "Active") {
        const now = Math.floor(Date.now() / 1000);
        const diff = token.payload.exp - now;
        setTimeout(checkActiveness, diff * 1000);
      }
    };

    checkActiveness();

    return () => {
      canceled = true;
    };
  }, [token]);

  useEffect(() => {
    const fetchStatus = () => {
      fetch(`${API_URL}/status`)
        .then((res) => {
          if (!res.ok) throw new Error("network response was not ok");
          return res.json();
        })
        .then((json) => {
          const dotbots = Object.fromEntries(
            Object.entries(json.response as Record<string, DotBotData>)
              .map(([k, v]) => [k, { ...v, battery: v.battery / 1000, pos_x: v.pos_x / 1000000, pos_y: v.pos_y / 1000000 }]));
          setDotBots(dotbots);
        })
        .catch((_err) => {
        });
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 1000);

    return () => clearInterval(interval);
  }, []);

  const loginLabel: Record<tokenActivenessType, string> = {
    NoToken: "Login",
    Active: "Logged-in",
    NotValidYet: "Token not valid yet",
    Expired: "Token expired",
  };

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-[#1E91C7]/10 to-white">
      <header className="bg-[#1E91C7] text-white py-4 px-8 shadow-md flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-wide">OpenSwarm Testbed</h1>
        {settings?.network_id && <h1 className="text-m font-semibold tracking-wide">Network ID: 0x{settings?.network_id.toUpperCase()}</h1>}
        <div onClick={() => setOpenLoginPopup(true)} className="text-sm opacity-80">{loginLabel[tokenActiveness]}</div>
      </header>

      <LoginModal open={openLoginPopup} setOpen={setOpenLoginPopup} token={token} setToken={setToken} />
      <div className="flex flex-1">
        <aside className="w-56 bg-white/70 backdrop-blur-md border-r border-gray-200 shadow-sm flex flex-col p-4 space-y-3">
          {["Home", "Reservations", "DotBots Info"].map((label, i) => (
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
            < HomePage token={token} tokenActiveness={tokenActiveness} dotbots={dotbots} />
          )}

          {page === 2 && (
            < CalendarPage token={token} setToken={setToken} />
          )}

          {page === 3 && (
            < OnlineDotBotPage dotbots={dotbots} token={token} />
          )}
        </main>
      </div>
    </div>
  );
}

export const checkTokenActiveness = (payload: TokenPayload): tokenActivenessType => {
  const now = Math.floor(Date.now() / 1000);
  // Token not active yet
  if (payload.nbf && now < payload.nbf) return "NotValidYet";
  // Token expired
  if (payload.exp && now > payload.exp) return "Expired";
  return "Active";
};
