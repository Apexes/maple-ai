// API client for the Maple AI Department backend.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000/api";

export async function apiGet<T = any>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T = any>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const endpoints = {
  health: "/health",
  snapshot: "/market/snapshot",
  metrics: "/market/metrics",
  index: "/market/index",
  pricing: "/market/pricing",
  devices: "/devices",
  device: (sku: string) => `/devices/${sku}`,
  competitor: "/agents/competitor",
  arbitrage: "/agents/arbitrage",
  inventory: "/agents/inventory",
  dubai: "/agents/dubai",
  facets: "/listings/facets",
  refresh: "/scrape/refresh",
  grades: "/normalization/grades",
  config: "/config",
  // Maple vs Market (comparison angle)
  mapleComparison: "/maple/comparison",
  mapleComparisonOne: (sku: string) => `/maple/comparison/${sku}`,
  // ML pricing layer
  mlPricing: "/ml/pricing",
  mlPricingOne: (sku: string) => `/ml/pricing/${sku}`,
  mlForecast: "/ml/forecast",
  // B2B wholesale segment
  b2b: "/b2b",
  b2bSpread: "/b2b/spread",
  b2bGlobal: "/b2b/global",
  b2bLadder: (sku: string) => `/b2b/device/${sku}/ladder`,
  b2bCosting: (sku: string) => `/b2b/device/${sku}/costing`,
  b2bQuote: "/b2b/quote",
  // Global price globe
  b2bGlobe: "/b2b/globe",
  // Copilot (local-LLM pricing analyst)
  copilotStatus: "/copilot/status",
  copilotAsk: "/copilot/ask",
  copilotScenario: "/copilot/scenario",
  copilotInventoryPlan: "/copilot/inventory/plan",
  copilotAbtest: "/copilot/abtest",
};
