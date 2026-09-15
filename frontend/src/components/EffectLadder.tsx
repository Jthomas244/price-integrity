"use client";

import { useMemo, useState } from "react";
import { allFindings, CATEGORY_COLOR, median, pct, shortLevel, type Finding, type Report } from "@/lib/report";
import { productTitle } from "@/lib/ghostcart";

/**
 * Every hypothesis the audit tested, on one axis.
 *
 * One row per signal level (or level pair for interactions). The dot is the
 * median estimate across products; the whisker spans the union of the
 * products' 95% confidence intervals. Hue = the legal category (individual-
 * vs market-based); levels with no significant effect are grey. Severity is
 * read from position against the 3 / 8 / 15 % bands, so the chart carries
 * no colour that the badge and table don't also carry.
 */

interface Row {
  key: string;
  term: string;
  level: string;
  first: boolean;            // first row of its term group
  interaction: boolean;
  color: string;
  categoryLabel: string;
  est: number;               // median effect, %
  lo: number;
  hi: number;
  perProduct: { product: string; est: number; lo: number; hi: number; sig: boolean }[];
}

function buildRows(r: Report): Row[] {
  const byTerm = new Map<string, Finding[]>();
  for (const f of allFindings(r)) {
    const g = byTerm.get(f.term);
    if (g) g.push(f); else byTerm.set(f.term, [f]);
  }
  // Order: flagged individual terms (most severe first), then market, then clean.
  const rank = (fs: Finding[]) => {
    const f = fs[0];
    const sev = { high: 0, moderate: 1, low: 2, lawful: 3, none: 4 }[f.severity];
    return sev * 1000 - Math.abs(f.variance_pct);
  };
  const groups = Array.from(byTerm.values()).sort((a, b) => rank(a) - rank(b));

  const rows: Row[] = [];
  for (const fs of groups) {
    const rep = fs[0];
    const levels = Object.keys(rep.variant_breakdown);
    levels.forEach((level, i) => {
      const per = fs
        .filter((f) => level in f.variant_breakdown)
        .map((f) => ({
          product: f.product_id,
          est: f.variant_breakdown[level],
          lo: f.variant_ci?.[level]?.[0] ?? f.variant_breakdown[level],
          hi: f.variant_ci?.[level]?.[1] ?? f.variant_breakdown[level],
          sig: f.significant_variants.includes(level),
        }));
      if (!per.length) return;
      const anySig = per.some((p) => p.sig);
      const color = anySig ? CATEGORY_COLOR[rep.category] : CATEGORY_COLOR.clean;
      rows.push({
        key: `${rep.term}|${level}`,
        term: rep.term,
        level: shortLevel(level),
        first: i === 0,
        interaction: rep.effect_type === "interaction",
        color,
        categoryLabel: anySig ? (rep.category === "individual_based" ? "individual-based" : "market-based") : "no significant effect",
        est: median(per.map((p) => p.est)),
        lo: Math.min(...per.map((p) => p.lo)),
        hi: Math.max(...per.map((p) => p.hi)),
        perProduct: per,
      });
    });
  }
  return rows;
}

const BANDS = [3, 8, 15];
const ROW_H = 22;
const HEAD_H = 24;
const LABEL_W = 210;
const PAD_R = 16;
const TOP = 34;
const BOTTOM = 26;

export default function EffectLadder({ report }: { report: Report }) {
  const rows = useMemo(() => buildRows(report), [report]);
  const [hover, setHover] = useState<Row | null>(null);
  // y of each row's centre; a group header precedes the first row of each term
  const ys = useMemo(() => {
    let y = TOP;
    return rows.map((r) => {
      if (r.first) y += HEAD_H;
      const cy = y + ROW_H / 2;
      y += ROW_H;
      return cy;
    });
  }, [rows]);
  const plotH = (ys.length ? ys[ys.length - 1] + ROW_H / 2 : TOP) - TOP;

  const extent = Math.max(15.5, ...rows.map((r) => Math.max(Math.abs(r.lo), Math.abs(r.hi)))) * 1.08;
  const width = 760;
  const plotW = width - LABEL_W - PAD_R;
  const x = (v: number) => LABEL_W + ((v + extent) / (2 * extent)) * plotW;
  const height = TOP + plotH + BOTTOM;
  const ticks = [-15, -10, -5, 0, 5, 10, 15].filter((t) => Math.abs(t) <= extent);

  return (
    <figure className="bg-card border border-line rounded-lg p-4 sm:p-5">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="font-semibold text-lg">Every effect the audit tested</h3>
          <p className="text-sm text-muted">
            Median estimate across {report.summary.products_tested.length} products, with the span of their 95% confidence intervals. Shaded bands are the severity thresholds.
          </p>
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Legend">
          {[
            ["individual-based", CATEGORY_COLOR.individual_based],
            ["market-based", CATEGORY_COLOR.market_based],
            ["no significant effect", CATEGORY_COLOR.clean],
          ].map(([l, c]) => (
            <li key={l} className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: c }} aria-hidden /> {l}
            </li>
          ))}
        </ul>
      </figcaption>

      <div className="relative mt-4 overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ minWidth: 560 }} role="img" aria-label="Forest plot of estimated price effects by signal level" className="font-sans">
          {/* severity bands */}
          {BANDS.map((b, i) => {
            const next = BANDS[i + 1] ?? extent;
            const alpha = 0.035 + i * 0.03;
            return (
              <g key={b}>
                <rect x={x(b)} y={TOP - 6} width={x(Math.min(next, extent)) - x(b)} height={plotH + 12} fill="#15171F" opacity={alpha} />
                <rect x={x(-Math.min(next, extent))} y={TOP - 6} width={x(-b) - x(-Math.min(next, extent))} height={plotH + 12} fill="#15171F" opacity={alpha} />
                <text x={x(b) + 4} y={TOP - 10} fontSize="10" fill="#6B7280">{["low ≥3%", "moderate ≥8%", "high ≥15%"][i]}</text>
              </g>
            );
          })}
          {/* gridlines + ticks */}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={TOP - 6} y2={TOP + plotH + 6} stroke={t === 0 ? "#15171F" : "#E4E5EA"} strokeWidth={1} />
              <text x={x(t)} y={height - 8} fontSize="11" textAnchor="middle" fill="#6B7280">{t > 0 ? `+${t}%` : `${t}%`}</text>
            </g>
          ))}
          {/* rows */}
          {rows.map((r, i) => {
            const cy = ys[i];
            const isHover = hover?.key === r.key;
            return (
              <g
                key={r.key}
                tabIndex={0}
                onPointerEnter={() => setHover(r)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(r)}
                onBlur={() => setHover(null)}
                className="outline-none"
                aria-label={`${r.term}, ${r.level}: ${pct(r.est)} (${pct(r.lo)} to ${pct(r.hi)}), ${r.categoryLabel}`}
              >
                {r.first && (
                  <>
                    {i > 0 && <line x1={0} x2={width - PAD_R} y1={cy - ROW_H / 2 - HEAD_H} y2={cy - ROW_H / 2 - HEAD_H} stroke="#E4E5EA" strokeWidth={1} />}
                    <text x={8} y={cy - ROW_H / 2 - HEAD_H / 2 + 4} fontSize="12" fontWeight={600} fill="#15171F">
                      <tspan className="capitalize">{r.term}</tspan>
                      {r.interaction && <tspan dx={6} fontSize="10" fontWeight={400} fill="#6B7280">interaction</tspan>}
                    </text>
                  </>
                )}
                {/* hit target: whole row */}
                <rect x={0} y={cy - ROW_H / 2} width={width} height={ROW_H} fill={isHover ? "#15171F" : "transparent"} opacity={isHover ? 0.04 : 1} />
                <text x={LABEL_W - 10} y={cy + 4} fontSize="11" textAnchor="end" fill="#6B7280">{r.level}</text>
                {/* whisker */}
                <line x1={x(r.lo)} x2={x(r.hi)} y1={cy} y2={cy} stroke={r.color} strokeWidth={2} strokeLinecap="round" />
                {/* dot with surface ring */}
                <circle cx={x(r.est)} cy={cy} r={isHover ? 6 : 5} fill={r.color} stroke="#FFFFFF" strokeWidth={2} />
                {/* selective label: only the terms that moved the price */}
                {r.color !== CATEGORY_COLOR.clean && (
                  <text x={x(r.hi) + 8} y={cy + 4} fontSize="11" fill="#15171F" fontWeight={600} className="tnum">{pct(r.est, 1)}</text>
                )}
              </g>
            );
          })}
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 bg-ink text-white text-xs rounded-md shadow-lg px-3 py-2 w-[21rem]"
            style={{ left: `${Math.min(92, (x(Math.max(hover.hi, 0)) / width) * 100 + 1)}%`, top: ys[rows.indexOf(hover)] - ROW_H / 2 - 4, transform: hover.hi > extent * 0.45 ? "translateX(-105%)" : undefined }}
          >
            <p className="font-semibold text-sm tnum">{pct(hover.est)} <span className="font-normal text-white/70">median · {hover.categoryLabel}</span></p>
            <p className="text-white/70 capitalize">{hover.term} — {hover.level}</p>
            <ul className="mt-1.5 space-y-0.5 max-h-48 overflow-auto">
              {hover.perProduct.map((p) => (
                <li key={p.product} className="grid grid-cols-[1fr_auto] gap-3 tnum">
                  <span className="text-white/70 truncate">{p.product} · {productTitle(p.product)}</span>
                  <span className="whitespace-nowrap"><b>{pct(p.est)}</b> <span className="text-white/50">±{((p.hi - p.lo) / 2).toFixed(2)}</span>{p.sig ? " ✓" : ""}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </figure>
  );
}
