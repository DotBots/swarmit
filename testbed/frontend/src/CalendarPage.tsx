import { ChangeEvent, Dispatch, SetStateAction, useState } from "react";

interface IssueRequest {
  start: string;
}

interface CalendarPageProps {
  token: string;
  setToken: Dispatch<SetStateAction<string>>;
}

export default function CalendarPage({ token, setToken }: CalendarPageProps) {
  const [dateTime, setDateTime] = useState<Date | null>(null);

  const [result, setResult] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const handleIssue = async () => {
    setResult(null);
    setToken("");
    setLoading(true);

    try {
      const res = await fetch("http://localhost:8883/issue_jwt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start: dateTime
            ? `${dateTime.getUTCFullYear()}-${(dateTime.getUTCMonth() + 1)
              .toString()
              .padStart(2, "0")}-${dateTime.getUTCDate().toString().padStart(2, "0")}T${dateTime
                .getUTCHours()
                .toString()
                .padStart(2, "0")}:${dateTime.getUTCMinutes().toString().padStart(2, "0")}Z`
            : null
        } as IssueRequest),
      });

      if (!res.ok) {
        const err = await res.text();
        setResult(`${err}`);
        return;
      }

      const data: { data: string } = await res.json();
      setToken(data.data);
    } catch (e: any) {
      setResult(`${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!dateTime) return;

    const start = new Date(dateTime);
    const end = new Date(dateTime);
    end.setMinutes(end.getMinutes() + 30);

    const fmt = (d: Date) =>
      d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";

    const ics = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "BEGIN:VEVENT",
      "SUMMARY:DotBots Event",
      `DTSTART:${fmt(start)}`,
      `DTEND:${fmt(end)}`,
      `DESCRIPTION:${token}`,
      "END:VEVENT",
      "END:VCALENDAR",
    ].join("\r\n");

    const blob = new Blob([ics], { type: "text/calendar" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "event.ics";
    a.click();
    URL.revokeObjectURL(url);
  };

  const generateTimeOptions = (): string[] => {
    const options: string[] = [];
    for (let hour = 0; hour < 24; hour++) {
      for (let min of [0, 30]) {
        const hh = hour.toString().padStart(2, "0");
        const mm = min.toString().padStart(2, "0");
        options.push(`${hh}:${mm}`);
      }
    }
    return options;
  };

  const displayValue = dateTime
    ? `${dateTime.getFullYear()}-${(dateTime.getMonth() + 1)
      .toString()
      .padStart(2, "0")}-${dateTime.getDate().toString().padStart(2, "0")}T${dateTime
        .getHours()
        .toString()
        .padStart(2, "0")}:${dateTime.getMinutes().toString().padStart(2, "0")}`
    : "";

  const handleDateChange = (e: ChangeEvent<HTMLInputElement>) => {
    const [year, month, day] = e.target.value.split("-").map(Number);
    const newDate = dateTime ? new Date(dateTime) : new Date();
    newDate.setFullYear(year, month - 1, day);
    setDateTime(newDate);
  };

  const handleTimeChange = (e: ChangeEvent<HTMLSelectElement>) => {
    const [hours, minutes] = e.target.value.split(":").map(Number);
    const newDate = dateTime ? new Date(dateTime) : new Date();
    newDate.setHours(hours, minutes, 0, 0);
    setDateTime(newDate);
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
              Start (datetime local)
            </label>

            <div>
              <label className="block">Date:</label>
              <input
                type="date"
                className="w-full p-2 border rounded-lg mt-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={dateTime ? displayValue.slice(0, 10) : ""}
                onChange={handleDateChange}
              />
            </div>

            <div>
              <label className="block">Time:</label>
              <select
                value={dateTime ? displayValue.slice(11, 16) : ""}
                onChange={handleTimeChange}
                className="w-full p-2 border rounded-lg mt-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select a time</option>
                {generateTimeOptions().map((t: string) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
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
              <button onClick={handleDownload}>Add to Calendar</button>
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
