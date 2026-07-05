import React from "react";
import { signedPct, trendClass } from "@/lib/format";

export function Panel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={`panel p-5 ${className}`}>{children}</div>;
}

export function SectionTitle({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <h3 className="text-[13px] font-semibold uppercase tracking-wider text-slate-400">
          {title}
        </h3>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function KpiCard({
  label,
  value,
  sub,
  accent = "maple",
  delta,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  accent?: "maple" | "amber" | "sky" | "rose" | "slate" | "violet";
  delta?: number;
}) {
  const ring: Record<string, string> = {
    maple: "before:bg-maple-500",
    amber: "before:bg-amber-500",
    sky: "before:bg-sky-500",
    rose: "before:bg-rose-500",
    slate: "before:bg-slate-500",
    violet: "before:bg-violet-500",
  };
  return (
    <div
      className={`panel relative overflow-hidden p-4 before:absolute before:left-0 before:top-0 before:h-full before:w-[3px] ${ring[accent]}`}
    >
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="mt-1.5 stat-num text-2xl font-semibold text-white">{value}</div>
      <div className="mt-1 flex items-center gap-2 text-xs text-slate-400">
        {sub}
        {delta !== undefined && (
          <span className={trendClass(delta)}>{signedPct(delta)}</span>
        )}
      </div>
    </div>
  );
}

export function Delta({ value, suffix = "%" }: { value: number; suffix?: string }) {
  const up = value > 0;
  const down = value < 0;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ${
        up
          ? "bg-maple-500/10 text-maple-400"
          : down
          ? "bg-rose-500/10 text-rose-400"
          : "bg-slate-500/10 text-slate-400"
      }`}
    >
      {up ? "▲" : down ? "▼" : "■"} {Math.abs(value).toFixed(suffix === "%" ? 2 : 0)}
      {suffix}
    </span>
  );
}

export function Badge({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "slate" | "maple" | "amber" | "rose" | "sky" | "violet";
}) {
  const tones: Record<string, string> = {
    slate: "border-slate-600/40 bg-slate-500/10 text-slate-300",
    maple: "border-maple-600/40 bg-maple-500/10 text-maple-300",
    amber: "border-amber-500/40 bg-amber-500/10 text-amber-400",
    rose: "border-rose-500/40 bg-rose-500/10 text-rose-300",
    sky: "border-sky-500/40 bg-sky-500/10 text-sky-300",
    violet: "border-violet-500/50 bg-violet-500/15 text-violet-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const w = Math.max(2, Math.min(100, (value / max) * 100));
  const tone = value >= 66 ? "bg-maple-500" : value >= 33 ? "bg-amber-500" : "bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-panel-line">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${w}%` }} />
      </div>
      <span className="stat-num text-xs text-slate-400">{value.toFixed(0)}</span>
    </div>
  );
}

export function ConfidenceDot({ value }: { value: number }) {
  const tone = value >= 0.85 ? "bg-maple-500" : value >= 0.6 ? "bg-amber-500" : "bg-rose-500";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${tone}`} />
      <span className="stat-num text-xs text-slate-400">{(value * 100).toFixed(0)}%</span>
    </span>
  );
}

export function Loading({ label = "Loading market data…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 p-8 text-sm text-slate-400">
      <span className="h-3 w-3 animate-pulse rounded-full bg-maple-500" />
      {label}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <Panel className="border-rose-500/30">
      <div className="text-sm text-rose-300">⚠ {message}</div>
      <div className="mt-2 text-xs text-slate-500">
        Is the backend running at <code className="text-slate-300">{process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"}</code>?
      </div>
    </Panel>
  );
}
