import Link from "next/link";
import { ShieldCheck, ExternalLink } from "lucide-react";
import { GHOSTCART_URL, REPO_URL } from "@/lib/api";

const NAV = [
  { href: "/report", label: "Audit report" },
  { href: "/methodology", label: "Methodology" },
];

export default function Header() {
  return (
    <header className="border-b border-line bg-card/80 backdrop-blur sticky top-0 z-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 h-14 flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2 font-bold tracking-tight focus-ring rounded">
          <ShieldCheck className="w-5 h-5 text-accent" aria-hidden />
          PriceIntegrity
        </Link>
        <nav className="flex items-center gap-4 text-sm ml-auto">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className="hover:text-accent focus-ring rounded">
              {n.label}
            </Link>
          ))}
          <a href={GHOSTCART_URL} target="_blank" rel="noopener noreferrer" className="hidden sm:inline-flex items-center gap-1 hover:text-ghost focus-ring rounded">
            GhostCart <ExternalLink className="w-3.5 h-3.5" aria-hidden />
          </a>
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="hidden sm:inline-flex items-center gap-1 hover:text-accent focus-ring rounded">
            GitHub <ExternalLink className="w-3.5 h-3.5" aria-hidden />
          </a>
        </nav>
      </div>
    </header>
  );
}
