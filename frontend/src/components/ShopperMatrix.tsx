"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";
import { allFindings, pct, type Report } from "@/lib/report";
import { productTitle } from "@/lib/ghostcart";

/**
 * What each kind of shopper pays, according to the audit's own model.
 *
 * Nothing here comes from GhostCart's rules. The control price is the one
 * the audit observed; every other cell multiplies in the estimated effects
 * (main effects × the interaction) for that combination of signals. If the
 * model is right, this grid *is* the store's pricing — reconstructed from
 * prices alone.
 */

const CATEGORICAL_ORDER: Record<string, string[]> = {
  "device type": ["desktop", "mobile", "tablet"],
  "cart abandonment": ["False", "True"],
  "referrer source": ["direct", "search", "social", "email"],
};

interface Model {
  control: number;
  // term -> level -> effect fraction (main effects of categorical signals)
  mains: Record<string, Record<string, number>>;
  // "termA|levelA|termB|levelB" -> effect fraction
  interactions: Record<string, number>;
  // numeric slope in log space per unit, keyed by term, with reference value
  numeric: Record<string, { slope: number; ref: number; min: number; max: number }>;
}

function buildModel(report: Report, productId: string): Model | null {
  const diag = report.diagnostics.find((d) => d.product_id === productId);
  if (!diag?.control_price) return null;
  const model: Model = { control: diag.control_price, mains: {}, interactions: {}, numeric: {} };
  const refs = report.probe.reference_levels ?? {};

  for (const f of allFindings(report).filter((f) => f.product_id === productId)) {
    if (f.effect_type === "interaction") {
      for (const [level, e] of Object.entries(f.variant_breakdown)) {
        const parts = level.split(" × ").map((p) => p.split(" = "));
        if (parts.length !== 2) continue;
        const [[ta, la], [tb, lb]] = parts;
        model.interactions[`${ta}|${la}|${tb}|${lb}`] = e / 100;
        model.interactions[`${tb}|${lb}|${ta}|${la}`] = e / 100;
      }
      continue;
    }
    const levels = Object.entries(f.variant_breakdown);
    const numericLike = levels.length === 2 && levels.every(([k]) => /= -?\d+(\.\d+)?$/.test(k));
    if (numericLike && f.category === "market_based") {
      // Two extremes vs the reference → a log-linear slope per unit.
      const [[k1, e1]] = levels;
      const v1 = Number(k1.split(" = ")[1]);
      const ref = Number(refs[f.signal_type] ?? 50);
      const slope = v1 !== ref ? Math.log(1 + e1 / 100) / (v1 - ref) : 0;
      const vals = levels.map(([k]) => Number(k.split(" = ")[1]));
      model.numeric[f.term] = { slope, ref, min: Math.min(...vals), max: Math.max(...vals) };
      continue;
    }
    model.mains[f.term] = Object.fromEntries(levels.map(([k, e]) => [k.split(" = ")[1], e / 100]));
  }
  return model;
}

function sessionMultiplier(m: Model, choice: Record<string, string>): number {
  let mult = 1;
  const chosen = Object.entries(choice);
  for (const [term, level] of chosen) mult *= 1 + (m.mains[term]?.[level] ?? 0);
  for (let i = 0; i < chosen.length; i++)
    for (let j = i + 1; j < chosen.length; j++) {
      const [ta, la] = chosen[i], [tb, lb] = chosen[j];
      mult *= 1 + (m.interactions[`${ta}|${la}|${tb}|${lb}`] ?? 0);
    }
  return mult;
}

const money = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD" });

export default function ShopperMatrix({ report }: { report: Report }) {
  const products = report.summary.products_tested;
  const [productId, setProductId] = useState(products[0]);
  const [referrer, setReferrer] = useState("direct");
  const model = useMemo(() => buildModel(report, productId), [report, productId]);
  const inv = model?.numeric["inventory level"];
  const [inventory, setInventory] = useState<number>(inv?.ref ?? 50);

  if (!model) return null;

  const devices = CATEGORICAL_ORDER["device type"].filter((d) => d === "desktop" || d in (model.mains["device type"] ?? {}));
  const carts = CATEGORICAL_ORDER["cart abandonment"];
  const invMult = inv ? Math.exp(inv.slope * (inventory - inv.ref)) : 1;
  const maxPersonal = Math.max(
    ...devices.flatMap((d) => carts.map((c) => sessionMultiplier(model, { "device type": d, "cart abandonment": c, "referrer source": referrer }) - 1)),
    0.001,
  );

  return (
    <figure className="bg-card border border-line rounded-lg p-4 sm:p-5">
      <figcaption>
        <h3 className="font-semibold text-lg">What each shopper pays, by the audit&rsquo;s model</h3>
        <p className="text-sm text-muted">
          Reconstructed from the estimates alone — no rules were read. Colour is the personalized markup; the inventory adjustment is lawful and applied to every cell equally.
        </p>
      </figcaption>

      <div className="flex flex-wrap gap-x-6 gap-y-3 items-end mt-4 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">Product</span>
          <select value={productId} onChange={(e) => setProductId(e.target.value)} className="border border-line rounded-md px-2 py-1.5 bg-card focus-ring">
            {products.map((p) => <option key={p} value={p}>{p} · {productTitle(p)}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">Referrer <span className="text-muted/70">(the decoy — watch nothing change)</span></span>
          <select value={referrer} onChange={(e) => setReferrer(e.target.value)} className="border border-line rounded-md px-2 py-1.5 bg-card focus-ring">
            {CATEGORICAL_ORDER["referrer source"].map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        {inv && (
          <label className="flex flex-col gap-1 min-w-[200px]">
            <span className="text-xs text-muted">Stock level: <b className="text-ink tnum">{inventory}</b> <span className="tnum">({pct((invMult - 1) * 100, 1)}, lawful)</span></span>
            <input type="range" min={inv.min} max={inv.max} value={inventory} onChange={(e) => setInventory(Number(e.target.value))} className="accent-[#12907A]" />
          </label>
        )}
      </div>

      <div className="mt-5 overflow-x-auto">
        <div className="grid gap-2 min-w-[420px]" style={{ gridTemplateColumns: `140px repeat(${devices.length}, minmax(0, 1fr))` }}>
          <div />
          {devices.map((d) => <div key={d} className="text-xs font-semibold text-center capitalize text-muted">{d}</div>)}
          {carts.map((c) => (
            <Row key={c} label={c === "True" ? "Abandoned a cart" : "No cart history"}>
              {devices.map((d) => {
                const personal = sessionMultiplier(model, { "device type": d, "cart abandonment": c, "referrer source": referrer }) - 1;
                const price = model.control * (1 + personal) * invMult;
                const t = personal / maxPersonal; // 0..1 for the sequential fill
                const isControl = personal < 0.0005 && personal > -0.0005;
                return (
                  <div
                    key={d}
                    className={clsx("rounded-md px-3 py-3 text-center border", isControl ? "border-line bg-paper" : "border-transparent")}
                    style={isControl ? undefined : { background: `rgba(180, 35, 24, ${0.12 + 0.68 * t})`, color: t > 0.55 ? "#fff" : "#15171F" }}
                    title={`${d}, ${c === "True" ? "abandoned cart" : "no cart history"}: ${money(price)} (${pct(personal * 100)} personalized)`}
                  >
                    <div className="text-xl font-bold tnum">{money(price)}</div>
                    <div className={clsx("text-xs mt-0.5 tnum", isControl ? "text-muted" : t > 0.55 ? "text-white/80" : "text-ink/70")}>
                      {isControl ? "control" : pct(personal * 100, 1)}
                    </div>
                  </div>
                );
              })}
            </Row>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted mt-3">
        Control price {money(model.control)} is the audit&rsquo;s observed price at the reference session. A cell&rsquo;s markup is the product of its main effects and any interaction between them; e.g. mobile × abandoned = (1 + mobile) × (1 + abandoned) × (1 + interaction) − 1.
      </p>
    </figure>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <div className="text-xs font-semibold text-muted self-center">{label}</div>
      {children}
    </>
  );
}

