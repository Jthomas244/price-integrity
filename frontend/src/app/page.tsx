import Link from "next/link";
import { ArrowRight, FlaskConical, Sigma, ListChecks, ShieldCheck, ExternalLink } from "lucide-react";
import clsx from "clsx";
import Stat from "@/components/Stat";
import SeverityBadge from "@/components/SeverityBadge";
import latest from "@/data/latest-report.json";
import { GHOSTCART_URL, REPO_URL } from "@/lib/api";
import { distinctTerms, pct, SEVERITY_TEXT, type Finding, type Report } from "@/lib/report";

const report = latest as unknown as Report;

function ResultCard({ f, note }: { f: Finding; note: string }) {
  return (
    <div className="bg-card border border-line rounded-lg p-4">
      <SeverityBadge severity={f.severity} />
      <div className="font-semibold capitalize mt-2 leading-snug">{f.term}</div>
      <div className={clsx("text-3xl font-bold tnum mt-2", f.severity === "none" ? "text-muted" : SEVERITY_TEXT[f.severity])}>
        {f.severity === "none" ? "0.0%" : pct(f.direction === "discount" ? -f.variance_pct : f.variance_pct, 1)}
      </div>
      <p className="text-sm text-muted mt-1">{note}</p>
    </div>
  );
}

export default function Home() {
  const s = report.summary;
  const terms = distinctTerms([...report.findings, ...report.lawful_dynamic, ...report.clean]);
  const byTerm = (t: string) => terms.find((f) => f.term === t);
  const mobile = byTerm("device type");
  const compound = terms.find((f) => f.effect_type === "interaction" && f.severity !== "none");
  const abandon = byTerm("cart abandonment");
  const referrer = byTerm("referrer source");
  const inventory = byTerm("inventory level");

  return (
    <div>
      {/* Hero */}
      <section className="bg-ink text-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24 grid lg:grid-cols-[1.2fr_1fr] gap-10 items-center">
          <div>
            <p className="text-accent font-semibold text-sm mb-3 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4" aria-hidden /> Open-source pricing compliance audit
            </p>
            <h1 className="font-bold text-4xl sm:text-6xl leading-[1.02] tracking-tight">
              Dynamic pricing is legal.
              <br />
              <span className="text-accent">Personalized pricing</span> has to be disclosed.
            </h1>
            <p className="mt-6 text-white/75 text-lg max-w-xl leading-relaxed">
              From the outside they look identical: the same product, a different price. PriceIntegrity probes a
              pricing engine with thousands of synthetic shoppers and tells the two apart — using nothing but the
              prices, and the statistics to back it up.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/report" className="inline-flex items-center gap-2 bg-accent hover:bg-accentDark text-white font-semibold px-5 py-3 rounded-md transition-colors focus-ring">
                See the audit <ArrowRight className="w-4 h-4" aria-hidden />
              </Link>
              <Link href="/methodology" className="inline-flex items-center gap-2 bg-white/10 hover:bg-white/20 text-white font-semibold px-5 py-3 rounded-md transition-colors focus-ring">
                How it works
              </Link>
            </div>
            <p className="mt-6 text-xs text-white/50 max-w-xl">
              It audits exactly one store: GhostCart, a satirical storefront built for the purpose. It is never pointed at a real retailer.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              [report.probe.session_count?.toLocaleString() ?? "—", "synthetic sessions", "text-white"],
              [String(s.products_tested.length), "products audited", "text-white"],
              [String(s.flagged_finding_count), "personalized-pricing findings", "text-moderate"],
              [String(s.clean_individual_signals.length), "decoy signal correctly cleared", "text-accent"],
            ].map(([n, label, tone]) => (
              <div key={label} className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className={clsx("text-3xl sm:text-4xl font-bold tnum", tone)}>{n}</div>
                <div className="text-xs uppercase tracking-wider text-white/60 mt-1">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* What it found */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 py-14 sm:py-20">
        <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">What it found on GhostCart</h2>
        <p className="text-muted mt-2 max-w-2xl">
          GhostCart&rsquo;s pricing engine has four inputs and one deliberate decoy. The audit sees only prices. Every number below is from the committed report, on all {s.products_tested.length} products, with 95% confidence intervals of about ±0.2 points.
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3 mt-8">
          {mobile && <ResultCard f={mobile} note="Mobile shoppers pay more. Individual-based → flagged." />}
          {compound && <ResultCard f={compound} note="Mobile + abandoned cart together: an extra markup beyond both. Compounding personalization." />}
          {abandon && <ResultCard f={abandon} note="An abandoned cart raises the price. Individual-based → flagged." />}
          {inventory && <ResultCard f={inventory} note="Low stock costs more. Market-based → lawful, surfaced only." />}
          {referrer && <ResultCard f={referrer} note="The decoy. No effect in any combination — and the audit says so." />}
        </div>
        <p className="text-sm mt-6">
          <Link href="/report" className="text-accent font-semibold inline-flex items-center gap-1 hover:underline">Full report, every product, every term <ArrowRight className="w-4 h-4" aria-hidden /></Link>
        </p>
      </section>

      {/* How it works */}
      <section className="bg-card border-y border-line">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-14 sm:py-20">
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">How it works</h2>
          <div className="grid md:grid-cols-3 gap-6 mt-8">
            {[
              [FlaskConical, "Probe", "Every synthetic session gets a random value for every signal — device, cart history, referrer, stock level. That makes it a randomized factorial experiment, so effects are causal, not correlational. Against GhostCart: the full 192-cell design per product."],
              [Sigma, "Regress", "Per product, log(price) is fit on all signals at once plus every pairwise interaction between individual-based signals, by Huber robust regression. Each coefficient is that signal's effect holding the others constant, as an exact percentage with a confidence interval."],
              [ListChecks, "Correct, then classify", "Hundreds of hypotheses means false positives by volume. Every p-value is Benjamini-Hochberg corrected (FDR 5%), and a signal is flagged only if significant and at least 3% in size. Market-based effects are reported as lawful; individual-based ones as findings."],
            ].map(([Icon, title, body]) => {
              const I = Icon as React.ComponentType<{ className?: string }>;
              return (
                <div key={title as string}>
                  <div className="w-10 h-10 rounded-md bg-accent/10 text-accent flex items-center justify-center"><I className="w-5 h-5" /></div>
                  <h3 className="font-semibold text-lg mt-3">{title as string}</h3>
                  <p className="text-sm text-muted mt-2 leading-relaxed">{body as string}</p>
                </div>
              );
            })}
          </div>
          <p className="text-sm mt-8">
            Every one of those claims has a test — including a 300-audit Monte Carlo check that the false-discovery rate really is 5%.{" "}
            <Link href="/methodology" className="text-accent font-semibold hover:underline">Read the methodology</Link>.
          </p>
        </div>
      </section>

      {/* Why */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 py-14 sm:py-20 grid lg:grid-cols-2 gap-10">
        <div>
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">Why the distinction matters now</h2>
          <p className="mt-4 leading-relaxed text-ink/90">
            The FTC&rsquo;s surveillance-pricing inquiry found retailers setting individualized prices from personal data. New York&rsquo;s Algorithmic Pricing Disclosure Act, in effect since November 2025, requires a plain-text disclosure whenever a price was set using a shopper&rsquo;s personal data — with penalties per violation.
          </p>
          <p className="mt-4 leading-relaxed text-ink/90">
            Both draw the same line: <strong>market conditions</strong> (inventory, time, demand) apply to everyone and are conventional dynamic pricing; <strong>individual characteristics</strong> (device, location, history, account) describe the shopper, and pricing on them is personalized. A compliance claim needs a method that can tell which one moved the price — and that can say, defensibly, when nothing did.
          </p>
        </div>
        <div className="bg-card border border-line rounded-lg p-6">
          <p className="text-ghost font-semibold text-sm flex items-center gap-1.5">Built with GhostCart</p>
          <h3 className="font-bold text-xl mt-2">The origin story</h3>
          <p className="mt-3 text-sm leading-relaxed text-ink/90">
            GhostCart is a fake e-commerce store built as a portfolio piece. Building its pricing engine made one thing obvious: charging each customer a different price based on who they appear to be is a few lines of code. So the store got a deliberately personalized pricing side-channel — real visitors never see it — and PriceIntegrity was built to catch it from the outside.
          </p>
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <a href={`${GHOSTCART_URL}/audit`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold text-ghost hover:underline">
              GhostCart&rsquo;s audit page <ExternalLink className="w-3.5 h-3.5" aria-hidden />
            </a>
            <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold text-accent hover:underline">
              Source on GitHub <ExternalLink className="w-3.5 h-3.5" aria-hidden />
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
