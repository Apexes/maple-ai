"""
The pricing brain.

Two responsibilities:

1. fair_market_value(...) — turn a noisy bag of listings (different conditions,
   cities, platforms, ages) into ONE condition-normalized fair value, using:
       * condition weighting   (normalize price to the 'Superb' reference grade)
       * recency weighting      (recent listings count more)
       * source weighting       (trusted platforms count more)
       * outlier trimming        (drop the cheapest/priciest tails)

2. recommend_prices(...) — apply Maple's Pricing Recommendation Formula:

       Recommended Selling Price =
           Market Median + Brand Premium + Warranty Premium + Maple Trust Premium

       Recommended Buying Price =
           Recommended Selling Price
           - Target Margin - Refurbishment Cost - Logistics Cost - Warranty Reserve

All knobs come from config (fully configurable).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date

from .config import MapleConfig, get_config


# --------------------------------------------------------------------------- #
# Observation normalization
# --------------------------------------------------------------------------- #
@dataclass
class Observation:
    normalized_price: float   # price restated to Superb / Delhi / retail reference
    weight: float
    raw_price: float
    platform: str
    city: str
    condition: str
    age_days: int


def recency_weight(age_days: float, half_life: float) -> float:
    if half_life <= 0:
        return 1.0
    return 0.5 ** (max(0.0, age_days) / half_life)


def restate_price(
    asking_price: float,
    *,
    condition: str | None = None,
    city: str | None = None,
    platform: str | None = None,
    cfg: MapleConfig | None = None,
) -> float:
    """Restate an observed price by dividing out ONLY the chosen structural effects.

    This is the key difference between *valuation* and *arbitrage*:
      * Fair value divides out condition + city + platform (estimate the value).
      * Competitor compare divides out condition + city, KEEPS platform
        (so platform price levels are comparable).
      * Arbitrage divides out condition only, KEEPS city + platform
        (so the geographic spread survives — that IS the opportunity).
    """
    cfg = cfg or get_config()
    p = asking_price
    if condition is not None:
        p /= cfg.condition_multipliers.get(condition, 1.0)
    if city is not None:
        p /= cfg.city_multipliers.get(city, 1.0)
    if platform is not None:
        pc = cfg.platform(platform)
        p /= pc.index if pc else 1.0
    return p


def _city_mult(cfg: MapleConfig, city: str) -> float:
    return cfg.city_multipliers.get(city, 1.0)


def _platform_index(cfg: MapleConfig, platform: str) -> float:
    p = cfg.platform(platform)
    return p.index if p else 1.0


def _platform_weight(cfg: MapleConfig, platform: str) -> float:
    p = cfg.platform(platform)
    return p.weight if p else 0.5


def build_observation(
    *,
    asking_price: float,
    platform: str,
    city: str,
    condition: str,
    listing_date: date,
    as_of: date,
    cfg: MapleConfig | None = None,
) -> Observation:
    cfg = cfg or get_config()
    cond_mult = cfg.condition_multipliers.get(condition, 1.0)
    cond_conf = cfg.condition_confidence.get(condition, 0.85)
    city_mult = _city_mult(cfg, city)
    plat_index = _platform_index(cfg, platform)

    # Restate the observed price to the reference: Superb grade, Delhi, retail level.
    normalized = asking_price / (cond_mult * city_mult * plat_index)

    age_days = max(0, (as_of - listing_date).days)
    w = (
        _platform_weight(cfg, platform)
        * recency_weight(age_days, cfg.pricing.recency_half_life_days)
        * cond_conf
    )
    return Observation(
        normalized_price=round(normalized, 2),
        weight=round(w, 4),
        raw_price=asking_price,
        platform=platform,
        city=city,
        condition=condition,
        age_days=age_days,
    )


# --------------------------------------------------------------------------- #
# Fair market value
# --------------------------------------------------------------------------- #
@dataclass
class FairValue:
    fair_value: float          # the condition-normalized central estimate (Superb)
    weighted_mean: float
    weighted_median: float
    p25: float
    p75: float
    low: float
    high: float
    sample_size: int
    confidence: float          # 0..1 — based on sample size & weight concentration


def _weighted_percentile(pairs: list[tuple[float, float]], q: float) -> float:
    """pairs = [(value, weight)] sorted by value. q in [0,1]."""
    if not pairs:
        return 0.0
    total = sum(w for _, w in pairs)
    if total <= 0:
        vals = [v for v, _ in pairs]
        idx = min(len(vals) - 1, int(q * len(vals)))
        return vals[idx]
    cum = 0.0
    target = q * total
    for v, w in pairs:
        cum += w
        if cum >= target:
            return v
    return pairs[-1][0]


def fair_market_value(
    observations: list[Observation], cfg: MapleConfig | None = None
) -> FairValue | None:
    cfg = cfg or get_config()
    obs = [o for o in observations if o.normalized_price > 0 and o.weight > 0]
    if not obs:
        return None

    obs.sort(key=lambda o: o.normalized_price)

    # Trim tails by count to kill scams / typos / overpriced flippers.
    n = len(obs)
    trim = cfg.pricing.trim_fraction
    cut = int(n * trim)
    trimmed = obs[cut: n - cut] if n - 2 * cut >= 3 else obs

    pairs = [(o.normalized_price, o.weight) for o in trimmed]
    wsum = sum(w for _, w in pairs) or 1.0

    weighted_mean = sum(v * w for v, w in pairs) / wsum
    weighted_median = _weighted_percentile(pairs, 0.50)
    p25 = _weighted_percentile(pairs, 0.25)
    p75 = _weighted_percentile(pairs, 0.75)

    # Primary fair value: blend robust median with weighted mean (60/40).
    fair = 0.6 * weighted_median + 0.4 * weighted_mean

    # Confidence: more samples + tighter spread => higher.
    spread = (p75 - p25) / fair if fair else 1.0
    size_factor = min(1.0, n / 12.0)
    confidence = max(0.05, min(0.99, size_factor * (1.0 - min(spread, 0.6))))

    return FairValue(
        fair_value=round(fair, 0),
        weighted_mean=round(weighted_mean, 0),
        weighted_median=round(weighted_median, 0),
        p25=round(p25, 0),
        p75=round(p75, 0),
        low=round(obs[0].normalized_price, 0),
        high=round(obs[-1].normalized_price, 0),
        sample_size=n,
        confidence=round(confidence, 2),
    )


# --------------------------------------------------------------------------- #
# Pricing Recommendation Formula
# --------------------------------------------------------------------------- #
@dataclass
class PriceRecommendation:
    condition: str
    market_median: float          # condition-adjusted market median (the base)
    brand_premium: float
    warranty_premium: float
    maple_trust_premium: float
    recommended_sell: float
    target_margin: float
    refurbishment_cost: float
    logistics_cost: float
    warranty_reserve: float
    recommended_buy: float
    expected_gross_margin: float       # INR
    expected_gross_margin_pct: float   # fraction of sell

    def to_dict(self) -> dict:
        return asdict(self)


def recommend_prices(
    fair_value_superb: float,
    condition: str,
    cfg: MapleConfig | None = None,
) -> PriceRecommendation:
    """Apply the configurable pricing formula for a given condition."""
    cfg = cfg or get_config()
    p = cfg.pricing
    cond_mult = cfg.condition_multipliers.get(condition, 1.0)

    # Condition-adjusted market median (the "Market Median" in the formula).
    market_median = fair_value_superb * cond_mult

    brand = market_median * p.brand_premium_pct
    warranty = market_median * p.warranty_premium_pct
    trust = market_median * p.maple_trust_premium_pct

    sell = market_median + brand + warranty + trust

    target_margin = sell * p.target_margin_pct
    buy = sell - target_margin - p.refurbishment_cost - p.logistics_cost - p.warranty_reserve

    # What Maple actually nets if it buys at `buy` and sells at `sell`.
    total_cost = buy + p.refurbishment_cost + p.logistics_cost + p.warranty_reserve
    gm = sell - total_cost
    gm_pct = gm / sell if sell else 0.0

    return PriceRecommendation(
        condition=condition,
        market_median=round(market_median, 0),
        brand_premium=round(brand, 0),
        warranty_premium=round(warranty, 0),
        maple_trust_premium=round(trust, 0),
        recommended_sell=round(sell, 0),
        target_margin=round(target_margin, 0),
        refurbishment_cost=round(p.refurbishment_cost, 0),
        logistics_cost=round(p.logistics_cost, 0),
        warranty_reserve=round(p.warranty_reserve, 0),
        recommended_buy=round(buy, 0),
        expected_gross_margin=round(gm, 0),
        expected_gross_margin_pct=round(gm_pct, 4),
    )


def recommend_all_conditions(
    fair_value_superb: float, cfg: MapleConfig | None = None
) -> dict[str, PriceRecommendation]:
    cfg = cfg or get_config()
    return {
        cond: recommend_prices(fair_value_superb, cond, cfg)
        for cond in cfg.condition_multipliers
    }


# --------------------------------------------------------------------------- #
# B2B / wholesale unit economics
# --------------------------------------------------------------------------- #
@dataclass
class B2BUnitEconomics:
    condition: str
    quantity: int
    retail_fair_value: float       # the B2C condition-adjusted fair value (reference)
    wholesale_unit: float          # per-unit wholesale SELL at this quantity
    volume_discount_pct: float     # discount applied for the lot size
    recommended_buy: float         # what Maple should pay per unit to hit B2B margin
    expected_gross_margin: float   # INR per unit
    expected_gross_margin_pct: float
    lot_total: float               # wholesale_unit * quantity

    def to_dict(self) -> dict:
        return asdict(self)


def b2b_unit_economics(
    fair_value_superb: float,
    condition: str,
    quantity: int = 1,
    cfg: MapleConfig | None = None,
) -> B2BUnitEconomics:
    """Per-unit wholesale price + margin for a given grade and lot size.

    Wholesale clears below the B2C retail fair value (b2b.wholesale_index) and
    drops further with volume (b2b.volume_tiers). Maple's B2B buy price is the
    wholesale sell less the thinner B2B target margin and the trade costs (refurb
    + logistics; no consumer warranty reserve on trade terms).
    """
    cfg = cfg or get_config()
    b = cfg.b2b
    c = cfg.costs
    cond_mult = cfg.condition_multipliers.get(condition, 1.0)

    retail_fair = fair_value_superb * cond_mult

    # Volume discount for this lot size.
    disc = 0.0
    for tier in sorted(b.volume_tiers, key=lambda t: t[0]):
        if quantity >= tier[0]:
            disc = tier[1]

    wholesale_unit = retail_fair * b.wholesale_index * (1 - disc)

    trade_costs = c.refurb_parts + c.refurb_labour + c.logistics_inbound + c.logistics_outbound + c.qc_grading
    target_margin = wholesale_unit * b.b2b_target_margin_pct
    buy = wholesale_unit - target_margin - trade_costs

    total_cost = buy + trade_costs
    gm = wholesale_unit - total_cost
    gm_pct = gm / wholesale_unit if wholesale_unit else 0.0

    return B2BUnitEconomics(
        condition=condition,
        quantity=quantity,
        retail_fair_value=round(retail_fair, 0),
        wholesale_unit=round(wholesale_unit, 0),
        volume_discount_pct=round(disc * 100, 1),
        recommended_buy=round(buy, 0),
        expected_gross_margin=round(gm, 0),
        expected_gross_margin_pct=round(gm_pct, 4),
        lot_total=round(wholesale_unit * quantity, 0),
    )


# --------------------------------------------------------------------------- #
# Full per-unit cost waterfall (the "costing matters" view)
# --------------------------------------------------------------------------- #
@dataclass
class CostBreakdown:
    condition: str
    segment: str                 # "retail" or "b2b"
    sell_price: float
    acquisition_cost: float      # what Maple pays to buy the unit
    refurb_parts: float
    refurb_labour: float
    logistics_inbound: float
    logistics_outbound: float
    qc_grading: float
    warranty_reserve: float      # 0 for b2b (trade terms)
    platform_fee: float          # pct of sell
    payment_fee: float           # pct of sell
    overhead_alloc: float
    total_cost: float
    net_margin: float            # sell - total_cost (AFTER all costs, incl fees/overhead)
    net_margin_pct: float
    breakeven_sell: float        # sell price at which net margin == 0

    def to_dict(self) -> dict:
        return asdict(self)


def cost_breakdown(
    fair_value_superb: float,
    condition: str,
    segment: str = "retail",
    quantity: int = 1,
    cfg: MapleConfig | None = None,
) -> CostBreakdown:
    """Decompose a unit into its FULL cost stack and the true NET margin.

    This is intentionally fuller than recommend_prices()'s gross margin: it adds
    QC, channel/payment fees and allocated overhead, so the dashboard can show
    how a headline gross margin erodes to the real net margin per unit. Segment
    'b2b' uses wholesale economics (b2b_unit_economics) and drops the consumer
    warranty reserve.
    """
    cfg = cfg or get_config()
    c = cfg.costs

    if segment == "b2b":
        econ = b2b_unit_economics(fair_value_superb, condition, quantity, cfg)
        sell = econ.wholesale_unit
        acquisition = econ.recommended_buy
        warranty_reserve = 0.0
    else:
        reco = recommend_prices(fair_value_superb, condition, cfg)
        sell = reco.recommended_sell
        acquisition = reco.recommended_buy
        warranty_reserve = c.warranty_reserve

    platform_fee = sell * c.platform_fee_pct
    payment_fee = sell * c.payment_fee_pct

    total_cost = (
        acquisition + c.refurb_parts + c.refurb_labour
        + c.logistics_inbound + c.logistics_outbound + c.qc_grading
        + warranty_reserve + platform_fee + payment_fee + c.overhead_alloc
    )
    net = sell - total_cost
    net_pct = net / sell if sell else 0.0

    # Break-even sell: fixed costs / (1 - variable fee fraction).
    fixed = (
        acquisition + c.refurb_parts + c.refurb_labour
        + c.logistics_inbound + c.logistics_outbound + c.qc_grading
        + warranty_reserve + c.overhead_alloc
    )
    fee_frac = c.platform_fee_pct + c.payment_fee_pct
    breakeven = fixed / (1 - fee_frac) if fee_frac < 1 else fixed

    return CostBreakdown(
        condition=condition,
        segment=segment,
        sell_price=round(sell, 0),
        acquisition_cost=round(acquisition, 0),
        refurb_parts=round(c.refurb_parts, 0),
        refurb_labour=round(c.refurb_labour, 0),
        logistics_inbound=round(c.logistics_inbound, 0),
        logistics_outbound=round(c.logistics_outbound, 0),
        qc_grading=round(c.qc_grading, 0),
        warranty_reserve=round(warranty_reserve, 0),
        platform_fee=round(platform_fee, 0),
        payment_fee=round(payment_fee, 0),
        overhead_alloc=round(c.overhead_alloc, 0),
        total_cost=round(total_cost, 0),
        net_margin=round(net, 0),
        net_margin_pct=round(net_pct, 4),
        breakeven_sell=round(breakeven, 0),
    )
