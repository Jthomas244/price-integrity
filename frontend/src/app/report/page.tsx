import type { Metadata } from "next";
import ReportClient from "@/components/ReportClient";
import latest from "@/data/latest-report.json";
import type { Report } from "@/lib/report";

export const metadata: Metadata = {
  title: "Audit report — GhostCart",
  description: "The full PriceIntegrity audit of GhostCart's pricing engine: every finding with effect size, confidence interval and FDR-corrected p-value.",
};

export default function ReportPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 sm:px-6 py-10 sm:py-14">
      <p className="text-accent font-semibold text-sm mb-2">Audit report</p>
      <h1 className="text-3xl sm:text-4xl font-bold tracking-tight mb-6">GhostCart pricing engine</h1>
      <ReportClient initial={latest as unknown as Report} />
    </div>
  );
}
