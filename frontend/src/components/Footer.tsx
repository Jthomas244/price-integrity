import { GHOSTCART_URL, REPO_URL } from "@/lib/api";

export default function Footer() {
  return (
    <footer className="border-t border-line mt-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-8 text-sm text-muted flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
        <p>
          PriceIntegrity is open source (MIT). It only ever audits{" "}
          <a href={GHOSTCART_URL} className="underline underline-offset-2 hover:text-ink" target="_blank" rel="noopener noreferrer">GhostCart</a>,
          a storefront built for the purpose — never a real retailer.
        </p>
        <p className="flex gap-4">
          <a href={REPO_URL} className="underline underline-offset-2 hover:text-ink" target="_blank" rel="noopener noreferrer">Source</a>
          <a href="/methodology" className="underline underline-offset-2 hover:text-ink">Methodology</a>
        </p>
      </div>
    </footer>
  );
}
