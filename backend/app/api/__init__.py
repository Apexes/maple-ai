"""API routers."""
from fastapi import APIRouter

from . import agents, b2b, copilot, devices, listings, maple, market, meta, ml

api_router = APIRouter()
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(market.router, tags=["market"])
api_router.include_router(agents.router, tags=["agents"])
api_router.include_router(devices.router, tags=["devices"])
api_router.include_router(listings.router, tags=["listings"])
api_router.include_router(maple.router, tags=["maple"])
api_router.include_router(ml.router, tags=["ml"])
api_router.include_router(b2b.router, tags=["b2b"])
api_router.include_router(copilot.router, tags=["copilot"])
