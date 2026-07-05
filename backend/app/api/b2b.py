"""B2B wholesale segment — market view, volume ladder, lot quote, global map."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.b2b_pricing import B2BPricingAgent
from ..db import get_session

router = APIRouter()


@router.get("/b2b")
def b2b_overview(db: Session = Depends(get_session)) -> dict:
    """Per-device wholesale view: B2B market value vs retail, discount, supply."""
    return B2BPricingAgent().overview(db)


@router.get("/b2b/spread")
def b2b_spread(top_n: int = Query(15), db: Session = Depends(get_session)) -> dict:
    """B2C↔B2B spread — biggest gaps between retail fair value and wholesale."""
    return B2BPricingAgent().spread(db, top_n=top_n)


@router.get("/b2b/global")
def b2b_global(db: Session = Depends(get_session)) -> dict:
    """Global price map — B2B price level by region (gsmExchange world view)."""
    return B2BPricingAgent().global_map(db)


@router.get("/b2b/globe")
def b2b_globe(db: Session = Depends(get_session)) -> dict:
    """Country-level world price view, geo-coded for the 3D globe."""
    return B2BPricingAgent().globe(db)


@router.get("/b2b/device/{sku}/ladder")
def b2b_ladder(
    sku: str,
    condition: str = Query("Superb"),
    db: Session = Depends(get_session),
) -> dict:
    """Volume-tier price ladder for one device."""
    result = B2BPricingAgent().volume_ladder(db, sku, condition=condition)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No B2B pricing for sku '{sku}'")
    return result


@router.get("/b2b/device/{sku}/costing")
def b2b_costing(
    sku: str,
    condition: str = Query("Superb"),
    quantity: int = Query(25),
    db: Session = Depends(get_session),
) -> dict:
    """Full retail-vs-B2B cost waterfall for one device (the costing view)."""
    result = B2BPricingAgent().costing(db, sku, condition=condition, quantity=quantity)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No pricing for sku '{sku}'")
    return result


class QuoteItem(BaseModel):
    sku: str
    quantity: int = 1
    condition: str = "Superb"


class QuoteRequest(BaseModel):
    items: list[QuoteItem]


@router.post("/b2b/quote")
def b2b_quote(req: QuoteRequest, db: Session = Depends(get_session)) -> dict:
    """Bulk-lot quote: mixed devices/grades/quantities -> total + margin."""
    items = [i.model_dump() for i in req.items]
    return B2BPricingAgent().lot_quote(db, items)
