// Types for the backend's report payload (audit_engine/report.py) and
// small presentation helpers shared by the landing page and the report.

export type Severity = "high" | "moderate" | "low" | "lawful" | "none";
export type Category = "market_based" | "individual_based";

export interface Finding {
  product_id: string;
  signal_type: string;
  signal_label: string;
  category: Category;
  variance_pct: number;
  severity: Severity;
  sample_size: number;
  detail: string;
  driving_variant: string | null;
  direction: "markup" | "discount" | null;
  variant_breakdown: Record<string, number>;
  effect_type: "main_effect" | "interaction";
  signals: string[];
  term: string;
  ci_low_pct: number | null;
  ci_high_pct: number | null;
  p_value_corrected: number | null;
  significant_variants: string[];
  variant_ci: Record<string, [number, number]>;
}

export interface Report {
  generated_at: string;
  store: string;
  probe: {
    observation_count: number | null;
    target?: string;
    design?: string;
    products_probed?: string[];
    signals_probed?: string[];
    signal_space?: Record<string, (string | number | boolean)[]>;
    reference_levels?: Record<string, string | number | boolean>;
    cells_per_product?: number;
    sessions_per_product?: number;
    session_count?: number;
    failure_count?: number;
    started_at?: string;
    finished_at?: string;
  };
  summary: {
    headline: string;
    highest_severity: Severity;
    flagged_finding_count: number;
    flagged_by_severity: Record<"high" | "moderate" | "low", number>;
    flagged_signals: string[];
    clean_individual_signals: string[];
    lawful_dynamic_finding_count: number;
    interaction_finding_count: number;
    signals_tested: string[];
    products_tested: string[];
  };
  findings: Finding[];
  lawful_dynamic: Finding[];
  clean: Finding[];
  diagnostics: { product_id: string; n_observations: number; n_parameters: number; fitted: boolean; reason: string | null; control_price: number | null }[];
  methodology_note: string;
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High",
  moderate: "Moderate",
  low: "Low",
  lawful: "Lawful dynamic",
  none: "Clean",
};

export const SEVERITY_CLASS: Record<Severity, string> = {
  high: "bg-high text-white",
  moderate: "bg-moderate text-white",
  low: "bg-low text-white",
  lawful: "bg-lawful text-white",
  none: "bg-ink/10 text-ink",
};

export const SEVERITY_TEXT: Record<Severity, string> = {
  high: "text-high",
  moderate: "text-moderate",
  low: "text-low",
  lawful: "text-lawful",
  none: "text-muted",
};

export const label = (s: string) => s.replace(/_/g, " ");

export const pct = (n: number, digits = 2) => `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;

/** One representative finding per term (signal or signal pair), for summaries. */
export function distinctTerms(findings: Finding[]): Finding[] {
  const seen = new Map<string, Finding>();
  for (const f of findings) if (!seen.has(f.term)) seen.set(f.term, f);
  return Array.from(seen.values());
}

export function durationSeconds(r: Report): number | null {
  const { started_at, finished_at } = r.probe;
  if (!started_at || !finished_at) return null;
  return Math.max(0, (Date.parse(finished_at) - Date.parse(started_at)) / 1000);
}

export const CATEGORY_COLOR: Record<Category | "clean", string> = {
  individual_based: "#B42318",
  market_based: "#12907A",
  clean: "#9AA0A6",
};

export function allFindings(r: Report): Finding[] {
  return [...r.findings, ...r.lawful_dynamic, ...r.clean];
}

/** "device type = mobile" -> "mobile"; "a = x × b = y" -> "x × y". */
export function shortLevel(level: string): string {
  return level.split(" × ").map((part) => part.replace(/^.*?= /, "")).join(" × ");
}

export function median(xs: number[]): number {
  const a = [...xs].sort((x, y) => x - y);
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
