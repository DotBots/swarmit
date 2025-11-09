import { useState, Dispatch, SetStateAction } from "react";
import { API_URL, Token, TokenPayload } from "./App";

type VerifyResult =
  | { valid: true; payload: TokenPayload }
  | { valid: false; reason: string };

interface LoginProps {
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  token: Token | null;
  setToken: Dispatch<SetStateAction<Token | null>>;
}

export default function LoginModal({ open, setOpen, token, setToken }: LoginProps) {
  const [unverifiedToken, setUnverifiedToken] = useState<string>("");
  const [message, setMessage] = useState<string>("");

  const handleVerify = async () => {
    if (!unverifiedToken) return;
    setMessage("");
    const publicKeyPem = await fetch(`${API_URL}/public_key`).then((r) => r.json());
    const res = await verifyJWT(unverifiedToken, publicKeyPem.data);
    if (res.valid) {
      setToken({ token: unverifiedToken, payload: res.payload });
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
      { name: "Ed25519" },
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
    const valid = await crypto.subtle.verify({ name: "Ed25519" }, key, signature, data);

    const now = Math.floor(Date.now() / 1000);
    if (!valid) return { valid: false, reason: "Invalid signature" };
    // Token not active yet
    if (payload.nbf && now < payload.nbf) return { valid: true, payload };
    // Token expired
    if (payload.exp && now > payload.exp) return { valid: true, payload };

    return { valid: true, payload };
  };

  return (
    <div className="">
      {open && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/50 z-2">
          <div className="bg-white p-6 rounded-2xl shadow-lg w-160">
            <h2 className="text-lg font-semibold mb-3">Enter JWT</h2>
            <textarea
              value={unverifiedToken}
              onChange={(e) => setUnverifiedToken(e.target.value)}
              placeholder={token?.token || "Paste your JSON web token here"}
              className="w-full border p-2 rounded mb-4 h-32 overflow-auto font-mono"
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
