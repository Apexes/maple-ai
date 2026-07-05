"""Scraper registry — discover, instantiate and run all adapters."""
from __future__ import annotations

from datetime import date

from ..config import get_config
from .apple_tradein import AppleTradeInScraper
from .base import BaseScraper
from .cashify import CashifyScraper
from .cashify_supersale import CashifySuperSaleScraper
from .controlz import ControlZScraper
from .dubai import DubaiResaleScraper
from .facebook import FacebookScraper
from .gsmexchange import GsmExchangeScraper
from .indiamart import IndiaMartScraper
from .maplestore import MapleStoreScraper
from .olx import OLXScraper
from .quikr import QuikrScraper

# Retail (B2C) adapters — the main scrape cycle (run_all_scrapers).
SCRAPER_CLASSES: list[type[BaseScraper]] = [
    MapleStoreScraper,
    CashifyScraper,
    ControlZScraper,
    OLXScraper,
    QuikrScraper,
    FacebookScraper,
    AppleTradeInScraper,
    DubaiResaleScraper,
]

# B2B wholesale adapters — a SEPARATE cycle (run_b2b_scrapers), driven by the
# daily refresh_b2b job. Kept out of SCRAPER_CLASSES so the retail refresh is
# completely unaffected by the B2B segment.
B2B_SCRAPER_CLASSES: list[type[BaseScraper]] = [
    GsmExchangeScraper,
    IndiaMartScraper,
    CashifySuperSaleScraper,
]


def _run(classes: list[type[BaseScraper]], as_of: date | None) -> tuple[list[dict], list[dict]]:
    cfg = get_config()
    all_listings: list[dict] = []
    report: list[dict] = []
    for cls in classes:
        scraper = cls(cfg)
        listings, source = scraper.scrape(as_of)
        all_listings.extend(listings)
        report.append(
            {
                "platform": scraper.platform_key,
                "platform_name": scraper.platform_name,
                "region": scraper.region,
                "source": source,          # 'live' or 'mock'
                "count": len(listings),
            }
        )
    return all_listings, report


def get_scrapers() -> list[BaseScraper]:
    cfg = get_config()
    return [cls(cfg) for cls in SCRAPER_CLASSES]


def run_all_scrapers(as_of: date | None = None) -> tuple[list[dict], list[dict]]:
    """Run every RETAIL adapter. Returns (all_listings, per_platform_report)."""
    return _run(SCRAPER_CLASSES, as_of)


def run_b2b_scrapers(as_of: date | None = None) -> tuple[list[dict], list[dict]]:
    """Run every B2B wholesale adapter (the daily B2B segment refresh)."""
    return _run(B2B_SCRAPER_CLASSES, as_of)
