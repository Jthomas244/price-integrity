import clsx from "clsx";
import { SEVERITY_CLASS, SEVERITY_LABEL, type Severity } from "@/lib/report";

export default function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span className={clsx("inline-block whitespace-nowrap text-[11px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full", SEVERITY_CLASS[severity], className)}>
      {SEVERITY_LABEL[severity]}
    </span>
  );
}
