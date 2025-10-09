export default function OnlineRobotPage({ publishCommand }) {
  const applyColor = async (r, g, b) => {
    let application = "0";
    let address = "482f353f8dd6ce8e";
    console.log("publish command");
    await publishCommand(address, application, "rgb_led", { red: r, green: g, blue: b });
  }

  return (
    <div className="animate-fadeIn">
      <h2 className="text-2xl font-semibold mb-6 text-gray-800">Data Table</h2>
      <div className="overflow-x-auto bg-white rounded-2xl shadow">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="bg-[#C9191E]/90 text-white">
              <th className="py-3 px-4 text-left font-semibold">Name</th>
              <th className="py-3 px-4 text-left font-semibold">Role</th>
              <th className="py-3 px-4 text-left font-semibold">Team</th>
            </tr>
          </thead>
          <tbody>
            {[
              { name: "Alice", role: "AAA", team: "ABC" },
              { name: "Bob", role: "BBB", team: "BCD" },
              { name: "Charlie", role: "CCC", team: "CDE" },
            ].map((row, i) => (
              <tr
                key={i}
                className={`hover:bg-[#C9191E]/5 transition-colors ${i % 2 === 0 ? "bg-gray-50" : "bg-white"
                  }`}
              >
                <td className="py-3 px-4 border-t" onClick={() => applyColor(255, 0, 0)}>{row.name}</td>
                <td className="py-3 px-4 border-t" onClick={() => applyColor(0, 255, 0)}>{row.role}</td>
                <td className="py-3 px-4 border-t" onClick={() => applyColor(0, 0, 255)}>{row.team}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
