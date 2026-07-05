"""Copilot API — local-LLM Q&A, scenarios, inventory planning, A/B tests."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import copilot
from ..db import get_session

router = APIRouter()


@router.get("/copilot/status")
def copilot_status() -> dict:
    """Local LLM server status + available scenario presets."""
    return copilot.status()


class AskRequest(BaseModel):
    question: str
    skus: list[str] | None = None


@router.post("/copilot/ask")
def copilot_ask(req: AskRequest, db: Session = Depends(get_session)) -> dict:
    """Grounded pricing Q&A. Auto-detects scenarios mentioned in the question."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question is empty")
    return copilot.ask(db, req.question.strip(), skus=req.skus)


class ScenarioRequest(BaseModel):
    scenario: str = "no_new_iphone"
    skus: list[str] | None = None
    params: dict | None = None
    horizon_days: int = Field(90, ge=7, le=365)


@router.post("/copilot/scenario")
def copilot_scenario(req: ScenarioRequest, db: Session = Depends(get_session)) -> dict:
    """Run a what-if scenario over the current market."""
    return copilot.run_scenario(
        db, req.scenario, skus=req.skus, params=req.params, horizon_days=req.horizon_days
    )


class InventoryItem(BaseModel):
    sku: str
    quantity: int = Field(ge=0)
    unit_cost: float | None = None


class InventoryPlanRequest(BaseModel):
    items: list[InventoryItem]
    horizon_days: int = Field(90, ge=7, le=365)


@router.post("/copilot/inventory/plan")
def copilot_inventory_plan(
    req: InventoryPlanRequest, db: Session = Depends(get_session)
) -> dict:
    """Q1 stock in -> Q2 plan out (restock / hold / clear per SKU)."""
    return copilot.plan_inventory(
        db, [i.model_dump() for i in req.items], horizon_days=req.horizon_days
    )


class AbTestRequest(BaseModel):
    sku: str
    price_a: float = Field(gt=0)
    price_b: float = Field(gt=0)
    daily_traffic: int = Field(400, gt=0)


@router.post("/copilot/abtest")
def copilot_abtest(req: AbTestRequest, db: Session = Depends(get_session)) -> dict:
    """Design a price A/B test: expected outcome, sample size, runtime."""
    result = copilot.design_ab_test(
        db, req.sku, req.price_a, req.price_b, daily_traffic=req.daily_traffic
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown sku '{req.sku}'")
    return result
