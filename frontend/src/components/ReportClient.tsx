"use client";

import { useEffect, useRef, useState } from "react";
import { Play, Loader2, RotateCcw, AlertTriangle } from "lucide-react";
import ReportView from "./ReportView";
import { ApiError, apiConfigured, runLiveAudit, API_URL } from "@/lib/api";
import type { Report } from "@/lib/report";

type Status = "idle" | "running" | "done" | "error";

/**
 * Shows the committed report immediately, and lets the visitor re-run the
 * audit against live GhostCart through the backend. The run takes 15–60 s
 * (1,920 HTTP probes), so there's a progress state; if the API isn't
 * reachable or has no probe secret the button explains why instead of
 * failing silently.
 */
export default function ReportClient({ initial }: { initial: Report }) {
  const [report, setReport] = useState<Report>(initial);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    apiConfigured().then(setAvailable);
  }, []);

  useEffect(() => {
    if (status !== "running") return;
    const t0 = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - t0) / 1000), 200);
    return () => clearInterval(id);
  }, [status]);

  async function run() {
    abort.current?.abort();
    abort.current = new AbortController();
    setStatus("running");
    setError(null);
    try {
      const fresh = await runLiveAudit(abort.current.signal);
      setReport(fresh);
      setStatus("done");
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError(e instanceof ApiError ? e.message : String(e));
      setStatus("error");
    }
  }

  const isLive = status === "done";
  const sessions = report.probe.session_count ?? 1920;

  return (
    <div>
      <div className="bg-card border border-line rounded-lg p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center gap-4 mb-8">
        <div className="flex-1">
          <p className="font-semibold">
            {isLive ? "Live result — just probed GhostCart" : "Showing the committed audit"}
          </p>
          <p className="text-sm text-muted mt-0.5">
            {status === "running"
              ? `Probing ${sessions.toLocaleString()} synthetic sessions across ${report.summary.products_tested.length} products… ${elapsed.toFixed(0)} s`
              : available === false
                ? `Live re-runs need the audit API (${API_URL}) with a GhostCart probe secret. The report below was produced by exactly that pipeline and is committed with the repo.`
                : "Re-run the whole pipeline against live GhostCart: a 192-cell factorial design per product, robust regression, FDR correction. Deterministic endpoint, so expect the same numbers."}
          </p>
          {status === "error" && error && (
            <p className="text-sm text-high mt-2 flex items-start gap-1.5">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden /> {error}
            </p>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          {isLive && (
            <button
              onClick={() => { setReport(initial); setStatus("idle"); }}
              className="inline-flex items-center gap-1.5 text-sm border border-line rounded-md px-3 py-2 hover:bg-paper focus-ring"
            >
              <RotateCcw className="w-4 h-4" aria-hidden /> Committed
            </button>
          )}
          <button
            onClick={run}
            disabled={status === "running" || available === false}
            className="inline-flex items-center gap-2 bg-accent hover:bg-accentDark disabled:opacity-50 disabled:hover:bg-accent text-white font-semibold rounded-md px-4 py-2 focus-ring transition-colors"
          >
            {status === "running" ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : <Play className="w-4 h-4" aria-hidden />}
            {status === "running" ? "Auditing…" : "Run the audit live"}
          </button>
        </div>
      </div>
      <ReportView report={report} />
    </div>
  );
}
