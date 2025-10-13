import { useState } from "react";
import OnlineRobotPage from "./OnlineRobotPage";
import CalendarPage from "./CalendarPage";
import HomePage from "./HomePage";
import LoginModal from "./Login";


export default function InriaDashboard() {
  const [page, setPage] = useState(1);
  const [token, setToken] = useState<string>("");
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-[#C9191E]/10 to-white">
      <header className="bg-[#C9191E] text-white py-4 px-8 shadow-md flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-wide">Inria Dashboard</h1>
        <div onClick={() => setOpen(true)} className="text-sm opacity-80">inria.fr</div>
      </header>

      <LoginModal open={open} setOpen={setOpen} token={token} setToken={setToken} />
      <div className="flex flex-1">
        <aside className="w-56 bg-white/70 backdrop-blur-md border-r border-gray-200 shadow-sm flex flex-col p-4 space-y-3">
          {["Home", "Calendar", "Data Table"].map((label, i) => (
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

        <main className="flex-1 p-8">
          {page === 1 && (
            < HomePage />
          )}

          {page === 2 && (
            < CalendarPage token={token} setToken={setToken} />
          )}

          {page === 3 && (
            <OnlineRobotPage />
          )}
        </main>
      </div>
    </div>
  );
}
