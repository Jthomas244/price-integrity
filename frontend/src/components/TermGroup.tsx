import clsx from "clsx";
import { Check } from "lucide-react";
import SeverityBadge from "./SeverityBadge";
import { pct, type Finding } from "@/lib/report";

/**
 * One card per term (signal or signal pair), with a row per product.
 * Findings arrive most-severe first, so the first one is the representative
 * for the badge and the plain-English detail.
 */
export default function TermGroup({ findings, compact = false }: { findings: Finding[]; compact?: boolean }) {
  const rep = findings[0];
  const rows = [...findings].sort((a, b) => a.product_id.localeCompare(b.product_id));
  const hasStats = rep.p_value_corrected !== null;
  const levels = Object.entries(rep.variant_breakdown);
  const significant = new Set(rep.significant_variants);

  return (
    <article className="bg-card border border-line rounded-lg p-4 sm:p-5">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <SeverityBadge severity={rep.severity} />
        <h3 className="font-semibold capitalize text-lg">{rep.term}</h3>
        {rep.effect_type === "interaction" && (
          <span className="text-[11px] uppercase tracking-wider text-muted border border-line rounded px-1.5">compounding</span>
        )}
        <span className="text-xs text-muted ml-auto tnum">{rows.length} {rows.length === 1 ? "product" : "products"}</span>
      </header>
      <p className="mt-2 text-sm leading-relaxed text-ink/90">{rep.detail}</p>

      {levels.length > 1 && (
        <p className="mt-2 text-xs text-muted flex flex-wrap gap-x-3 gap-y-1">
          <span>Levels ({rep.product_id}):</span>
          {levels.map(([v, e]) => (
            <span key={v} className="tnum">
              {v.replace(/^.*= /, "")} <span className={clsx("font-mono", e > 0 ? "text-high" : e < 0 ? "text-lawful" : "")}>{pct(e)}</span>
              {significant.has(v) && <Check className="inline w-3 h-3 ml-0.5 text-lawful" aria-label="significant" />}
            </span>
          ))}
        </p>
      )}

      {!compact && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted text-xs">
                <th className="text-left font-medium pb-1">Product</th>
                <th className="text-right font-medium pb-1">Effect</th>
                {hasStats && <th className="text-right font-medium pb-1 hidden sm:table-cell">95% CI</th>}
                {hasStats && <th className="text-right font-medium pb-1">FDR-corrected p</th>}
                <th className="text-right font-medium pb-1 hidden sm:table-cell">n</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => {
                const signed = f.direction === "discount" ? -f.variance_pct : f.variance_pct;
                return (
                  <tr key={f.product_id} className="border-t border-line/70">
                    <td className="py-1.5 pr-3 font-mono text-[13px]">{f.product_id}</td>
                    <td className={clsx("py-1.5 text-right tnum font-mono text-[13px]", signed > 0 ? "text-high" : signed < 0 ? "text-lawful" : "text-muted")}>
                      {f.severity === "none" ? "—" : pct(signed)}
                    </td>
                    {hasStats && (
                      <td className="py-1.5 text-right tnum font-mono text-[13px] text-muted hidden sm:table-cell">
                        {f.ci_low_pct !== null ? `${pct(f.ci_low_pct)} to ${pct(f.ci_high_pct!)}` : "—"}
                      </td>
                    )}
                    {hasStats && <td className="py-1.5 text-right tnum font-mono text-[13px] text-muted">{f.p_value_corrected!.toFixed(4)}</td>}
                    <td className="py-1.5 text-right tnum text-muted hidden sm:table-cell">{f.sample_size}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
