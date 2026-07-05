"""Cashify SuperSale adapter — the dominant competitor's B2B app (DORMANT).

Cashify SuperSale is Maple's biggest competitor's B2B wholesale channel. It is
KYC-gated behind Cashify's own app, and Maple (rightly) does not want to register
a buyer account with its direct competitor. So this adapter ships DORMANT: it is
never seeded with a session, always falls back to its modeled synthetic floor,
and exists only so the competitor's structural B2B price level is represented in
the market map (and can be plugged in later if Maple ever chooses to).
"""
from __future__ import annotations

from .base import B2BWholesaleScraper


class CashifySuperSaleScraper(B2BWholesaleScraper):
    platform_key = "cashify_supersale"
    platform_name = "Cashify SuperSale"
    region = "IN"
    base_url = "https://supersale.cashify.in"
