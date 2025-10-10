import { useEffect, useState } from "react";

type RobotStatus = {
  device: string;
  status: string;
  battery: number;
  pos_x: number;
  pos_y: number;
};


export default function OnlineRobotPage() {
  const [data, setData] = useState<Record<string, RobotStatus> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStatus = () => {
      fetch("http://localhost:8883/status")
        .then((res) => {
          if (!res.ok) throw new Error("network response was not ok");
          return res.json();
        })
        .then((json) => {
          setData(json.response);
          setLoading(false);
          setError(null);
        })
        .catch((err) => {
          setError(err.message);
          setLoading(false);
        });
    };

    // Fetch immediately on mount
    fetchStatus();

    // Then fetch every 10 seconds
    const interval = setInterval(fetchStatus, 10000);

    // Cleanup interval on unmount
    return () => clearInterval(interval);
  }, []);

  console.log(`data: ${data}`);

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="text-red-500">Error: {error}</p>;
  // if (!data) return <p>No data available.</p>;


  return (
    <div className="animate-fadeIn">
      <h2 className="text-2xl font-semibold mb-6 text-gray-800">Data Table</h2>
      <div className="overflow-x-auto bg-white rounded-2xl shadow">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="bg-[#C9191E]/90 text-white">
              <th className="py-3 px-4 text-left font-semibold">Node Address</th>
              <th className="py-3 px-4 text-left font-semibold">Device</th>
              <th className="py-3 px-4 text-left font-semibold">Status</th>
              <th className="py-3 px-4 text-left font-semibold">Battery</th>
              <th className="py-3 px-4 text-left font-semibold">Pos (x, y)</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data).map(([id, robot], i) => (
              <tr
                key={id}
                className={`hover:bg-[#C9191E]/5 transition-colors ${i % 2 === 0 ? "bg-gray-50" : "bg-white"
                  }`}
              >
                <td className="py-3 px-4 border-t">{id}</td>
                <td className="py-3 px-4 border-t">{robot.device}</td>
                <td className="py-3 px-4 border-t">{robot.status}</td>
                <td className="py-3 px-4 border-t">{`${robot.battery / 100}V`}</td>
                <td className="py-3 px-4 border-t">{`(${robot.pos_x}, ${robot.pos_y})`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
