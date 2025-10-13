import { Dispatch, SetStateAction, useState } from "react";

interface IssueRequest {
  start: string;
}

interface CalendarPageProps {
  token: string;
  setToken: Dispatch<SetStateAction<string>>;
}

export default function CalendarPage({ token, setToken }: CalendarPageProps) {
  const [start, setStart] = useState<string>("");
  const [result, setResult] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  // --- Issue JWT ---
  const handleIssue = async () => {
    setResult(null);
    setToken("");
    setLoading(true);

    try {
      const res = await fetch("http://localhost:8883/issue_jwt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start } as IssueRequest),
      });

      if (!res.ok) {
        const err = await res.text();
        setResult(`❌ ${err}`);
        return;
      }

      const data: { data: string } = await res.json();
      setToken(data.data);
    } catch (e: any) {
      setResult(`❌ ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center p-6">
      <div className="bg-white shadow-lg rounded-2xl p-8 w-full max-w-lg">
        <h1 className="text-2xl font-bold mb-6 text-gray-800">
          JWT Time Window Demo
        </h1>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-600">
              Start (ISO 8601)
            </label>
            <input
              type="datetime-local"
              className="w-full p-2 border rounded-lg mt-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>

          <button
            onClick={handleIssue}
            disabled={loading}
            className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 transition disabled:opacity-50"
          >
            {loading ? "Issuing..." : "Generate Token"}
          </button>

          {token && (
            <div className="mt-6">
              <label className="block text-sm font-medium text-gray-600 mb-1">
                JWT Token (Please copy and don't share with anyone!)
              </label>
              <textarea
                readOnly
                value={token}
                rows={10}
                className="w-full p-2 border rounded-lg bg-gray-50 font-mono text-xs"
              />
            </div>
          )}

          {result && (
            <div className="mt-6 bg-gray-100 p-3 rounded-lg text-sm font-mono text-gray-800 whitespace-pre-wrap">
              {result}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
