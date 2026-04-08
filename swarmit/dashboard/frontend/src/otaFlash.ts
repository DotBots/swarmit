import { API_URL } from "./App";

const OTA_START_POLL_TIMEOUT = 120;  // 60 s at 500 ms per poll
const OTA_TRANSFER_POLL_TIMEOUT = 240; // 120 s at 500 ms per poll
const POLL_INTERVAL_MS = 500;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface OtaProgress {
  /** Chunks acknowledged so far (min across all devices). 0 before transfer starts. */
  acked: number;
  /** Total chunks to transfer. 0 before OTA start completes. */
  total: number;
}

/**
 * Run the full OTA flash sequence against the REST API.
 *
 * @param firmware_b64 - Base64-encoded firmware binary.
 * @param token        - Bearer token string.
 * @param devices      - List of device addresses to flash, or null for all.
 * @param onStatus     - Callback invoked with a human-readable status message
 *                       at each phase change.
 * @param onProgress   - Callback invoked on every transfer poll with current
 *                       progress so callers can render a progress bar.
 */
export async function otaFlash(
  firmware_b64: string,
  token: string,
  devices: string[] | null,
  onStatus: (msg: string) => void,
  onProgress?: (progress: OtaProgress) => void,
): Promise<void> {
  const authJson = {
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json",
  };
  const authOnly = { "Authorization": `Bearer ${token}` };

  // Step 1 – initiate OTA start (non-blocking)
  onStatus("Starting OTA negotiation...");
  const startRes = await fetch(`${API_URL}/ota/start`, {
    method: "POST",
    headers: authJson,
    body: JSON.stringify({ firmware_b64, devices: devices ?? null }),
  });
  if (!startRes.ok) {
    const data = await startRes.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to initiate OTA start");
  }

  // Step 2 – poll /ota/start/status until status === "done"
  onStatus("Waiting for devices to acknowledge...");
  let startStatus: {
    status: string;
    acked: string[];
    missed: string[];
    total_chunks: number;
    fw_hash: string;
  } | null = null;

  for (let i = 0; i < OTA_START_POLL_TIMEOUT; i++) {
    const res = await fetch(`${API_URL}/ota/start/status`, { headers: authOnly });
    const data = await res.json();
    if (data.status === "done") {
      startStatus = data;
      break;
    }
    await sleep(POLL_INTERVAL_MS);
  }

  if (!startStatus) {
    throw new Error("OTA start timed out waiting for device acknowledgements");
  }
  if (startStatus.missed.length > 0) {
    throw new Error(
      `${startStatus.missed.length} device(s) missed OTA start: ${startStatus.missed.join(", ")}`,
    );
  }

  // Step 3 – start the chunk transfer
  onStatus(`Transferring firmware (${startStatus.total_chunks} chunks)...`);
  onProgress?.({ acked: 0, total: startStatus.total_chunks });
  const transferRes = await fetch(`${API_URL}/ota/transfer`, {
    method: "POST",
    headers: authJson,
    body: JSON.stringify({ devices: startStatus.acked }),
  });
  if (transferRes.status === 409) {
    throw new Error("OTA transfer already in progress");
  }
  if (!transferRes.ok) {
    const data = await transferRes.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to start OTA transfer");
  }

  // Step 4 – poll /ota/transfer/status until success or failure
  for (let i = 0; i < OTA_TRANSFER_POLL_TIMEOUT; i++) {
    const res = await fetch(`${API_URL}/ota/transfer/status`, { headers: authOnly });
    const data = await res.json();

    if (data.total_chunks > 0 && data.devices && Object.keys(data.devices).length > 0) {
      const minAcked = Math.min(
        ...Object.values<{ chunks_acked: number }>(data.devices).map((d) => d.chunks_acked),
      );
      onProgress?.({ acked: minAcked, total: data.total_chunks });
    }

    if (data.status === "success") {
      onProgress?.({ acked: data.total_chunks, total: data.total_chunks });
      return;
    }
    if (data.status === "failed") {
      throw new Error(data.error || "Firmware transfer failed");
    }
    await sleep(POLL_INTERVAL_MS);
  }

  throw new Error("OTA transfer timed out");
}
