"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, useState } from "react";
import { apiGet, apiPost, endpoints } from "@/lib/api";

const NAV = [
  { href: "/", label: "Executive", icon: "◆" },
  { href: "/competitors", label: "Competitors", icon: "▤" },
  { href: "/devices", label: "Device Pricing", icon: "▦" },
  { href: "/maple", label: "Maple vs Market", icon: "⚖" },
  { href: "/b2b", label: "B2B Wholesale", icon: "⊞" },
  { href: "/globe", label: "Price Globe", icon: "◍" },
  { href: "/copilot", label: "Copilot", icon: "✦" },
  { href: "/dubai", label: "Dubai Expansion", icon: "⇄" },
  { href: "/inventory", label: "Inventory", icon: "▣" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [refreshing, setRefreshing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [dataSource, setDataSource] = useState<string | null>(null);

  useEffect(() => {
    apiGet(endpoints.config)
      .then((c: any) => setDataSource(c?.data_source ?? null))
      .catch(() => setDataSource(null));
  }, []);

  const isReal = dataSource === "real";

  async function refresh() {
    setRefreshing(true);
    setNote(null);
    try {
      const r = await apiPost(endpoints.refresh);
      setNote(`Re-scraped ${r.total_listings} listings`);
      // hard reload so all dashboards pull fresh data
      setTimeout(() => window.location.reload(), 400);
    } catch (e: any) {
      setNote(e.message || "Refresh failed");
      setRefreshing(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-panel-line bg-panel/60 px-4 py-6 backdrop-blur md:flex">
        <div className="mb-8 flex items-center gap-2.5 px-1">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-maple-400 to-maple-700 text-lg shadow-glow">
            🍁
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight text-white">Maple Store</div>
            <div className="text-[10px] uppercase tracking-widest text-maple-400">
              AI Department
            </div>
          </div>
        </div>

        <nav className="flex flex-col gap-1">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-maple-500/10 text-maple-300 shadow-[inset_0_0_0_1px_rgba(34,197,94,0.2)]"
                    : "text-slate-400 hover:bg-white/[0.03] hover:text-slate-200"
                }`}
              >
                <span className="w-4 text-center text-xs opacity-70">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-2 px-1 pt-6 text-[11px] text-slate-600">
          <div className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 animate-pulse rounded-full ${isReal ? "bg-sky-400" : "bg-maple-500"}`}
            />
            <span className="text-slate-500">
              {dataSource === null ? "Connecting…" : isReal ? "Live scraped data" : "Mock market"}
            </span>
          </div>
          <div>iPhone 13–17 · India + Dubai</div>
          <div className="text-slate-700">Demo pilot v1.0</div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-panel-line bg-[#070b0f]/80 px-5 py-3 backdrop-blur md:px-8">
          <div className="flex items-center gap-3 md:hidden">
            <span className="text-base">🍁</span>
            <span className="text-sm font-semibold text-white">Maple AI</span>
          </div>
          <div className="hidden text-xs text-slate-500 md:block">
            Continuous pre-owned iPhone market intelligence
          </div>
          <div className="flex items-center gap-3">
            {dataSource && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium ${
                  isReal
                    ? "border-sky-500/40 bg-sky-500/10 text-sky-300"
                    : "border-slate-600/40 bg-slate-500/10 text-slate-300"
                }`}
                title={isReal ? "Data scraped live from maplestore.in + market" : "Deterministic synthetic market"}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${isReal ? "bg-sky-400" : "bg-slate-400"}`} />
                {isReal ? "REAL DATA" : "MOCK DATA"}
              </span>
            )}
            {note && <span className="text-xs text-maple-400">{note}</span>}
            <button
              onClick={refresh}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-lg border border-maple-600/40 bg-maple-500/10 px-3 py-1.5 text-xs font-medium text-maple-300 transition hover:bg-maple-500/20 disabled:opacity-50"
            >
              <span className={refreshing ? "animate-spin" : ""}>⟳</span>
              {refreshing ? "Scraping…" : "Refresh market"}
            </button>
          </div>
        </header>

        {/* Mobile nav */}
        <nav className="flex gap-1 overflow-x-auto border-b border-panel-line px-3 py-2 md:hidden">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs ${
                  active ? "bg-maple-500/10 text-maple-300" : "text-slate-400"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8 md:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  badge,
}: {
  title: string;
  subtitle?: string;
  badge?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white md:text-[28px]">
          {title}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {badge}
    </div>
  );
}
