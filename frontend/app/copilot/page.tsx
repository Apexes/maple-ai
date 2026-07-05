"use client";

import { useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/Shell";
import { Badge, ErrorState, KpiCard, Loading, Panel, SectionTitle } from "@/components/ui";
import { apiPost, endpoints } from "@/lib/api";
import { inr } from "@/lib/format";
import { useApi } from "@/lib/useApi";

type ChatMsg = {
  role: "user" | "copilot";
  text: string;
  engine?: string;
  scenario?: any;
};

const SUGGESTIONS = [
  "What should we price the iPhone 16 Pro Max at, since Apple is not releasing an iPhone this year?",
  "Should we buy iPhone 15 stock from the wholesale market right now?",
  "How will festive season demand affect iPhone 14 pricing?",
  "What happens to our prices if the rupee weakens against the dollar?",
];

const SAMPLE_CSV = `sku,quantity,unit_cost
ip16-promax-256gb,18,95000
ip16-base-128gb,42,48000
ip15-base-128gb,65,36000
ip14-base-128gb,80,26000
ip13-base-128gb,55,20000`;

export default function CopilotPage() {
  const status = useApi<any>(endpoints.copilotStatus);
  const [tab, setTab] = useState<"ask" | "scenarios" | "inventory" | "abtest">("ask");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Pricing Copilot"
        subtitle="Ask pricing questions, run what-if scenarios, plan next quarter's stock — every number computed from the live market, narrated by a local LLM (no data leaves this machine)"
        badge={
          status.data ? (
            <Badge tone={status.data.model_ready ? "maple" : "amber"}>
              {status.data.model_ready
                ? `local LLM · ${status.data.model}`
                : "deterministic mode (local LLM offline)"}
            </Badge>
          ) : undefined
        }
      />

      <div className="flex gap-1 rounded-xl border border-panel-line bg-panel/60 p-1 text-sm">
        {(
          [
            ["ask", "💬 Ask"],
            ["scenarios", "🔮 Scenarios"],
            ["inventory", "📦 Inventory Planner"],
            ["abtest", "🧪 A/B Pricing"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex-1 rounded-lg px-3 py-2 transition ${
              tab === key
                ? "bg-maple-500/10 text-maple-300 shadow-[inset_0_0_0_1px_rgba(34,197,94,0.25)]"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "ask" && <AskTab />}
      {tab === "scenarios" && <ScenariosTab scenarios={status.data?.scenarios || []} />}
      {tab === "inventory" && <InventoryTab />}
      {tab === "abtest" && <AbTestTab />}
    </div>
  );
}

/* ---------------------------- Ask (chat) ---------------------------- */
function AskTab() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  async function send(q?: string) {
    const question = (q ?? input).trim();
    if (!question || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setBusy(true);
    try {
      const r = await apiPost(endpoints.copilotAsk, { question });
      setMsgs((m) => [
        ...m,
        { role: "copilot", text: r.answer, engine: r.engine, scenario: r.scenario_analysis },
      ]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "copilot", text: `Error: ${e.message}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="flex min-h-[560px] flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto pr-1">
        {msgs.length === 0 && (
          <div className="pt-8 text-center">
            <div className="text-3xl">🍁</div>
            <p className="mt-2 text-sm text-slate-400">
              Ask anything about pricing, buying or the wholesale market.
            </p>
            <div className="mx-auto mt-5 grid max-w-2xl gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-xl border border-panel-line bg-white/[0.02] px-3 py-2.5 text-left text-xs text-slate-400 transition hover:border-maple-600/40 hover:text-slate-200"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-maple-500/15 text-maple-100"
                  : "border border-panel-line bg-white/[0.03] text-slate-200"
              }`}
            >
              {m.text}
              {m.engine && (
                <div className="mt-2 text-[10px] uppercase tracking-wider text-slate-500">
                  {m.engine}
                  {m.scenario ? ` · scenario: ${m.scenario.scenario.label}` : ""}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="h-2 w-2 animate-pulse rounded-full bg-maple-500" />
            Copilot is reading the market…
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="mt-4 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. What should we price the iPhone 16 Pro Max at?"
          className="flex-1 rounded-xl border border-panel-line bg-[#0b1220] px-4 py-2.5 text-sm text-slate-200 outline-none placeholder:text-slate-600 focus:border-maple-600/50"
        />
        <button
          disabled={busy || !input.trim()}
          className="rounded-xl border border-maple-600/40 bg-maple-500/10 px-5 py-2.5 text-sm font-medium text-maple-300 transition hover:bg-maple-500/20 disabled:opacity-40"
        >
          Ask
        </button>
      </form>
    </Panel>
  );
}

/* ---------------------------- Scenarios ---------------------------- */
function ScenariosTab({ scenarios }: { scenarios: any[] }) {
  const [key, setKey] = useState("no_new_iphone");
  const [horizon, setHorizon] = useState(90);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await apiPost(endpoints.copilotScenario, { scenario: key, horizon_days: horizon }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Panel>
        <SectionTitle title="Scenario" subtitle="deterministic what-if on the live market" />
        <div className="space-y-2">
          {scenarios.map((s) => (
            <button
              key={s.key}
              onClick={() => setKey(s.key)}
              className={`w-full rounded-xl border px-3 py-2.5 text-left text-sm transition ${
                key === s.key
                  ? "border-maple-600/50 bg-maple-500/10 text-maple-200"
                  : "border-panel-line bg-white/[0.02] text-slate-400 hover:text-slate-200"
              }`}
            >
              <div className="font-medium">{s.label}</div>
              <div className="mt-0.5 text-xs opacity-70">{s.narrative}</div>
            </button>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3 text-sm">
          <label className="text-slate-400">Horizon</label>
          {[30, 90, 180].map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              className={`rounded-lg px-2.5 py-1 text-xs ${
                horizon === h ? "bg-sky-500/15 text-sky-300" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {h}d
            </button>
          ))}
        </div>
        <button
          onClick={run}
          disabled={busy}
          className="mt-4 w-full rounded-xl border border-maple-600/40 bg-maple-500/10 py-2.5 text-sm font-medium text-maple-300 hover:bg-maple-500/20 disabled:opacity-50"
        >
          {busy ? "Simulating…" : "Run scenario"}
        </button>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      </Panel>

      <Panel>
        <SectionTitle
          title="Projected impact"
          subtitle={
            result
              ? `${result.scenario.label} · ${result.horizon_days} days · baseline drift ${result.baseline_monthly_drift_pct}%/mo`
              : "run a scenario to see projected prices"
          }
        />
        {result ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-panel-line text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="pb-2 pr-3">Device</th>
                  <th className="pb-2 pr-3">Today</th>
                  <th className="pb-2 pr-3">Baseline</th>
                  <th className="pb-2 pr-3">Scenario</th>
                  <th className="pb-2 pr-3">Δ vs baseline</th>
                  <th className="pb-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {result.devices.map((d: any) => (
                  <tr key={d.sku} className="border-b border-panel-line/50">
                    <td className="py-2.5 pr-3 font-medium text-slate-200">{d.model}</td>
                    <td className="py-2.5 pr-3 text-slate-400">{inr(d.current_fair_inr)}</td>
                    <td className="py-2.5 pr-3 text-slate-400">{inr(d.baseline_price_inr)}</td>
                    <td className="py-2.5 pr-3 font-semibold text-white">{inr(d.scenario_price_inr)}</td>
                    <td
                      className={`py-2.5 pr-3 font-medium ${
                        d.vs_baseline_pct >= 0 ? "text-maple-400" : "text-red-400"
                      }`}
                    >
                      {d.vs_baseline_pct >= 0 ? "+" : ""}
                      {d.vs_baseline_pct}%
                    </td>
                    <td className="py-2.5 text-xs text-slate-400">{d.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-16 text-center text-sm text-slate-500">
            {busy ? <Loading label="Simulating market…" /> : "No scenario run yet."}
          </div>
        )}
      </Panel>
    </div>
  );
}

/* ---------------------------- Inventory ---------------------------- */
function InventoryTab() {
  const [csv, setCsv] = useState(SAMPLE_CSV);
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function parseCsv(text: string) {
    const lines = text.trim().split(/\r?\n/);
    const header = lines[0].toLowerCase().split(",").map((h) => h.trim());
    const si = header.indexOf("sku");
    const qi = header.indexOf("quantity");
    const ci = header.indexOf("unit_cost");
    if (si < 0 || qi < 0) throw new Error("CSV needs 'sku' and 'quantity' columns");
    return lines.slice(1).filter(Boolean).map((l) => {
      const cells = l.split(",").map((c) => c.trim());
      return {
        sku: cells[si],
        quantity: parseInt(cells[qi] || "0", 10),
        unit_cost: ci >= 0 && cells[ci] ? parseFloat(cells[ci]) : null,
      };
    });
  }

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const items = parseCsv(csv);
      setPlan(await apiPost(endpoints.copilotInventoryPlan, { items, horizon_days: 90 }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        <Panel>
          <SectionTitle
            title="Your current stock (Q-1)"
            subtitle="paste CSV: sku, quantity, unit_cost — or upload from your ERP"
          />
          <textarea
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
            rows={10}
            spellCheck={false}
            className="w-full rounded-xl border border-panel-line bg-[#0b1220] p-3 font-mono text-xs text-slate-300 outline-none focus:border-maple-600/50"
          />
          <div className="mt-3 flex items-center gap-2">
            <label className="cursor-pointer rounded-lg border border-panel-line px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">
              Upload CSV
              <input
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  f.text().then(setCsv);
                }}
              />
            </label>
            <button
              onClick={run}
              disabled={busy}
              className="flex-1 rounded-lg border border-maple-600/40 bg-maple-500/10 py-1.5 text-sm font-medium text-maple-300 hover:bg-maple-500/20 disabled:opacity-50"
            >
              {busy ? "Planning…" : "Plan next quarter"}
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        </Panel>

        <div className="space-y-4">
          {plan && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <KpiCard label="Units in stock" value={plan.totals.units} accent="sky" />
              <KpiCard label="Stock value" value={inr(plan.totals.stock_value_inr)} accent="maple" />
              <KpiCard
                label="Projected in 90d"
                value={inr(plan.totals.projected_value_inr)}
                sub={<span className={plan.totals.value_drift_pct >= 0 ? "text-maple-400" : "text-red-400"}>{plan.totals.value_drift_pct >= 0 ? "+" : ""}{plan.totals.value_drift_pct}% drift</span>}
                accent="violet"
              />
              <KpiCard label="Q+1 buy budget" value={inr(plan.totals.buy_budget_inr)} accent="amber" />
            </div>
          )}
          <Panel>
            <SectionTitle
              title="Next-quarter plan"
              subtitle="demand-covered stock analysis · sorted by urgency"
            />
            {plan ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-panel-line text-left text-xs uppercase tracking-wider text-slate-500">
                      <th className="pb-2 pr-3">Device</th>
                      <th className="pb-2 pr-3">Qty</th>
                      <th className="pb-2 pr-3">Fair value</th>
                      <th className="pb-2 pr-3">90d drift</th>
                      <th className="pb-2 pr-3">Demand (90d)</th>
                      <th className="pb-2 pr-3">Buy Q+1</th>
                      <th className="pb-2">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.lines.map((l: any) => (
                      <tr key={l.sku} className="border-b border-panel-line/50">
                        <td className="py-2.5 pr-3 font-medium text-slate-200">
                          {l.model} <span className="text-xs text-slate-500">{l.storage}</span>
                        </td>
                        <td className="py-2.5 pr-3 text-slate-400">{l.quantity}</td>
                        <td className="py-2.5 pr-3 text-slate-400">{inr(l.fair_value_inr)}</td>
                        <td className={`py-2.5 pr-3 ${l.quarter_drift_pct >= 0 ? "text-maple-400" : "text-red-400"}`}>
                          {l.quarter_drift_pct >= 0 ? "+" : ""}
                          {l.quarter_drift_pct}%
                        </td>
                        <td className="py-2.5 pr-3 text-slate-400">{l.expected_demand_units}</td>
                        <td className="py-2.5 pr-3 font-semibold text-white">{l.next_quarter_buy_qty || "—"}</td>
                        <td className="py-2.5 text-xs text-slate-400">{l.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-16 text-center text-sm text-slate-500">
                Paste last quarter's stock and hit "Plan next quarter".
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------- A/B test ---------------------------- */
function AbTestTab() {
  const [sku, setSku] = useState("ip16-promax-256gb");
  const [priceA, setPriceA] = useState("115000");
  const [priceB, setPriceB] = useState("109500");
  const [traffic, setTraffic] = useState("400");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await apiPost(endpoints.copilotAbtest, {
          sku,
          price_a: parseFloat(priceA),
          price_b: parseFloat(priceB),
          daily_traffic: parseInt(traffic, 10),
        }),
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const field =
    "w-full rounded-xl border border-panel-line bg-[#0b1220] px-3 py-2 text-sm text-slate-200 outline-none focus:border-maple-600/50";

  return (
    <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
      <Panel>
        <SectionTitle title="Design a price test" subtitle="two price points, one device" />
        <div className="space-y-3 text-sm">
          <div>
            <label className="mb-1 block text-xs text-slate-500">Device SKU</label>
            <input value={sku} onChange={(e) => setSku(e.target.value)} className={field} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-slate-500">Price A (₹)</label>
              <input value={priceA} onChange={(e) => setPriceA(e.target.value)} className={field} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Price B (₹)</label>
              <input value={priceB} onChange={(e) => setPriceB(e.target.value)} className={field} />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">Daily product-page visitors</label>
            <input value={traffic} onChange={(e) => setTraffic(e.target.value)} className={field} />
          </div>
          <button
            onClick={run}
            disabled={busy}
            className="w-full rounded-xl border border-maple-600/40 bg-maple-500/10 py-2.5 font-medium text-maple-300 hover:bg-maple-500/20 disabled:opacity-50"
          >
            {busy ? "Designing…" : "Design test"}
          </button>
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
      </Panel>

      <Panel>
        <SectionTitle
          title="Test design"
          subtitle={result ? `${result.model} · fair value ${inr(result.fair_value_inr)}` : "expected outcome, sample size & runtime"}
        />
        {result ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              {(["A", "B"] as const).map((arm) => (
                <div
                  key={arm}
                  className={`rounded-xl border p-4 ${
                    result.expected_winner === arm
                      ? "border-maple-600/50 bg-maple-500/5"
                      : "border-panel-line bg-white/[0.02]"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-slate-200">Arm {arm}</span>
                    {result.expected_winner === arm && <Badge tone="maple">expected winner</Badge>}
                  </div>
                  <div className="mt-3 space-y-1.5 text-sm text-slate-400">
                    <div className="flex justify-between">
                      <span>Price</span>
                      <span className="font-semibold text-white">{inr(result.arms[arm].price_inr)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Expected conversion</span>
                      <span>{result.arms[arm].expected_conversion_pct}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Revenue / visitor</span>
                      <span>₹{result.arms[arm].expected_revenue_per_visitor_inr}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <KpiCard
                label="Sample size / arm"
                value={result.sample_size_per_arm?.toLocaleString("en-IN") ?? "—"}
                accent="sky"
              />
              <KpiCard label="Estimated runtime" value={result.estimated_days ? `${result.estimated_days} days` : "—"} accent="violet" />
            </div>
            <p className="text-xs text-slate-500">{result.note}</p>
          </div>
        ) : (
          <div className="py-16 text-center text-sm text-slate-500">
            {busy ? <Loading label="Computing test design…" /> : "Design a test to see the expected outcome."}
          </div>
        )}
      </Panel>
    </div>
  );
}
