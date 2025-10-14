import { useEffect, useState } from "react";
import { Token } from "./App";

interface HomePageProps {
  token: Token | null;
}

export default function HomePage({ token }: HomePageProps) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleStart = () => {
    if (!token) {
      setMessage("Please fill a token first");
      return;
    };
    setLoading(true);
    setMessage("Starting...");

    fetch("http://localhost:8883/start", {
      method: "POST", headers: {
        "Authorization": `Bearer ${token.token}`,
      }
    })
      .then((res) => {
        if (res.ok) {
          setMessage("Testbed started successfully");
        } else {
          return res
            .json()
            .then((data) => {
              setMessage(`Error: ${data.detail || "Failed to start testbed"}`);
            })
            .catch(() => {
              setMessage("Failed to start testbed");
            });
        }
      })
      .catch((_err) => {
        setMessage(`Error: couldn't authorize token`);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const handleStop = () => {
    if (!token) {
      setMessage("Please fill a token first");
      return;
    };
    setLoading(true);
    setMessage("Stopping...");

    fetch("http://localhost:8883/stop", {
      method: "POST", headers: {
        "Authorization": `Bearer ${token.token}`,
      }
    })
      .then((res) => {
        if (res.ok) {
          setMessage("Testbed stopped successfully");
        } else {
          return res
            .json()
            .then((data) => {
              setMessage(`Error: ${data.detail || "Failed to stop testbed"}`);
            })
            .catch(() => {
              setMessage("Failed to stop testbed");
            });
        }
      })
      .catch((_err) => {
        setMessage(`Error: couldn't authorize token`);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const handleFlash = () => {
    if (!token) {
      setMessage("Please fill a token first");
      return;
    };
    if (!file) {
      setMessage("Please select a file first");
      return;
    }

    setLoading(true);
    setMessage(null);

    const reader = new FileReader();

    reader.onload = () => {
      const base64 = (reader.result as string).split(",")[1];
      setMessage("Flashing...");

      fetch("http://localhost:8883/flash", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token.token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ firmware_b64: base64 }),
      })
        .then((res) =>
          res
            .json()
            .then((data) => ({ ok: res.ok, data }))
            .catch(() => ({ ok: res.ok, data: { error: "Invalid response" } }))
        )
        .then(({ ok, data }) => {
          if (ok) {
            setMessage("File flashed successfully");
          } else {
            setMessage(data.detail || "Unknown error");
          }
          setLoading(false);
        })
        .catch((_err) => {
          setMessage(`Error: couldn't authorize token`);
          setLoading(false);
        });
    };

    reader.readAsDataURL(file);
  };
  const unixToLocale = (t: number) => new Date(t * 1000).toLocaleString();

  return (
    <div className="max-w-md mx-auto p-6 space-y-6 bg-white rounded-2xl shadow mt-10 animate-fadeIn">
      {token?.payload && <div className="border p-4 rounded-lg bg-gray-50">
        <h3 className="font-semibold mb-2">Token Info</h3>
        <p><span className="font-medium">Issued at:</span> {unixToLocale(token?.payload.iat)}</p>
        <p><span className="font-medium">Not before:</span> {unixToLocale(token?.payload.nbf)}</p>
        <p><span className="font-medium">Expiration:</span> {unixToLocale(token?.payload.exp)}</p>
      </div>}
      <h1 className="text-2xl font-semibold text-gray-800 text-center">Testbed Control</h1>

      <div className="flex justify-between space-x-4">
        <button
          className="flex-1 py-2 px-4 bg-green-600 text-white rounded-lg hover:bg-green-700 transition disabled:cursor-not-allowed disabled:bg-green-900"
          onClick={() => handleStart()}
          disabled={loading}
        >
          Start
        </button>
        <button
          className="flex-1 py-2 px-4 bg-red-600 text-white rounded-lg hover:bg-red-700 transition disabled:cursor-not-allowed disabled:bg-red-900"
          onClick={() => handleStop()}
          disabled={loading}
        >
          Stop
        </button>
      </div>

      {loading && (
        <div role="status" className="flex items-center justify-center space-x-2">
          <svg aria-hidden="true" className="w-8 h-8 text-gray-200 animate-spin dark:text-gray-600 fill-blue-600" viewBox="0 0 100 101" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M100 50.5908C100 78.2051 77.6142 100.591 50 100.591C22.3858 100.591 0 78.2051 0 50.5908C0 22.9766 22.3858 0.59082 50 0.59082C77.6142 0.59082 100 22.9766 100 50.5908ZM9.08144 50.5908C9.08144 73.1895 27.4013 91.5094 50 91.5094C72.5987 91.5094 90.9186 73.1895 90.9186 50.5908C90.9186 27.9921 72.5987 9.67226 50 9.67226C27.4013 9.67226 9.08144 27.9921 9.08144 50.5908Z" fill="currentColor" />
            <path d="M93.9676 39.0409C96.393 38.4038 97.8624 35.9116 97.0079 33.5539C95.2932 28.8227 92.871 24.3692 89.8167 20.348C85.8452 15.1192 80.8826 10.7238 75.2124 7.41289C69.5422 4.10194 63.2754 1.94025 56.7698 1.05124C51.7666 0.367541 46.6976 0.446843 41.7345 1.27873C39.2613 1.69328 37.813 4.19778 38.4501 6.62326C39.0873 9.04874 41.5694 10.4717 44.0505 10.1071C47.8511 9.54855 51.7191 9.52689 55.5402 10.0491C60.8642 10.7766 65.9928 12.5457 70.6331 15.2552C75.2735 17.9648 79.3347 21.5619 82.5849 25.841C84.9175 28.9121 86.7997 32.2913 88.1811 35.8758C89.083 38.2158 91.5421 39.6781 93.9676 39.0409Z" fill="currentFill" />
          </svg>
          <span className="sr-only">Loading...</span>
        </div>
      )}

      <div className="space-y-2">
        <input
          type="file"
          accept=".bin"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="block w-full text-sm text-gray-600"
        />
        <button
          className="w-full py-2 px-4 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition disabled:cursor-not-allowed disabled:bg-blue-900"
          onClick={handleFlash}
          disabled={loading || !file}
        >
          Flash
        </button>
      </div>

      {message && <p className="text-center text-gray-700">{message}</p>}
    </div>
  );
}
