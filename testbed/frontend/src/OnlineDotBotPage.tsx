import { DotBotData } from "./App";
import { DotBotsMap } from "./BotMap";

interface CalendarPageProps {
  dotbots: Record<string, DotBotData>;
}

export default function OnlineDotBotPage({ dotbots }: CalendarPageProps) {
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DotBotsMap dotbots={dotbots} />
    </div>
  );
}
