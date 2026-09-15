// Display names for GhostCart's audit-enabled products (contract table).
// Prices are NOT here on purpose — the report carries the control price
// the audit observed, and every other price is derived from its estimates.
export const PRODUCT_TITLES: Record<string, string> = {
  "GC-0001": "Wireless noise-cancelling headphones",
  "GC-0002": "Cast-iron skillet, 12\"",
  "GC-0003": "Weighted blanket, 15 lb",
  "GC-0004": "Robot vacuum with mapping",
  "GC-0005": "Trail running shoes",
  "GC-0006": "Merino wool crewneck",
  "GC-0007": "Adjustable dumbbell set, 5–52 lb",
  "GC-0008": "Bouclé accent chair",
  "GC-0009": "Kettle-cooked sea salt chips, 6-pack",
  "GC-0010": "Swiss automatic chronograph",
};

export const productTitle = (id: string) => PRODUCT_TITLES[id] ?? id;
