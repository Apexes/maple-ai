"""
Agent orchestrator — the 'AI Department'.

Runs every agent against the current market state and assembles the executive
snapshot the dashboards consume.  In production this is what a scheduler /
Redis worker invokes after each scrape cycle.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_config
from ..models import MarketDaily
from .arbitrage import ArbitrageAgent
from .b2b_pricing import B2BPricingAgent
from .competitor import CompetitorIntelligenceAgent
from .device_pricing import DevicePricingAgent
from .dubai import DubaiExpansionAgent
from .inventory import InventoryAgent
from .maple_compare import MapleComparisonAgent
from .market_pricing import MarketPricingAgent
from .ml_pricing import MLPricingAgent


AGENTS = {
    CompetitorIntelligenceAgent.name: CompetitorIntelligenceAgent,
    MarketPricingAgent.name: MarketPricingAgent,
    DevicePricingAgent.name: DevicePricingAgent,
    ArbitrageAgent.name: ArbitrageAgent,
    InventoryAgent.name: InventoryAgent,
    DubaiExpansionAgent.name: DubaiExpansionAgent,
    MapleComparisonAgent.name: MapleComparisonAgent,
    MLPricingAgent.name: MLPricingAgent,
    B2BPricingAgent.name: B2BPricingAgent,
}


def run_agent(name: str, db: Session) -> dict | None:
    cls = AGENTS.get(name)
    if not cls:
        return None
    return cls(get_config()).run(db)


def executive_snapshot(db: Session) -> dict:
    """Compact cross-agent summary for the Executive Dashboard."""
    cfg = get_config()
    competitor = CompetitorIntelligenceAgent(cfg).run(db)
    arb = ArbitrageAgent(cfg).run(db, top_n=5)
    dubai = DubaiExpansionAgent(cfg).run(db, top_n=5)
    inventory = InventoryAgent(cfg).run(db)

    # market index history for the headline chart
    rows = list(db.scalars(select(MarketDaily).order_by(MarketDaily.day.asc())))
    history = [
        {"day": r.day.isoformat(), "index": r.index_value, "movement_pct": r.movement_pct}
        for r in rows
    ]

    # representative buy/sell headline: top high-demand model, Superb grade
    headline_device = None
    if inventory["high_demand"]:
        top = inventory["high_demand"][0]
        headline_device = {
            "model": top["model"],
            "storage": top["storage"],
            "recommended_buy": top["recommended_buy"],
            "recommended_sell": top["recommended_sell"],
            "fair_value": top["fair_value"],
        }

    return {
        "market_index": competitor["price_movement"],
        "market_index_history": history,
        "headline_device": headline_device,
        "top_arbitrage": arb["opportunities"],
        "arbitrage_total_value": arb["total_opportunity_value"],
        "top_dubai": dubai["opportunities"],
        "dubai_total_value": dubai["total_margin_potential"],
        "top_demand": inventory["high_demand"][:5],
        "top_underpriced": inventory["underpriced"][:5],
        "competitor_rankings": competitor["competitor_rankings"],
    }
