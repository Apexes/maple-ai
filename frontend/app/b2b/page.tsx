"use client";

import { useMemo, useState } from "react";
import { PageHeader } from "@/components/Shell";
import { HBarChart } from "@/components/charts";
import { Badge, ConfidenceDot, ErrorState, KpiCard, Loading, Panel, SectionTitle } from "@/components/ui";
import { apiPost, endpoints } from "@/lib/api";
import { inr, inrCompact, pct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const SOURCE_LABEL: Record<string, string> = {
  gsmexchange: "gsmExchange",
  indiamart: "IndiaMART",
  cashify_supersale: "Cashify SuperSale",
};
const REGION_LABEL: Record<string, string> = {
  IN: "🇮🇳 India",
  AE: "🇦🇪 UAE",
  US: "🇺🇸 USA",
  GB: "🇬🇧 UK",
  SG: "🇸🇬 Singapore",
  HK: "🇭🇰 Hong Kong",
};
const REGION_COLOR = "#38bdf8";
const CONDITIONS = ["Almost New", "Superb", "Good", "Fair"];

export default function B2BPage() {
  const overview = useApi<any>(endpoints.b2b);
  const global = useApi<any>(endpoints.b2bGlobal);
  const spread = useApi<any>(endpoints.b2bSpread + "?top_n=12");

  const devices: any[] = overview.data?.devices || [];
  const [sku, setSku] = useState<string | null>(null);
  const selectedSku = sku ?? devices[0]?.sku ?? null;
  const ladder = useApi<any>(selectedSku ? endpoints.b2bLadder(selectedSku) : null);
  const costing = useApi<any>(selectedSku ? endpoints.b2bCosting(selectedSku) + "?quantity=25" : null);

  if (overview.error) return <ErrorState message={overview.error} />;
  if (overview.loading || !overview.data) return <Loading label="Loading B2B wholesale market…" />;

  const ov = overview.data;

  return (
    <div className="space-y-4">
      <PageHeader
        title="B2B Wholesale"
        subtitle="The trade market — bulk lots, volume pricing & the global price map, separate from the B2C benchmark"
        badge={<Badge tone="violet">{ov.sources.map((s: string) => SOURCE_LABEL[s] || s).join(" · ")}</Badge>}
      />

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard label="Devices in trade" value={ov.device_count} sub={<span>across {ov.sources.length} sources</span>} accent="violet" />
        <KpiCard label="Active lots" value={ov.total_lots.toLocaleString("en-IN")} accent="sky" />
        <KpiCard label="Units available" value={ov.total_units.toLocaleString("en-IN")} sub={<span>wholesale supply</span>} accent="maple" />
        <KpiCard
          label="Global markets"
          value={global.data?.regions?.length ?? "—"}
          sub={<span>live price map</span>}
          accent="amber"
        />
      </div>

      {/* Global price map */}
      <Panel>
        <SectionTitle
          title="Global Price Map"
          subtitle="gsmExchange world view · median wholesale price by market (INR-normalized)"
        />
        {global.loading || !global.data ? (
          <Loading label="Loading global map…" />
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr,1.1fr]">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {global.data.regions.map((r: any) => (
                <div key={r.region} className="rounded-lg border border-panel-line bg-panel-soft p-3">
                  <div className="text-sm font-medium text-slate-200">{REGION_LABEL[r.region] || r.region}</div>
                  <div className="mt-1 stat-num text-lg font-semibold text-white">{inr(r.median_price_inr)}</div>
                  <div className="mt-0.5 text-[11px] text-slate-500">
                    {r.units.toLocaleString("en-IN")} units · {r.lots} lots
                  </div>
                </div>
              ))}
            </div>
            <div>
              <HBarChart
                data={global.data.regions.map((r: any) => ({
                  label: (REGION_LABEL[r.region] || r.region).replace(/^[^ ]+ /, ""),
                  value: r.median_price_inr,
                  color: REGION_COLOR,
                }))}
                unit=" ₹"
                height={Math.max(180, global.data.regions.length * 36)}
              />
            </div>
          </div>
        )}
        {global.data?.matrix?.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full whitespace-nowrap">
              <thead>
                <tr className="border-b border-panel-line">
                  <th className="th">Device</th>
                  {global.data.region_keys.map((rk: string) => (
                    <th key={rk} className="th text-right">{REGION_LABEL[rk]?.replace(/^[^ ]+ /, "") || rk}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {global.data.matrix.map((row: any) => (
                  <tr key={row.sku} className="row-hover border-b border-panel-line/50">
                    <td className="td font-medium text-slate-200">{row.model}</td>
                    {global.data.region_keys.map((rk: string) => (
                      <td key={rk} className="td stat-num text-right text-slate-300">
                        {row.by_region[rk] != null ? inr(row.by_region[rk]) : "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* B2C ↔ B2B spread */}
      <Panel>
        <SectionTitle
          title="B2C ↔ B2B Spread"
          subtitle="Where the trade clears furthest below retail fair value — the cross-segment opportunity"
        />
        {spread.loading || !spread.data ? (
          <Loading label="Loading spread…" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-panel-line">
                  <th className="th">Device</th>
                  <th className="th text-right">Retail Fair</th>
                  <th className="th text-right">B2B Market</th>
                  <th className="th text-right">Discount</th>
                  <th className="th text-right">Gross Spread</th>
                  <th className="th text-right">Units</th>
                </tr>
              </thead>
              <tbody>
                {spread.data.opportunities.map((o: any) => (
                  <tr key={o.sku} className="row-hover border-b border-panel-line/50">
                    <td className="td font-medium text-slate-200">{o.model}</td>
                    <td className="td stat-num text-right text-slate-400">{inr(o.retail_fair_value)}</td>
                    <td className="td stat-num text-right text-white">{inr(o.b2b_market_value)}</td>
                    <td className="td stat-num text-right text-maple-400">−{pct(o.wholesale_discount_pct)}</td>
                    <td className="td stat-num text-right text-violet-300">{inr(o.gross_spread)}</td>
                    <td className="td stat-num text-right text-slate-400">{o.units_available?.toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* Device picker + volume ladder + costing */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px,1fr]">
        <Panel className="p-3">
          <SectionTitle title="Devices in Trade" />
          <div className="max-h-[520px] space-y-1 overflow-y-auto pr-1">
            {devices.map((d) => {
              const active = d.sku === selectedSku;
              return (
                <button
                  key={d.sku}
                  onClick={() => setSku(d.sku)}
                  className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                    active ? "border-violet-500/50 bg-violet-500/10" : "border-transparent hover:bg-white/[0.03]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`text-sm font-medium ${active ? "text-violet-200" : "text-slate-200"}`}>{d.model}</span>
                    <span className="text-[11px] text-slate-500">{d.storage}</span>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between text-[11px] text-slate-500">
                    <span className="stat-num">{inr(d.b2b_market_value)}</span>
                    <span>{d.wholesale_discount_pct != null ? `−${d.wholesale_discount_pct}% vs retail` : `${d.lots} lots`}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </Panel>

        <div className="min-w-0 space-y-4">
          {/* Volume ladder */}
          <Panel>
            <SectionTitle
              title="Volume Price Ladder"
              subtitle={ladder.data ? `${ladder.data.model} · Superb · per-unit wholesale falls as the lot grows` : "Per-unit wholesale by lot size"}
            />
            {ladder.loading || !ladder.data ? (
              <Loading label="Loading ladder…" />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-panel-line">
                      <th className="th text-right">Lot size</th>
                      <th className="th text-right">Volume discount</th>
                      <th className="th text-right">Unit price</th>
                      <th className="th text-right">Recommended buy</th>
                      <th className="th text-right">Unit margin</th>
                      <th className="th text-right">Lot total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ladder.data.ladder.map((t: any) => (
                      <tr key={t.quantity} className="row-hover border-b border-panel-line/50">
                        <td className="td stat-num text-right font-medium text-slate-200">{t.quantity}+</td>
                        <td className="td stat-num text-right text-maple-400">−{pct(t.volume_discount_pct)}</td>
                        <td className="td stat-num text-right text-white">{inr(t.wholesale_unit)}</td>
                        <td className="td stat-num text-right text-amber-300">{inr(t.recommended_buy)}</td>
                        <td className="td stat-num text-right text-sky-300">{inr(t.expected_gross_margin)}</td>
                        <td className="td stat-num text-right text-slate-300">{inrCompact(t.lot_total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          {/* Costing: retail vs B2B waterfall */}
          {costing.data && (
            <Panel>
              <SectionTitle
                title="Unit Economics — Retail vs B2B"
                subtitle="Full cost stack to true net margin (after QC, fees & overhead) · B2B at lot of 25"
              />
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-panel-line">
                      <th className="th">Line</th>
                      <th className="th text-right">Retail (1 unit)</th>
                      <th className="th text-right">B2B (per unit)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["Sell price", "sell_price", "white"],
                      ["− Acquisition", "acquisition_cost", "slate"],
                      ["− Refurb parts", "refurb_parts", "slate"],
                      ["− Refurb labour", "refurb_labour", "slate"],
                      ["− Logistics in", "logistics_inbound", "slate"],
                      ["− Logistics out", "logistics_outbound", "slate"],
                      ["− QC / grading", "qc_grading", "slate"],
                      ["− Warranty reserve", "warranty_reserve", "slate"],
                      ["− Platform fee", "platform_fee", "slate"],
                      ["− Payment fee", "payment_fee", "slate"],
                      ["− Overhead", "overhead_alloc", "slate"],
                    ].map(([label, key, tone]) => (
                      <tr key={key as string} className="row-hover border-b border-panel-line/50">
                        <td className="td text-slate-300">{label}</td>
                        <td className={`td stat-num text-right ${tone === "white" ? "text-white" : "text-slate-400"}`}>
                          {inr(costing.data.retail[key as string])}
                        </td>
                        <td className={`td stat-num text-right ${tone === "white" ? "text-white" : "text-slate-400"}`}>
                          {inr(costing.data.b2b[key as string])}
                        </td>
                      </tr>
                    ))}
                    <tr className="border-b border-panel-line/50 bg-white/[0.02]">
                      <td className="td font-medium text-slate-200">Net margin</td>
                      <td className="td stat-num text-right font-semibold text-maple-300">
                        {inr(costing.data.retail.net_margin)} <span className="text-[11px] text-slate-500">({pct(costing.data.retail.net_margin_pct * 100)})</span>
                      </td>
                      <td className="td stat-num text-right font-semibold text-violet-300">
                        {inr(costing.data.b2b.net_margin)} <span className="text-[11px] text-slate-500">({pct(costing.data.b2b.net_margin_pct * 100)})</span>
                      </td>
                    </tr>
                    <tr>
                      <td className="td text-slate-500">Break-even sell</td>
                      <td className="td stat-num text-right text-slate-500">{inr(costing.data.retail.breakeven_sell)}</td>
                      <td className="td stat-num text-right text-slate-500">{inr(costing.data.b2b.breakeven_sell)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </div>
      </div>

      {/* Bulk-lot quote builder */}
      <QuoteBuilder devices={devices} />
    </div>
  );
}

function QuoteBuilder({ devices }: { devices: any[] }) {
  const [rows, setRows] = useState<{ sku: string; quantity: number; condition: string }[]>([]);
  const [pickSku, setPickSku] = useState<string>("");
  const [qty, setQty] = useState<number>(25);
  const [condition, setCondition] = useState<string>("Superb");
  const [quote, setQuote] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const modelOf = useMemo(() => {
    const m: Record<string, string> = {};
    for (const d of devices) m[d.sku] = `${d.model} ${d.storage}`;
    return m;
  }, [devices]);

  function addRow() {
    const sku = pickSku || devices[0]?.sku;
    if (!sku) return;
    setRows((r) => [...r, { sku, quantity: qty || 1, condition }]);
    setQuote(null);
  }
  function removeRow(i: number) {
    setRows((r) => r.filter((_, idx) => idx !== i));
    setQuote(null);
  }
  async function getQuote() {
    if (rows.length === 0) return;
    setBusy(true);
    try {
      const res = await apiPost(endpoints.b2bQuote, { items: rows });
      setQuote(res);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel>
      <SectionTitle
        title="Bulk-Lot Quote Builder"
        subtitle="Build a mixed lot — devices × grades × quantities — for an instant wholesale quote"
      />
      <div className="flex flex-wrap items-end gap-2">
        <select
          value={pickSku || devices[0]?.sku || ""}
          onChange={(e) => setPickSku(e.target.value)}
          className="rounded-lg border border-panel-line bg-panel-soft px-3 py-2 text-sm text-slate-200 focus:border-violet-500/50 focus:outline-none"
        >
          {devices.map((d) => (
            <option key={d.sku} value={d.sku}>{d.model} {d.storage}</option>
          ))}
        </select>
        <select
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          className="rounded-lg border border-panel-line bg-panel-soft px-3 py-2 text-sm text-slate-200 focus:border-violet-500/50 focus:outline-none"
        >
          {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input
          type="number"
          min={1}
          value={qty}
          onChange={(e) => setQty(parseInt(e.target.value) || 1)}
          className="w-24 rounded-lg border border-panel-line bg-panel-soft px-3 py-2 text-sm text-slate-200 focus:border-violet-500/50 focus:outline-none"
        />
        <button onClick={addRow} className="chip border-violet-500/40 text-violet-200 hover:bg-violet-500/10">+ Add</button>
        <button
          onClick={getQuote}
          disabled={rows.length === 0 || busy}
          className="rounded-lg border border-violet-600/40 bg-violet-500/10 px-4 py-2 text-sm font-medium text-violet-200 transition hover:bg-violet-500/20 disabled:opacity-40"
        >
          {busy ? "Quoting…" : "Get quote"}
        </button>
      </div>

      {rows.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-panel-line">
                <th className="th">Device</th>
                <th className="th">Grade</th>
                <th className="th text-right">Qty</th>
                {quote && <th className="th text-right">Unit price</th>}
                {quote && <th className="th text-right">Line total</th>}
                {quote && <th className="th text-right">Line margin</th>}
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const line = quote?.lines?.[i];
                return (
                  <tr key={i} className="row-hover border-b border-panel-line/50">
                    <td className="td font-medium text-slate-200">{modelOf[r.sku] || r.sku}</td>
                    <td className="td text-slate-400">{r.condition}</td>
                    <td className="td stat-num text-right text-slate-300">{r.quantity}</td>
                    {quote && <td className="td stat-num text-right text-white">{inr(line?.unit_price)}</td>}
                    {quote && <td className="td stat-num text-right text-slate-300">{inrCompact(line?.line_total)}</td>}
                    {quote && <td className="td stat-num text-right text-sky-300">{inrCompact(line?.line_margin)}</td>}
                    <td className="td text-right">
                      <button onClick={() => removeRow(i)} className="text-slate-500 hover:text-rose-400">✕</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {quote && (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-4">
          <KpiCard label="Total units" value={quote.total_units.toLocaleString("en-IN")} accent="violet" />
          <KpiCard label="Lot value" value={inrCompact(quote.total_value)} accent="sky" />
          <KpiCard label="Total margin" value={inrCompact(quote.total_margin)} accent="maple" />
          <KpiCard label="Blended margin" value={pct(quote.blended_margin_pct * 100)} accent="amber" />
        </div>
      )}
    </Panel>
  );
}
