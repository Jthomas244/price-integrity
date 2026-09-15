import type { Report } from "./report";

/** Set at build time. Unset means this deployment has no audit backend — the
 * report page then serves the committed audit and says live re-runs are off. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
export const API_CONFIGURED = API_URL.length > 0;
export const GHOSTCART_URL = process.env.NEXT_PUBLIC_GHOSTCART_URL ?? "https://ghostcart-ten.vercel.app";
export const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/Jthomas244/price-integrity";

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
  }
}

/** POST /audit/ghostcart — probes live GhostCart and returns a fresh report. */
export async function runLiveAudit(signal?: AbortSignal): Promise<Report> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/audit/ghostcart`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Could not reach the audit API.");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {}
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as Report;
}

export async function apiConfigured(): Promise<boolean> {
  if (!API_CONFIGURED) return false;
  try {
    const res = await fetch(`${API_URL}/ghostcart`, { cache: "no-store" });
    if (!res.ok) return false;
    return Boolean((await res.json()).configured);
  } catch {
    return false;
  }
}
