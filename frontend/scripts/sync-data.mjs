// Copies the latest audit report and the methodology doc from the repo
// into src/data so the frontend can import them statically. Runs before
// `dev` and `build`; the copies are committed too, so a Vercel build with
// only ./frontend checked out still works.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const out = join(here, "..", "src", "data");
mkdirSync(out, { recursive: true });

const files = [
  ["reports/ghostcart-latest.json", "latest-report.json"],
  ["docs/methodology.md", "methodology.md"],
];
for (const [src, dst] of files) {
  const from = join(repo, src);
  if (!existsSync(from)) {
    console.warn(`sync-data: ${src} not found, keeping committed copy`);
    continue;
  }
  copyFileSync(from, join(out, dst));
  console.log(`sync-data: ${src} -> src/data/${dst}`);
}
