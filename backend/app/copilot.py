"""
Maple Copilot — the predictive/analytical brain the sales team talks to.

Architecture: every number is produced by the DETERMINISTIC layer (fair values
from pricing.py, forecasts from the trained PriceModel, scenario math below);
the local LLM (llm_local) only turns that structured context into a fluent
answer. If the model server is down, the same context is rendered through a
template — the copilot never fabricates a price and never breaks.

Capabilities:
  * ask()            — natural-language Q&A grounded in the live market context
  * run_scenario()   — what-if analysis (no new iPhone, festive demand, FX, …)
  * plan_inventory() — upload last quarter's stock, get next quarter's plan
  * design_ab_test() — price A/B test design with sample size & runtime
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .agents.b2b_pricing import B2BPricingAgent
from .agents.base import Agent
from .catalog import Device, all_devices, device_by_sku
from .config import get_config
from .llm_local import DEFAULT_MODEL, llm_status, local_chat
from .ml.model import load_model
from .pricing import recommend_prices

# --------------------------------------------------------------------------- #
# Device mention detection (question text -> catalogue SKUs)
# --------------------------------------------------------------------------- #
_IPHONE_Q_RE = re.compile(r"i\s*phone\s*(\d{1,2})\s*(pro\s*max|pro|plus|mini)?", re.I)
_STORAGE_Q_RE = re.compile(r"(\d+)\s*(gb|tb)", re.I)

_VARIANT_NORM = {None: "Base", "": "Base", "pro max": "Pro Max", "promax": "Pro Max",
                 "pro": "Pro", "plus": "Plus", "mini": "Mini"}


def find_skus_in_text(text: str, limit: int = 4) -> list[str]:
    """Best-effort catalogue SKUs mentioned in free text."""
    skus: list[str] = []
    for m in _IPHONE_Q_RE.finditer(text):
        series = int(m.group(1))
        variant = _VARIANT_NORM.get((m.group(2) or "").lower().replace("  ", " "), "Base")
        sm = _STORAGE_Q_RE.search(text)
        storage = f"{sm.group(1)}{sm.group(2).upper()}" if sm else "256GB"
        for st in (storage, "256GB", "128GB"):
            sku = Device(series, variant, st).sku
            if device_by_sku(sku) and sku not in skus:
                skus.append(sku)
                break
    low = text.lower()
    if not skus:  # non-iPhone families by name
        for d in all_devices():
            if getattr(d, "family", "iPhone") != "iPhone" and d.model.lower() in low:
                skus.append(d.sku)
    return skus[:limit]


# --------------------------------------------------------------------------- #
# Context pack — everything an answer may need, all deterministic
# --------------------------------------------------------------------------- #
def build_context(db: Session, question: str = "", skus: list[str] | None = None) -> dict:
    cfg = get_config()
    agent = Agent(cfg)
    vals = agent.valuations(db, region="IN")
    model = load_model()

    skus = skus or find_skus_in_text(question)
    if not skus:  # default to the market's most valuable devices
        skus = [s for s, _ in sorted(
            vals.items(), key=lambda kv: kv[1].fair.fair_value, reverse=True
        )[:3]]

    b2b_ov = B2BPricingAgent(cfg).overview(db)
    b2b_by_sku = {d["sku"]: d for d in b2b_ov["devices"]}

    devices = []
    for sku in skus:
        v = vals.get(sku)
        device = device_by_sku(sku)
        if device is None:
            continue
        fair = v.fair.fair_value if v else None
        rec = recommend_prices(fair, "Superb", cfg).__dict__ if fair else None
        fc = model.forecast(sku) if (model and fair) else {}
        b2b = b2b_by_sku.get(sku)
        devices.append({
            "sku": sku,
            "model": device.model,
            "storage": device.storage,
            "launch_msrp_inr": device.msrp,
            "retail_fair_value_inr": fair,
            "listing_count": v.listing_count if v else 0,
            "recommended_sell_inr": round(rec["recommended_sell"]) if rec else None,
            "recommended_buy_inr": round(rec["recommended_buy"]) if rec else None,
            "forecast": fc or None,
            "b2b": {
                "market_value_inr": b2b["b2b_market_value"],
                "wholesale_discount_pct": b2b["wholesale_discount_pct"],
                "units_available": b2b["units_available"],
                "sources": b2b["sources"],
            } if b2b else None,
        })

    return {
        "as_of": str(agent.as_of),
        "currency": "INR",
        "monthly_market_drift_pct": (
            round((math.exp(model.depr_k) - 1) * 100, 2) if model else None
        ),
        "devices": devices,
        "b2b_totals": {
            "lots": b2b_ov["total_lots"],
            "units": b2b_ov["total_units"],
            "sources": b2b_ov["sources"],
        },
    }


# --------------------------------------------------------------------------- #
# Scenario engine
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    key: str
    label: str
    narrative: str
    demand_shift_pct: float = 0.0       # buyer demand vs baseline
    depreciation_multiplier: float = 1.0  # scales the learned monthly drift
    fx_shift_pct: float = 0.0            # USD/INR move (import parity)
    keywords: list[str] = field(default_factory=list)


SCENARIOS: dict[str, Scenario] = {
    "no_new_iphone": Scenario(
        "no_new_iphone", "Apple skips this year's iPhone launch",
        "No replacement cycle: current generations stay 'newest' longer, so "
        "depreciation slows sharply and demand for late-gen used units firms up.",
        demand_shift_pct=8.0, depreciation_multiplier=0.45,
        keywords=["not releasing", "no iphone", "skips", "no new iphone", "delay launch", "not launching"],
    ),
    "new_launch": Scenario(
        "new_launch", "New iPhone generation launches",
        "A fresh generation accelerates depreciation of every prior series and "
        "floods trade-in supply; used prices step down fastest in the first 8 weeks.",
        demand_shift_pct=-5.0, depreciation_multiplier=1.8,
        keywords=["new launch", "iphone 18", "launches", "just released"],
    ),
    "festive_demand": Scenario(
        "festive_demand", "Festive-season demand surge",
        "Diwali/holiday demand lifts sell-through; supply is unchanged short-term "
        "so prices firm up and inventory turns accelerate.",
        demand_shift_pct=15.0, depreciation_multiplier=0.9,
        keywords=["festive", "diwali", "holiday season", "christmas"],
    ),
    "rupee_weakens": Scenario(
        "rupee_weakens", "Rupee weakens 5% vs USD",
        "Imported wholesale stock (gsmExchange is USD-priced) gets ~5% dearer in "
        "INR; the import-parity floor under domestic used prices rises.",
        fx_shift_pct=5.0, depreciation_multiplier=0.85,
        keywords=["rupee", "usd", "fx", "exchange rate", "dollar"],
    ),
}

# Price elasticity of demand assumed for used premium phones.
_ELASTICITY = -1.5


def detect_scenario(question: str) -> Scenario | None:
    low = question.lower()
    for sc in SCENARIOS.values():
        if any(k in low for k in sc.keywords):
            return sc
    return None


def run_scenario(
    db: Session,
    scenario_key: str,
    skus: list[str] | None = None,
    params: dict | None = None,
    horizon_days: int = 90,
) -> dict:
    """Deterministic what-if: baseline vs scenario price path per device."""
    cfg = get_config()
    sc = SCENARIOS.get(scenario_key)
    if sc is None:
        sc = Scenario(scenario_key or "custom", "Custom scenario", "User-defined shocks.")
    if params:
        sc = Scenario(
            sc.key, sc.label, sc.narrative,
            demand_shift_pct=float(params.get("demand_shift_pct", sc.demand_shift_pct)),
            depreciation_multiplier=float(params.get("depreciation_multiplier", sc.depreciation_multiplier)),
            fx_shift_pct=float(params.get("fx_shift_pct", sc.fx_shift_pct)),
        )

    ctx = build_context(db, skus=skus or [])
    model = load_model()
    base_drift_m = model.depr_k if model else math.log(1 - 0.015)  # ~-1.5%/mo fallback
    months = horizon_days / 30.44

    # Demand shock -> price support via elasticity; FX -> import-parity pass-through.
    demand_price_effect = sc.demand_shift_pct / (-_ELASTICITY) / 100.0
    fx_price_effect = 0.6 * sc.fx_shift_pct / 100.0

    rows = []
    for d in ctx["devices"]:
        fair = d["retail_fair_value_inr"]
        if not fair:
            continue
        baseline = fair * math.exp(base_drift_m * months)
        shocked = (
            fair * (1 + demand_price_effect + fx_price_effect)
            * math.exp(base_drift_m * sc.depreciation_multiplier * months)
        )
        delta_pct = (shocked / baseline - 1) * 100
        rec = recommend_prices(shocked, "Superb", cfg)
        rows.append({
            "sku": d["sku"],
            "model": d["model"],
            "current_fair_inr": fair,
            "baseline_price_inr": round(baseline),
            "scenario_price_inr": round(shocked),
            "vs_baseline_pct": round(delta_pct, 1),
            "recommended_sell_inr": round(rec.recommended_sell),
            "recommended_buy_inr": round(rec.recommended_buy),
            "action": (
                "Hold pricing firm — do not discount into this market"
                if delta_pct > 2
                else "Accelerate sell-through before the step-down"
                if delta_pct < -2
                else "Track weekly; no pricing action needed yet"
            ),
        })

    return {
        "scenario": {
            "key": sc.key, "label": sc.label, "narrative": sc.narrative,
            "demand_shift_pct": sc.demand_shift_pct,
            "depreciation_multiplier": sc.depreciation_multiplier,
            "fx_shift_pct": sc.fx_shift_pct,
        },
        "horizon_days": horizon_days,
        "baseline_monthly_drift_pct": round((math.exp(base_drift_m) - 1) * 100, 2),
        "devices": rows,
    }


# --------------------------------------------------------------------------- #
# Inventory planning (Q1 stock in -> Q2 plan out)
# --------------------------------------------------------------------------- #
def plan_inventory(db: Session, items: list[dict], horizon_days: int = 90) -> dict:
    """items: [{sku, quantity, unit_cost?}] -> per-SKU next-quarter plan."""
    cfg = get_config()
    agent = Agent(cfg)
    vals = agent.valuations(db, region="IN")
    model = load_model()
    b2b_ov = B2BPricingAgent(cfg).overview(db)
    b2b_by_sku = {d["sku"]: d for d in b2b_ov["devices"]}

    total_listings = sum(v.listing_count for v in vals.values()) or 1
    monthly_units = cfg.baselines.assumed_monthly_units
    months = horizon_days / 30.44
    drift_m = model.depr_k if model else math.log(1 - 0.015)

    lines, totals = [], {"units": 0, "stock_value": 0.0, "projected_value": 0.0}
    for item in items:
        sku = item.get("sku")
        qty = int(item.get("quantity", 0) or 0)
        device = device_by_sku(sku)
        v = vals.get(sku)
        if device is None or qty <= 0:
            continue
        fair = v.fair.fair_value if v else None
        if not fair:
            continue
        unit_cost = float(item.get("unit_cost") or 0.0)
        rec = recommend_prices(fair, "Superb", cfg)

        # Demand share proxy: this SKU's share of market listings x Maple volume.
        demand_q = max(1.0, v.listing_count / total_listings * monthly_units) * months
        cover_ratio = qty / demand_q
        projected_fair = fair * math.exp(drift_m * months)
        b2b = b2b_by_sku.get(sku)

        if cover_ratio > 1.4:
            action = "OVERSTOCKED — discount 3–5% now; value decays before it sells"
            buy_qty = 0
        elif cover_ratio < 0.6:
            buy_qty = int(round(demand_q - qty))
            disc = b2b.get("wholesale_discount_pct") if b2b else None
            if disc is not None and disc > 0:
                src = (
                    f"source via B2B ({disc}% below retail, "
                    f"{b2b['units_available']} units on offer)"
                )
            elif disc is not None:
                src = (
                    "source via trade-in + marketplace buys "
                    f"(global B2B trades {abs(disc)}% ABOVE local retail — don't import)"
                )
            else:
                src = "source via trade-in + marketplace buys"
            action = f"UNDERSTOCKED — buy ~{buy_qty} units; {src}"
        else:
            action = "BALANCED — replenish to demand as units sell"
            buy_qty = max(0, int(round(demand_q - qty)))

        margin_pct = ((rec.recommended_sell - unit_cost) / rec.recommended_sell
                      if unit_cost else cfg.pricing.target_margin_pct)
        lines.append({
            "sku": sku,
            "model": device.model,
            "storage": device.storage,
            "quantity": qty,
            "unit_cost_inr": unit_cost or None,
            "fair_value_inr": fair,
            "projected_fair_inr": round(projected_fair),
            "quarter_drift_pct": round((projected_fair / fair - 1) * 100, 1),
            "expected_demand_units": round(demand_q),
            "cover_ratio": round(cover_ratio, 2),
            "gross_margin_pct": round(margin_pct * 100, 1),
            "recommended_sell_inr": round(rec.recommended_sell),
            "next_quarter_buy_qty": buy_qty,
            "action": action,
        })
        totals["units"] += qty
        totals["stock_value"] += fair * qty
        totals["projected_value"] += projected_fair * qty

    lines.sort(key=lambda l: l["cover_ratio"])
    return {
        "horizon_days": horizon_days,
        "lines": lines,
        "totals": {
            "units": totals["units"],
            "stock_value_inr": round(totals["stock_value"]),
            "projected_value_inr": round(totals["projected_value"]),
            "value_drift_pct": round(
                (totals["projected_value"] / totals["stock_value"] - 1) * 100, 1
            ) if totals["stock_value"] else 0.0,
            "buy_budget_inr": round(sum(
                l["next_quarter_buy_qty"] * (l["fair_value_inr"] or 0) * 0.86
                for l in lines
            )),
        },
    }


# --------------------------------------------------------------------------- #
# A/B price test designer
# --------------------------------------------------------------------------- #
def design_ab_test(
    db: Session, sku: str, price_a: float, price_b: float,
    daily_traffic: int = 400, base_conversion: float = 0.02,
) -> dict | None:
    device = device_by_sku(sku)
    if device is None or price_a <= 0 or price_b <= 0:
        return None
    vals = Agent().valuations(db, region="IN")
    fair = vals[sku].fair.fair_value if sku in vals else None

    conv_a = base_conversion * (price_a / fair) ** _ELASTICITY if fair else base_conversion
    conv_b = base_conversion * (price_b / fair) ** _ELASTICITY if fair else (
        base_conversion * (price_b / price_a) ** _ELASTICITY
    )
    conv_a, conv_b = max(1e-4, conv_a), max(1e-4, conv_b)
    p_bar = (conv_a + conv_b) / 2
    delta = abs(conv_b - conv_a)
    # Two-proportion test, alpha=0.05 (two-sided), power=0.80.
    n_per_arm = (
        math.ceil(2 * ((1.96 + 0.84) ** 2) * p_bar * (1 - p_bar) / (delta**2))
        if delta > 1e-6 else None
    )
    rev_a, rev_b = conv_a * price_a, conv_b * price_b
    winner = "A" if rev_a >= rev_b else "B"
    return {
        "sku": sku,
        "model": device.model,
        "fair_value_inr": fair,
        "elasticity_assumed": _ELASTICITY,
        "arms": {
            "A": {"price_inr": price_a, "expected_conversion_pct": round(conv_a * 100, 2),
                  "expected_revenue_per_visitor_inr": round(rev_a, 1)},
            "B": {"price_inr": price_b, "expected_conversion_pct": round(conv_b * 100, 2),
                  "expected_revenue_per_visitor_inr": round(rev_b, 1)},
        },
        "expected_winner": winner,
        "sample_size_per_arm": n_per_arm,
        "estimated_days": (
            math.ceil(2 * n_per_arm / max(1, daily_traffic)) if n_per_arm else None
        ),
        "note": (
            "Expected outcome from the elasticity prior; run the test to confirm — "
            "the winner is decided by measured revenue per visitor, not the prior."
        ),
    }


# --------------------------------------------------------------------------- #
# Q&A — local LLM over the deterministic context (template fallback)
# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = """You are Maple Copilot, the pricing analyst for Maple Store \
(India's premium Apple reseller — certified pre-owned devices). You advise the \
sales team on pricing, buying and inventory.

Rules:
- Base EVERY number strictly on the CONTEXT JSON provided. Never invent prices.
- Copy each price DIGIT-FOR-DIGIT from the context, then add a ₹ sign in front. \
Do not regroup, round, or re-derive numbers (context says 104700 -> write ₹104700).
- The headline recommendation must be the context's scenario_price_inr (if a \
scenario is present) or recommended_sell_inr — never a number you computed yourself.
- Be concise and decisive: lead with the recommendation, then 2-4 short bullets \
of rationale (market fair value, trend, B2B angle, scenario effect if present).
- If the context lacks the data to answer, say exactly what is missing."""


def _fallback_answer(question: str, ctx: dict, scenario: dict | None) -> str:
    parts = []
    for d in ctx["devices"][:3]:
        if not d["retail_fair_value_inr"]:
            continue
        line = (
            f"{d['model']} {d['storage']}: market fair value ₹{d['retail_fair_value_inr']:,.0f}; "
            f"recommended sell ₹{d['recommended_sell_inr']:,} / buy ₹{d['recommended_buy_inr']:,}"
        )
        fc = d.get("forecast") or {}
        if fc.get("monthly_drift_pct") is not None:
            line += f"; drifting {fc['monthly_drift_pct']:+.1f}%/month"
        if d.get("b2b") and d["b2b"].get("wholesale_discount_pct") is not None:
            disc = d["b2b"]["wholesale_discount_pct"]
            rel = f"{disc}% below" if disc >= 0 else f"{abs(disc)}% above"
            line += (
                f"; wholesale trades {rel} retail "
                f"({d['b2b']['units_available']} units on the trade floor)"
            )
        parts.append(line)
    if scenario:
        sc = scenario["scenario"]
        moves = ", ".join(
            f"{r['model']}: ₹{r['scenario_price_inr']:,} ({r['vs_baseline_pct']:+.1f}% vs baseline)"
            for r in scenario["devices"][:3]
        )
        parts.append(f"Scenario '{sc['label']}': {sc['narrative']} Projected {scenario['horizon_days']}d prices — {moves}.")
        if scenario["devices"]:
            parts.append(f"Recommended action: {scenario['devices'][0]['action']}.")
    return "\n".join(parts) if parts else (
        "No priced devices matched the question — name a model (e.g. 'iPhone 16 Pro Max')."
    )


def ask(db: Session, question: str, skus: list[str] | None = None) -> dict:
    import json as _json

    skus = skus or find_skus_in_text(question)
    ctx = build_context(db, question, skus)
    sc = detect_scenario(question)
    scenario_result = run_scenario(db, sc.key, skus=skus) if sc else None

    payload = {"context": ctx}
    if scenario_result:
        payload["scenario_analysis"] = scenario_result

    answer = local_chat(
        _SYSTEM_PROMPT,
        f"QUESTION: {question}\n\nCONTEXT JSON:\n{_json.dumps(payload, default=str)}",
    )
    used_llm = answer is not None
    if answer is None:
        answer = _fallback_answer(question, ctx, scenario_result)

    return {
        "question": question,
        "answer": answer,
        "engine": f"local:{DEFAULT_MODEL}" if used_llm else "deterministic-fallback",
        "llm": used_llm,
        "scenario_detected": sc.key if sc else None,
        "context": ctx,
        "scenario_analysis": scenario_result,
    }


def status() -> dict:
    s = llm_status()
    s["scenarios"] = [
        {"key": k, "label": v.label, "narrative": v.narrative} for k, v in SCENARIOS.items()
    ]
    return s
