import { useState } from "react";

interface IssueRequest {
  start: string;
}

interface VerifyResult {
  valid: boolean;
  reason?: string;
  payload?: any;
}

export default function CalendarPage() {
  const [start, setStart] = useState<string>("");
  const [token, setToken] = useState<string>("");
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

  // --- Web Crypto helpers ---
  const importPublicKey = async (pem: string): Promise<CryptoKey> => {
    const pemHeader = "-----BEGIN PUBLIC KEY-----";
    const pemFooter = "-----END PUBLIC KEY-----";
    const base64 = pem.replace(pemHeader, "").replace(pemFooter, "").replace(/\s/g, "");
    const binaryDer = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    return crypto.subtle.importKey(
      "spki",
      binaryDer.buffer,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      true,
      ["verify"]
    );
  };

  const verifyJWT = async (token: string, publicKeyPem: string): Promise<VerifyResult> => {
    const [headerB64, payloadB64, signatureB64] = token.split(".");
    const payload = JSON.parse(atob(payloadB64));

    const enc = new TextEncoder();
    const data = enc.encode(`${headerB64}.${payloadB64}`);
    const signature = Uint8Array.from(
      atob(signatureB64.replace(/-/g, "+").replace(/_/g, "/")),
      (c) => c.charCodeAt(0)
    );

    const key = await importPublicKey(publicKeyPem);
    const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature, data);

    const now = Math.floor(Date.now() / 1000);
    if (!valid) return { valid: false, reason: "Invalid signature" };
    if (payload.nbf && now < payload.nbf) return { valid: false, reason: "Token not active yet" };
    if (payload.exp && now > payload.exp) return { valid: false, reason: "Token expired" };

    return { valid: true, payload };
  };

  const handleVerify = async () => {
    if (!token) return;
    const publicKeyPem = await fetch("http://localhost:8883/public_key").then((r) => r.json());
    const res = await verifyJWT(token, publicKeyPem.data);
    setResult(res.valid ? `✅ Valid: ${JSON.stringify(res.payload, null, 2)}` : `❌ ${res.reason}`);
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-6">
      <div className="bg-white shadow-lg rounded-2xl p-8 w-full max-w-lg">
        <h1 className="text-2xl font-bold mb-6 text-gray-800">
          🔐 JWT Time Window Demo (TSX)
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
                JWT Token
              </label>
              <textarea
                readOnly
                value={token}
                rows={5}
                className="w-full p-2 border rounded-lg bg-gray-50 font-mono text-xs"
              />
              <button
                onClick={handleVerify}
                className="mt-3 w-full bg-green-600 text-white py-2 rounded-lg hover:bg-green-700 transition"
              >
                Verify Token
              </button>
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
