# GhostCart `/api/persona-price` — contract for PriceIntegrity

Finalized 2026-09-15. This is the endpoint PriceIntegrity's Phase 1 prober is
built against. It is a side channel: nothing on the GhostCart storefront calls
it, and real visitors never see these prices.

## Gating

Both are required. If either fails the route returns **404 with an empty
body**, indistinguishable from a path that doesn't exist.

1. `PERSONA_PRICING_ENABLED=true` (server env var, master switch)
2. Request header `X-PriceIntegrity-Probe: <secret>` equal to
   `PERSONA_PRICING_SECRET` (constant-time comparison)

## Request

```
POST https://ghostcart-ten.vercel.app/api/persona-price
Content-Type: application/json
X-PriceIntegrity-Probe: <secret>

{
  "productId": "GC-0001",
  "signals": {
    "device_type": "mobile",          // "mobile" | "desktop" | "tablet"
    "cart_abandonment": true,         // boolean
    "referrer_source": "search",      // "search" | "direct" | "social" | "email"
    "inventory_level": 22             // integer 0–100000
  }
}
```

`productId` accepts the audit ID (`GC-0001`) or the GhostCart catalog slug
(`wireless-noise-cancelling-headphones-0`). All four signals are required.

## Response

```
200 { "productId": "GC-0001", "basePrice": 89.99, "price": 119.67,
      "appliedRules": ["device_type:mobile", "cart_abandonment:true",
                       "device_type:mobile×cart_abandonment:true", "inventory_level"] }
400 { "error": "invalid signals", "details": ["…one per bad field…"] }
400 { "error": "productId is required" } | { "error": "body must be JSON" }
404 { "error": "productId 'X' is not in the audit-enabled subset" }
404 (empty)  — gating failed
```

`appliedRules` lists only rules that moved the price. `Cache-Control: no-store`.
No jitter: the function is pure and deterministic — same input, same price.

## Rule set (exact)

| Signal | Effect |
|---|---|
| `device_type = mobile` | ×1.10 |
| `cart_abandonment = true` | ×1.06 |
| both of the above (interaction) | an additional ×1.08 on top of both |
| `inventory_level` | ×(1 + adj), adj = (50 − inventory) × 0.002, capped at ±0.10 → +0.2%/unit below 50, −0.2%/unit above, zero at 50 |
| `referrer_source` | **no effect** (decoy) — verified by unit test across every combination of the other signals |
| `device_type = desktop` or `tablet` | no effect |

Order of application is as listed; effects are multiplicative; result is
rounded to cents.

## Audit-enabled subset

`GET /api/persona-price` with the secret header returns the list. Static copy:

| productId | GhostCart slug | basePrice | inventory (control) |
|---|---|---|---|
| GC-0001 | wireless-noise-cancelling-headphones-0 | 89.99 | 40 |
| GC-0002 | cast-iron-skillet-12-17 | 32.50 | 62 |
| GC-0003 | weighted-blanket-15lb-11 | 54.99 | 35 |
| GC-0004 | robot-vacuum-with-mapping-6 | 219.00 | 4 |
| GC-0005 | trail-running-shoes-72 | 79.99 | 58 |
| GC-0006 | merino-wool-crewneck-38 | 78.00 | 27 |
| GC-0007 | adjustable-dumbbell-set-5-52lb-60 | 299.00 | 12 |
| GC-0008 | boucl-accent-chair-24 | 449.00 | 9 |
| GC-0009 | kettle-cooked-sea-salt-chips-6-pack-88 | 18.00 | 80 |
| GC-0010 | swiss-automatic-chronograph-41 | 6800.00 | 1 |

(Slugs are derived from title + catalog index; if a title changes, the slug
changes but the `GC-` ID does not. Use the `GC-` ID.)

## Source

- `src/lib/pricing/signalTypes.ts` — taxonomy + validation
- `src/lib/pricing/personaPricing.ts` — pure rule function (`personaPrice`)
- `src/lib/pricing/auditProducts.ts` — the subset
- `src/lib/pricing/personaPricing.test.ts` — 17 tests (`npm test`)
- `src/app/api/persona-price/route.ts` — the route

## Relationship to `/api/price`

GhostCart also has an open, unauthenticated `/api/price` with a 7-persona /
9-rule engine that powers the public `/pricing-lab` and `/audit` pages. That is
a demo surface and was **not** statistically validated on the PriceIntegrity
side. `/api/persona-price` is the validated 4-signal target; probe this one.
