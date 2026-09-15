import clsx from "clsx";
import TermGroup from "./TermGroup";
import Stat from "./Stat";
import { durationSeconds, label, SEVERITY_TEXT, type Finding, type Report } from "@/lib/report";

function groupByTerm(findings: Finding[]): Finding[][] {
  const groups = new Map<string, Finding[]>();
  for (const f of findings) {
    const g = groups.get(f.term);
    if (g) g.push(f); else groups.set(f.term, [f]);
  }
  return Array.from(groups.values());
}

/** Renders one report payload. Pure — used for both the cached and a freshly fetched report. */
export default function ReportView({ report }: { report: Report }) {
  const s = report.summary;
  const secs = durationSeconds(report);
  const interactions = groupByTerm(report.findings.filter((f) => f.effect_type === "interaction"));
  const mains = groupByTerm(report.findings.filter((f) => f.effect_type !== "interaction"));
  const lawful = groupByTerm(report.lawful_dynamic);
  const unfitted = report.diagnostics.filter((d) => !d.fitted);

  return (
    <div className="space-y-12">
      <section>
        <div
          className={clsx(
            "bg-card border border-line border-l-4 rounded-lg p-5 text-lg leading-relaxed",
            s.highest_severity === "high" ? "border-l-high" : s.highest_severity === "moderate" ? "border-l-moderate" : s.highest_severity === "low" ? "border-l-low" : "border-l-lawful",
          )}
        >
          {s.headline}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
          <Stat value={s.flagged_by_severity.high} label="high risk" tone={SEVERITY_TEXT.high} />
          <Stat value={s.flagged_by_severity.moderate} label="moderate" tone={SEVERITY_TEXT.moderate} />
          <Stat value={s.flagged_by_severity.low} label="low" tone={SEVERITY_TEXT.low} />
          <Stat value={s.interaction_finding_count} label="compounding" tone="text-ink" />
          <Stat value={s.lawful_dynamic_finding_count} label="lawful dynamic" tone={SEVERITY_TEXT.lawful} />
          <Stat value={s.clean_individual_signals.length} label="signals clean" tone="text-accent" />
        </div>
        <p className="text-sm text-muted mt-3 tnum">
          {report.store} · generated {report.generated_at.replace("T", " ").replace("+00:00", " UTC")}
          {report.probe.session_count ? ` · ${report.probe.session_count.toLocaleString()} synthetic sessions` : ""}
          {report.probe.sessions_per_product ? ` · ${report.probe.sessions_per_product} per product (${report.probe.design ?? "full"} factorial)` : ""}
          {secs !== null ? ` · ${secs.toFixed(0)} s` : ""}
          {report.probe.failure_count ? ` · ${report.probe.failure_count} failed requests` : ""}
        </p>
      </section>

      <Section title="Personalized pricing findings" count={mains.length} blurb="Individual-based signals that moved the price, holding every other signal constant.">
        {mains.length ? mains.map((g) => <TermGroup key={g[0].term} findings={g} />) : <Empty>None. No individual-based signal moved the price beyond the detection threshold.</Empty>}
      </Section>

      <Section title="Compounding effects" count={interactions.length} blurb="Two individual-based signals together costing more than the sum of their own effects — a stronger surveillance-pricing indicator than either alone.">
        {interactions.length ? interactions.map((g) => <TermGroup key={g[0].term} findings={g} />) : <Empty>No compounding effects between individual-based signals.</Empty>}
      </Section>

      <Section title="Individual-based signals that came back clean" count={s.clean_individual_signals.length} blurb="Tested, and not statistically distinguishable from the control session after FDR correction.">
        {s.clean_individual_signals.length ? (
          <ul className="flex flex-wrap gap-2">
            {s.clean_individual_signals.map((v) => (
              <li key={v} className="bg-lawful/10 text-lawful rounded-full px-3 py-1 text-sm">{label(v)}</li>
            ))}
          </ul>
        ) : <Empty>None — every individual-based signal tested produced a finding.</Empty>}
        {report.clean.filter((f) => f.effect_type === "interaction").length > 0 && (
          <p className="text-sm text-muted mt-3">
            Also clean: {Array.from(new Set(report.clean.filter((f) => f.effect_type === "interaction").map((f) => f.term))).join(", ")} (interactions).
          </p>
        )}
      </Section>

      <Section title="Market-based (lawful dynamic) pricing observed" count={lawful.length} blurb="Price variance driven by conditions that apply to every shopper. Surfaced for visibility, never flagged.">
        {lawful.length ? lawful.map((g) => <TermGroup key={g[0].term} findings={g} />) : <Empty>No market-driven price variance observed.</Empty>}
      </Section>

      {unfitted.length > 0 && (
        <Section title="Not assessed" count={unfitted.length} blurb="Products skipped rather than guessed at.">
          <ul className="text-sm space-y-1">
            {unfitted.map((d) => <li key={d.product_id}><span className="font-mono">{d.product_id}</span>: {d.reason}</li>)}
          </ul>
        </Section>
      )}

      <Section title="Methodology">
        <p className="text-sm leading-relaxed text-ink/80">{report.methodology_note}</p>
        <p className="text-sm mt-3"><a href="/methodology" className="text-accent underline underline-offset-2">Full methodology, with what each claim is tested against →</a></p>
      </Section>
    </div>
  );
}

function Section({ title, count, blurb, children }: { title: string; count?: number; blurb?: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xl font-bold tracking-tight flex items-baseline gap-2">
        {title}
        {count !== undefined && <span className="text-sm font-medium text-muted tnum">{count}</span>}
      </h2>
      {blurb && <p className="text-sm text-muted mt-1">{blurb}</p>}
      <div className="space-y-3 mt-4">{children}</div>
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}
