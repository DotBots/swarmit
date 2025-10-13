import { useState, Dispatch, SetStateAction } from "react";

type VerifyResult =
  | { valid: true; fresh: boolean; payload: TokenPayload }
  | { valid: false; reason: string };

interface TokenPayload {
  iat: number; // issued at
  nbf: number; // not before
  exp: number; // expiration
}

interface LoginProps {
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  token: string;
  setToken: Dispatch<SetStateAction<string>>;
}

export default function LoginModal({ open, setOpen, token, setToken }: LoginProps) {
  const [unverifiedToken, setUnverifiedToken] = useState<string>("");
  const [message, setMessage] = useState<string>("");

  const handleVerify = async () => {
    if (!unverifiedToken) return;
    setMessage("");
    const publicKeyPem = await fetch("http://localhost:8883/public_key").then((r) => r.json());
    const res = await verifyJWT(unverifiedToken, publicKeyPem.data);
    if (res.valid) {
      setToken(unverifiedToken);
      setUnverifiedToken("");
      setOpen(false);
    } else {
      setMessage(res.reason)
    };
  };

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
    // Token not active yet
    if (payload.nbf && now < payload.nbf) return { valid: true, fresh: false, payload };
    // Token expired
    if (payload.exp && now > payload.exp) return { valid: true, fresh: false, payload };

    return { valid: true, fresh: true, payload };
  };

  return (
    <div className="p-4">
      {open && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/50">
          <div className="bg-white p-6 rounded-2xl shadow-lg w-80">
            <h2 className="text-lg font-semibold mb-3">Enter JWT</h2>
            <input
              type="text"
              value={unverifiedToken}
              onChange={(e) => setUnverifiedToken(e.target.value)}
              placeholder={token}
              className="w-full border p-2 rounded mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setUnverifiedToken(""); setOpen(false) }}
                className="px-3 py-1 text-gray-500"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  handleVerify();
                }}
                className="px-3 py-1 bg-blue-600 text-white rounded"
              >
                Verify & Save
              </button>
            </div>
            {message && (
              <div className="mt-6 bg-gray-100 p-3 rounded-lg text-sm font-mono text-gray-800 whitespace-pre-wrap">
                {message}
              </div>
            )}
          </div>
        </div>
      )
      }
    </div >
  );
}
