"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { PageHeader } from "@/components/Shell";
import { Badge, ErrorState, KpiCard, Loading, Panel, SectionTitle } from "@/components/ui";
import { endpoints } from "@/lib/api";
import { inr } from "@/lib/format";
import { useApi } from "@/lib/useApi";

// react-globe.gl is WebGL/three — client-only. next/dynamic does not forward
// refs, so wrap it and pass the ref through a regular prop.
const Globe = dynamic(
  async () => {
    const mod = await import("react-globe.gl");
    const GlobeGl = mod.default;
    return function GlobeWithRef({ globeRef, ...props }: any) {
      return <GlobeGl ref={globeRef} {...props} />;
    };
  },
  { ssr: false, loading: () => <Loading label="Spinning up the globe…" /> },
);

type Country = {
  iso: string;
  name: string;
  lat: number;
  lng: number;
  lots: number;
  units: number;
  median_price_usd: number;
  price_index: number;
  top_models: { model: string; units: number }[];
  sources: string[];
};

type Arc = {
  from_iso: string;
  from_name: string;
  start_lat: number;
  start_lng: number;
  end_lat: number;
  end_lng: number;
  model: string;
  spread_pct: number;
  landed_cost: number;
  india_fair_value: number;
};

// Price index -> color: cheap markets glow green (buy), expensive glow red (sell).
function indexColor(idx: number): string {
  if (idx <= 0.94) return "#34d399";
  if (idx <= 0.99) return "#a3e635";
  if (idx <= 1.04) return "#facc15";
  if (idx <= 1.12) return "#fb923c";
  return "#f87171";
}

export default function GlobePage() {
  const globe = useApi<any>(endpoints.b2bGlobe);
  const globeRef = useRef<any>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 640 });
  const [selected, setSelected] = useState<Country | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() =>
      setSize({ w: el.clientWidth, h: Math.max(560, Math.min(760, el.clientWidth * 0.62)) }),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Gentle auto-rotate, opening on the India <-> Gulf <-> Far East corridor.
  function onGlobeReady() {
    const g = globeRef.current;
    if (!g) return;
    try {
      g.pointOfView({ lat: 22, lng: 74, altitude: 2.1 }, 0);
      g.controls().autoRotate = true;
      g.controls().autoRotateSpeed = 0.55;
    } catch {}
  }

  const countries: Country[] = globe.data?.countries || [];
  const arcs: Arc[] = globe.data?.arcs || [];
  const maxUnits = useMemo(
    () => Math.max(1, ...countries.map((c) => c.units)),
    [countries],
  );

  if (globe.error) return <ErrorState message={globe.error} />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Global Price Globe"
        subtitle="Live wholesale market by country — scraped from the gsmExchange trading floor & IndiaMART. Bars = supply on offer, color = price level, arcs = sourcing opportunities into India."
        badge={<Badge tone="sky">{countries.length} markets live</Badge>}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard label="Markets on the map" value={countries.length} accent="sky" />
        <KpiCard
          label="Units on offer"
          value={(globe.data?.total_units ?? 0).toLocaleString("en-IN")}
          sub={<span>{(globe.data?.total_lots ?? 0).toLocaleString("en-IN")} wholesale lots</span>}
          accent="violet"
        />
        <KpiCard
          label="Cheapest market"
          value={
            countries.length
              ? [...countries].sort((a, b) => a.price_index - b.price_index)[0].name
              : "—"
          }
          sub={<span>best sourcing origin</span>}
          accent="maple"
        />
        <KpiCard
          label="Import arcs to India"
          value={arcs.length}
          sub={<span>profitable after duty + freight</span>}
          accent="amber"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        {/* The globe */}
        <Panel className="overflow-hidden p-0">
          <div ref={wrapRef} className="relative">
            {globe.loading || !globe.data ? (
              <div className="flex h-[560px] items-center justify-center">
                <Loading label="Loading world market…" />
              </div>
            ) : (
              <Globe
                globeRef={globeRef}
                onGlobeReady={onGlobeReady}
                width={size.w}
                height={size.h}
                backgroundColor="rgba(0,0,0,0)"
                globeImageUrl="/globe/earth-night.jpg"
                atmosphereColor="#38bdf8"
                atmosphereAltitude={0.18}
                pointsData={countries}
                pointLat={(d: any) => d.lat}
                pointLng={(d: any) => d.lng}
                pointAltitude={(d: any) => 0.02 + 0.5 * Math.sqrt(d.units / maxUnits)}
                pointRadius={0.55}
                pointColor={(d: any) => indexColor(d.price_index)}
                pointLabel={(d: any) => `
                  <div style="background:#0b1220ee;border:1px solid #1e293b;border-radius:10px;padding:10px 12px;font-size:12px;color:#e2e8f0;max-width:250px">
                    <div style="font-weight:600;font-size:13px">${d.name}</div>
                    <div style="color:#94a3b8;margin:2px 0 6px">${d.lots} lots · ${d.units.toLocaleString()} units on offer</div>
                    <div>Median wholesale: <b>$${d.median_price_usd.toLocaleString()}</b></div>
                    <div>Price level vs world: <b style="color:${indexColor(d.price_index)}">${((d.price_index - 1) * 100).toFixed(1)}%</b></div>
                    <div style="color:#94a3b8;margin-top:6px">${(d.top_models || []).map((m: any) => `${m.model} (${m.units})`).join(" · ")}</div>
                  </div>`}
                onPointClick={(d: any) => setSelected(d as Country)}
                arcsData={arcs}
                arcStartLat={(d: any) => d.start_lat}
                arcStartLng={(d: any) => d.start_lng}
                arcEndLat={(d: any) => d.end_lat}
                arcEndLng={(d: any) => d.end_lng}
                arcColor={() => ["#34d39988", "#38bdf8ee"]}
                arcAltitude={0.28}
                arcStroke={0.45}
                arcDashLength={0.45}
                arcDashGap={0.25}
                arcDashAnimateTime={2600}
                arcLabel={(d: any) => `
                  <div style="background:#0b1220ee;border:1px solid #1e293b;border-radius:10px;padding:10px 12px;font-size:12px;color:#e2e8f0">
                    <div style="font-weight:600">${d.from_name} → India</div>
                    <div style="margin-top:4px">${d.model}: buy + duty + freight = <b>₹${d.landed_cost.toLocaleString("en-IN")}</b></div>
                    <div>India fair value ₹${d.india_fair_value.toLocaleString("en-IN")} · spread <b style="color:#34d399">+${(d.spread_pct * 100).toFixed(1)}%</b></div>
                  </div>`}
                ringsData={countries.slice(0, 4)}
                ringLat={(d: any) => d.lat}
                ringLng={(d: any) => d.lng}
                ringMaxRadius={4.5}
                ringPropagationSpeed={1.4}
                ringRepeatPeriod={1800}
                ringColor={() => (t: number) => `rgba(56,189,248,${1 - t})`}
              />
            )}
            {/* Legend */}
            <div className="pointer-events-none absolute bottom-3 left-3 rounded-lg border border-panel-line bg-[#0b1220cc] px-3 py-2 text-[11px] text-slate-400 backdrop-blur">
              <div className="mb-1 font-medium text-slate-300">Price level vs world median</div>
              <div className="flex items-center gap-2">
                {[
                  ["#34d399", "cheap"],
                  ["#a3e635", ""],
                  ["#facc15", "par"],
                  ["#fb923c", ""],
                  ["#f87171", "rich"],
                ].map(([c, l], i) => (
                  <span key={i} className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full" style={{ background: c as string }} />
                    {l}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </Panel>

        {/* Market table / detail */}
        <div className="space-y-4">
          <Panel>
            <SectionTitle
              title={selected ? selected.name : "Markets by supply"}
              subtitle={
                selected
                  ? `${selected.lots} lots · ${selected.units.toLocaleString("en-IN")} units`
                  : "click a bar on the globe for detail"
              }
            />
            {selected ? (
              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-400">Median wholesale</span>
                  <span className="font-semibold text-white">
                    ${selected.median_price_usd.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Price level vs world</span>
                  <span className="font-semibold" style={{ color: indexColor(selected.price_index) }}>
                    {((selected.price_index - 1) * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <div className="mb-1 text-slate-400">Most-traded devices</div>
                  {(selected.top_models || []).map((m) => (
                    <div key={m.model} className="flex justify-between text-slate-300">
                      <span>{m.model}</span>
                      <span className="text-slate-500">{m.units.toLocaleString("en-IN")} u</span>
                    </div>
                  ))}
                </div>
                <div className="text-xs text-slate-500">
                  Sources: {selected.sources.join(", ")}
                </div>
                <button
                  onClick={() => setSelected(null)}
                  className="mt-1 rounded-lg border border-panel-line px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200"
                >
                  ← All markets
                </button>
              </div>
            ) : (
              <div className="max-h-[300px] space-y-1 overflow-y-auto pr-1">
                {countries.map((c) => (
                  <button
                    key={c.iso}
                    onClick={() => setSelected(c)}
                    className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm hover:bg-white/[0.04]"
                  >
                    <span className="flex items-center gap-2 text-slate-300">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ background: indexColor(c.price_index) }}
                      />
                      {c.name}
                    </span>
                    <span className="text-xs text-slate-500">
                      {c.units.toLocaleString("en-IN")} u · ${c.median_price_usd.toLocaleString()}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Panel>

          <Panel>
            <SectionTitle
              title="Sourcing arcs → India"
              subtitle="landed cost (incl. duty + freight) vs India retail fair value"
            />
            <div className="space-y-2">
              {arcs.slice(0, 6).map((a, i) => (
                <div key={i} className="rounded-lg border border-panel-line bg-white/[0.02] px-3 py-2 text-xs">
                  <div className="flex justify-between text-slate-300">
                    <span className="font-medium">
                      {a.from_name} → 🇮🇳
                    </span>
                    <span className="font-semibold text-maple-400">
                      +{(a.spread_pct * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="mt-0.5 flex justify-between text-slate-500">
                    <span>{a.model}</span>
                    <span>
                      landed {inr(a.landed_cost)} → sells {inr(a.india_fair_value)}
                    </span>
                  </div>
                </div>
              ))}
              {!arcs.length && (
                <div className="text-xs text-slate-500">
                  No import spreads clear the 5% threshold right now.
                </div>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
