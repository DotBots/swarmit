import { useState } from "react";
import OnlineRobotPage from "./OnlineRobotPage";
import BlankPage from "./BlankPage";
import HomePage from "./HomePage";

export default function InriaDashboard() {
  const [page, setPage] = useState(1);

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
            < HomePage />
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
