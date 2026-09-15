import { useEffect, useState } from "react";
import OnlineDotBotPage from "./OnlineDotBotPage";
import CalendarPage from "./CalendarPage";
import HomePage from "./HomePage";
import LoginModal from "./Login";

export const API_URL = `${window.location.origin}`;

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

// What a bot reports it is running. Absent until the bot has answered a
// device-info request, and permanently absent on firmware that predates the
// message, so every consumer has to tolerate null.
export type DeviceInfoData = {
  info_gen: number;
  boot_count: number;
  uptime_s: number;
  boot_reason: number;
  bl_version: string;
  net_version: string;
  image_state: number;
  image_result: number;
  image_size: number;
  image_digest: string;
  image_name: string;
  image_version: string;
  lh2_homography_count: number;
  lh2_flags: number;
};

export type DotBotData = {
  device: DeviceType;
  status: StatusType;
  battery: number;
  pos_x: number;
  pos_y: number;
  info_gen?: number;
  info?: DeviceInfoData | null;
};

// The digest is the identity; the name is display-only and a bot flashed by
// an older controller simply has none.
export const imageLabel = (bot: DotBotData): string =>
  bot.info ? bot.info.image_name || bot.info.image_digest.slice(0, 16) || "-" : "-";

type SettingsType = {
  network_id: string;
  auth_mode: string;
};

export type tokenActivenessType =
  | "NoToken"
  | "Active"
  | "NotValidYet"
  | "Expired"
  | "AuthDisabled"

export const isAuthorized = (t: tokenActivenessType): boolean =>
  t === "Active" || t === "AuthDisabled";

export const authHeaders = (
  token: Token | null,
  tokenActiveness: tokenActivenessType,
): Record<string, string> =>
  tokenActiveness === "AuthDisabled" || !token
    ? {}
    : { Authorization: `Bearer ${token.token}` };

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

// One rectangle of the active area set, in frame millimetres. An area is a
// view of the frame and carries no calibration.
export interface Area {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SettingsResponse {
  network_id: number;
  areas: Area[];
  reference_points: number[][];
  auth_mode: string;
}


const DEFAULT_AREA: Area = {x: 0, y: 0, w: 2000, h: 2000};

function unionAreas(list: Area[]): Area {
  if (list.length === 0) return DEFAULT_AREA;
  const x = Math.min(...list.map((b) => b.x));
  const y = Math.min(...list.map((b) => b.y));
  const xMax = Math.max(...list.map((b) => b.x + b.w));
  const yMax = Math.max(...list.map((b) => b.y + b.h));
  return {x, y, w: xMax - x, h: yMax - y};
}


export default function MainDashboard() {
  const [page, setPage] = useState<number>(1);
  const [openLoginPopup, setOpenLoginPopup] = useState<boolean>(false);
  const [dotbots, setDotBots] = useState<Record<string, DotBotData>>({});
  const { token, setToken } = usePersistedToken();
  const [tokenActiveness, setTokenActiveness] = useState<tokenActivenessType>("NoToken");
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [area, setArea] = useState<Area>({x: 0, y: 0, w: 2000, h: 2000});
  const [referencePoints, setReferencePoints] = useState<number[][]>([]);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await fetch(`${API_URL}/settings`);
        if (!res.ok) throw new Error("Network response was not ok");

        const json = await res.json();
        const settings: SettingsType = {
          network_id: json.network_id.toString(16),
          auth_mode: json.auth_mode,
        };
        setSettings(settings);
        // The dashboard draws one box, so an active set is drawn over its
        // bounding box.
        setArea(unionAreas(json.areas ?? []));
        setReferencePoints(json.reference_points ?? []);
        if (json.auth_mode === "none") {
          setTokenActiveness("AuthDisabled");
        }
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
              .map(([k, v]) => [k, { ...v, battery: v.battery / 1000, pos_x: v.pos_x, pos_y: v.pos_y }]));
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
    AuthDisabled: "Logged in (local mode, auth off)",
  };

  const authDisabled = settings?.auth_mode === "none";
  const navItems: { label: string; page: number; disabled: boolean }[] = [
    { label: "Home", page: 1, disabled: false },
    { label: "Reservations", page: 2, disabled: authDisabled },
    { label: "DotBots Info", page: 3, disabled: false },
  ];

  return (
    <div className="h-screen flex flex-col bg-gradient-to-br from-[#1E91C7]/10 to-white overflow-hidden">
      <header className="shrink-0 bg-gradient-to-r from-[#1E91C7] to-[#187AA3] text-white py-4 px-8 shadow-lg flex items-center justify-between border-b border-[#135C7B]/30">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-semibold tracking-wide">DotBot Testbed</h1>
          {settings?.network_id && (
            <span className="font-mono text-xs px-2.5 py-0.5 rounded-full bg-white/15 opacity-90">
              0x{settings.network_id.toUpperCase()}
            </span>
          )}
          <span
            className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-white/15 text-xs font-medium tabular-nums"
            title={`${Object.keys(dotbots).length} device(s) currently visible`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${Object.keys(dotbots).length > 0 ? "bg-green-300 animate-pulse" : "bg-gray-300"}`} />
            {Object.keys(dotbots).length} {Object.keys(dotbots).length === 1 ? "device" : "devices"}
          </span>
        </div>
        {authDisabled ? (
          <span className="text-sm px-3 py-1 rounded-full bg-white/15 opacity-80">
            {loginLabel[tokenActiveness]}
          </span>
        ) : (
          <button
            onClick={() => setOpenLoginPopup(true)}
            className="text-sm px-3 py-1 rounded-full bg-white/15 hover:bg-white/25 transition"
          >
            {loginLabel[tokenActiveness]}
          </button>
        )}
      </header>

      <LoginModal open={openLoginPopup} setOpen={setOpenLoginPopup} token={token} setToken={setToken} />
      <div className="flex flex-1 min-h-0">
        <aside className="shrink-0 w-56 bg-white/70 backdrop-blur-md border-r border-gray-200 shadow-sm flex flex-col p-4 space-y-3 overflow-y-auto">
          {navItems.map(({ label, page: targetPage, disabled }) => (
            <button
              key={label}
              onClick={() => setPage(targetPage)}
              disabled={disabled}
              title={disabled ? "Disabled in local mode" : undefined}
              className={`text-left px-4 py-2 rounded-xl font-medium transition-all ${disabled
                ? "text-gray-400 cursor-not-allowed"
                : page === targetPage
                  ? "bg-[#1E91C7] text-white shadow"
                  : "text-gray-700 hover:bg-[#1E91C7]/10"
                }`}
            >
              {label}
            </button>
          ))}
          {/* mt-auto pushes the logo to the bottom of the flex column. */}
          <div className="mt-auto pt-4 flex justify-center">
            <img
              src="/logo.png"
              alt=""
              className="max-w-full max-h-24 opacity-90"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            />
          </div>
        </aside>

        <main className="flex-1 p-8 overflow-y-auto">
          {page === 1 && (
            < HomePage token={token} tokenActiveness={tokenActiveness} dotbots={dotbots} area={area} referencePoints={referencePoints} />
          )}

          {page === 2 && (
            < CalendarPage token={token} setToken={setToken} />
          )}

          {page === 3 && (
            < OnlineDotBotPage dotbots={dotbots} token={token} tokenActiveness={tokenActiveness} />
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
