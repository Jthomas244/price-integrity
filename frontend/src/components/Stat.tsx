import clsx from "clsx";

export default function Stat({ value, label, tone = "text-ink", className }: { value: React.ReactNode; label: string; tone?: string; className?: string }) {
  return (
    <div className={clsx("bg-card border border-line rounded-lg px-4 py-3", className)}>
      <div className={clsx("text-2xl sm:text-3xl font-bold tnum leading-tight", tone)}>{value}</div>
      <div className="text-xs uppercase tracking-wider text-muted mt-1">{label}</div>
    </div>
  );
}
