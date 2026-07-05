"""IndiaMART adapter — India B2B directory (LIVE; wholesale incl. MacBooks).

The India-wide wholesale source for the non-phone Apple lineup (MacBooks,
iPads) as well as iPhones. IndiaMART's ``dir.indiamart.com/impcat/*`` category
pages are server-rendered: each supplier card shows product title, ₹ price,
price unit (Piece / Unit), supplier name and city — all public. When Maple's
logged-in session is seeded (cookie blob), it is injected for richer results.

IndiaMART rate-limits aggressively (HTTP 429), so fetches are spaced several
seconds apart and retried with backoff. Only titles that map onto Maple's
device catalogue (iPhone 13–17, current iPads/MacBooks) are ingested — a 2014
MacBook Air at ₹15k must not contaminate the price of an M4 Air. Everything
fetched is archived raw in ``scrape_raw`` regardless, so nothing is lost.
"""
from __future__ import annotations

import html as html_mod
import os
import re
from datetime import date

from ..catalog import Device, device_by_sku
from ..util import as_of_date
from .base import B2BWholesaleScraper, ScrapeBlocked
from .http import fetch_html

BASE = "https://dir.indiamart.com/impcat"

# Category pages scraped each cycle (comma-separated slugs, env-overridable).
_DEFAULT_CATEGORIES = ",".join(
    [
        "used-iphone",               # iPhones (all generations; catalogue filters)
        "refurbished-apple-iphone",  # iPhones (second angle)
        "refurbished-apple-laptop",  # MacBooks
        "apple-macbook",             # MacBooks
        "apple-macbook-air",         # MacBook Air
        "apple-macbook-pro",         # MacBook Pro
        "apple-mac-mini",            # Mac mini
        "apple-imac",                # iMac
        "refurbished-mobile-phones", # mixed brands; Apple titles filtered in
    ]
)
_CATEGORIES = [
    s.strip()
    for s in os.getenv("MAPLE_INDIAMART_CATEGORIES", _DEFAULT_CATEGORIES).split(",")
    if s.strip()
]
# Seconds between category fetches — IndiaMART 429s under faster polling.
_THROTTLE = float(os.getenv("MAPLE_INDIAMART_THROTTLE", "6.0"))

# --- title -> catalogue SKU -------------------------------------------------- #
_STORAGE_RE = re.compile(r"(\d+)\s*(GB|TB)\b", re.I)
_IPHONE_RE = re.compile(r"i\s*phone\s*(\d{1,2})", re.I)
_MBP_INCH_RE = re.compile(r"(14|16)\s*(?:inch|\"|”)?", re.I)
_M_CHIP_RE = re.compile(r"\bM([1-4])(\s*(pro|max))?\b", re.I)

_KNOWN_IPHONE_SERIES = {13, 14, 15, 16, 17}


def _iphone_sku(title: str) -> str | None:
    m = _IPHONE_RE.search(title)
    if not m:
        return None
    series = int(m.group(1))
    if series not in _KNOWN_IPHONE_SERIES:
        return None
    low = title.lower()
    if "pro max" in low or "promax" in low:
        variant = "Pro Max"
    elif re.search(r"\bpro\b", low):
        variant = "Pro"
    elif "plus" in low:
        variant = "Plus"
    elif "mini" in low:
        variant = "Mini"
    else:
        variant = "Base"
    sm = _STORAGE_RE.search(title)
    storage = f"{sm.group(1)}{sm.group(2).upper()}" if sm else "128GB"
    sku = Device(series, variant, storage).sku
    return sku if device_by_sku(sku) else None


def _mac_sku(title: str, storage_hint: str | None) -> str | None:
    """Macs: only current Apple-silicon (M-chip) units map to catalogue."""
    low = title.lower()
    if not re.search(r"macbook|mac book|mac mini|imac", low):
        return None
    if not _M_CHIP_RE.search(title):
        return None  # Intel-era units are out of catalogue — skip, don't poison
    sm = _STORAGE_RE.search(title)
    storage = (
        f"{sm.group(1)}{sm.group(2).upper()}"
        if sm
        else (storage_hint or "256GB")
    )
    if "mac mini" in low:
        token = "m4pro" if re.search(r"m4\s*pro", low) else "m4"
        sku = f"macmini-{token}-{storage.lower()}"
        return sku if device_by_sku(sku) else None
    if "imac" in low:
        sku = f"imac24-{storage.lower()}"
        return sku if device_by_sku(sku) else None
    if "air" in low:
        prefix = "mba15" if "15" in low else "mba13"
        sku = f"{prefix}-{storage.lower()}"  # single-chip family: no chip token
    elif "pro" in low:
        inch = _MBP_INCH_RE.search(low.replace("macbook pro", ""))
        prefix = "mbp16" if inch and inch.group(1) == "16" else "mbp14"
        chip = _M_CHIP_RE.search(title)
        tier = (chip.group(3) or "").lower() if chip else ""
        token = "m4max" if tier == "max" else ("m4pro" if tier == "pro" else "m4")
        if prefix == "mbp16" and token == "m4":
            token = "m4pro"  # 16" starts at M4 Pro
        sku = f"{prefix}-{token}-{storage.lower()}"
    else:
        return None
    return sku if device_by_sku(sku) else None


def sku_for_title(title: str, storage_hint: str | None = None) -> str | None:
    return _iphone_sku(title) or _mac_sku(title, storage_hint)


# --- card-level extraction ---------------------------------------------------- #
_CARD_SPLIT = re.compile(r'class="prdtitle')
# Title is an <a href> when the product has a detail page, else a bare <span>.
_TITLE_RE = re.compile(r'^[^"]*"(?:\s+href="([^"]+)")?[^>]*>\s*([^<]+?)\s*<')
_PRICE_RE = re.compile(r'class="prc[^"]*">\s*₹\s*([\d,\.]+)')
_UNIT_RE = re.compile(r'class="prcut[^"]*">\s*([^<]+?)\s*<')
_CITY_RE = re.compile(r'itemProp="addressLocality">([^<]+)<')
# Supplier homepage link (proddetail links are the product, not the seller).
_SELLER_RE = re.compile(
    r'href="https://www\.indiamart\.com/(?!proddetail)[^"]*"[^>]*>([^<]{2,60})</a>'
)
_TRUSTSEAL = "TrustSEAL"
_SPEC_ROW_RE = re.compile(r"<dt[^>]*>([^<]+)</dt><dd[^>]*>([^<]+)</dd>")

# Wholesale units treated as per-piece prices; anything else (Set/Box/…) skipped.
_PIECE_UNITS = {"piece", "unit", "piece(s)", "number", "pc"}


class IndiaMartScraper(B2BWholesaleScraper):
    platform_key = "indiamart"
    platform_name = "IndiaMART"
    region = "IN"
    base_url = f"{BASE}/used-iphone.html"

    def fetch_raw(self, devices: list | None = None) -> list[dict]:
        sess = self.session()  # optional cookie enrichment
        as_of = as_of_date()
        out: list[dict] = []
        errors = 0
        for i, cat in enumerate(_CATEGORIES):
            url = f"{BASE}/{cat}.html"
            try:
                page = fetch_html(
                    url,
                    self.platform_key,
                    session=sess,
                    throttle=_THROTTLE if i else 0.0,
                    retries=3,
                    backoff=25.0,
                )
            except Exception:
                errors += 1
                continue
            out.extend(self._parse_cards(page, as_of))
        if not out:
            raise ScrapeBlocked(
                f"{self.platform_key}: no catalogue listings parsed "
                f"({errors}/{len(_CATEGORIES)} categories failed)"
            )
        # De-duplicate across categories by product URL.
        seen: set[str] = set()
        unique = []
        for r in out:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            unique.append(r)
        return unique

    # ------------------------------------------------------------------ #
    def _parse_cards(self, page: str, as_of: date) -> list[dict]:
        cards = _CARD_SPLIT.split(page)[1:]  # chunk per supplier card
        rows: list[dict] = []
        for chunk in cards:
            t = _TITLE_RE.match(chunk)
            p = _PRICE_RE.search(chunk)
            if not t or not p:
                continue
            title = html_mod.unescape(t.group(2)).strip()
            # Link-less cards get a stable pseudo-URL for de-duplication.
            url = t.group(1) or f"indiamart:{abs(hash((title, p.group(1))))}"
            try:
                price = float(p.group(1).replace(",", ""))
            except ValueError:
                continue
            if price < 3000:  # accessories / junk floor for catalogue devices
                continue

            unit_m = _UNIT_RE.search(chunk)
            if unit_m and unit_m.group(1).strip().lower() not in _PIECE_UNITS:
                continue  # price not per-piece (e.g. per Set) — not comparable

            specs = {
                html_mod.unescape(k).strip(): html_mod.unescape(v).strip()
                for k, v in _SPEC_ROW_RE.findall(chunk)
            }
            storage_hint = None
            for key in ("Storage Capacity", "Maximum storage", "Internal Storage"):
                if key in specs:
                    sm = _STORAGE_RE.search(specs[key])
                    if sm:
                        storage_hint = f"{sm.group(1)}{sm.group(2).upper()}"
                        break

            sku = sku_for_title(title, storage_hint)
            if not sku:
                continue
            device = device_by_sku(sku)
            # Plausibility band vs MSRP: kills clone/scam listings (a ₹10k
            # "iPhone 15") and bundle prices without touching real wholesale.
            if not (0.18 * device.msrp <= price <= 1.5 * device.msrp):
                continue

            city_m = _CITY_RE.search(chunk)
            city = "Mumbai"
            if city_m:
                # "Jogeshwari East, Mumbai" -> the metro is the last component.
                city = html_mod.unescape(city_m.group(1)).split(",")[-1].strip()

            seller_m = _SELLER_RE.search(chunk)
            seller = (
                html_mod.unescape(seller_m.group(1)).strip()
                if seller_m
                else "IndiaMART supplier"
            )

            raw_condition = (
                "Refurbished"
                if re.search(r"refurb", title, re.I)
                else "Used - Good"
                if re.search(r"used|second\s*hand|pre[- ]?owned", title, re.I)
                else "Refurbished"
            )

            rows.append(
                {
                    "platform": self.platform_key,
                    "region": self.region,
                    "segment": "b2b",
                    "sku": sku,
                    "series": getattr(device, "series", 0),
                    "model": device.model,
                    "variant": getattr(device, "variant", ""),
                    "storage": device.storage,
                    "battery_health": 88,
                    "raw_condition": raw_condition,
                    "city": city,
                    "asking_price": price,
                    "asking_price_native": price,
                    "currency": "INR",
                    "quantity": 1,  # directory lists per-piece; MOQ varies by seller
                    "seller_type": "wholesaler",
                    "seller_name": seller[:60],
                    "seller_rating": 4.2 if _TRUSTSEAL in chunk else 0.0,
                    "seller_reviews": 0,
                    "warranty": "Seller warranty (trade terms)",
                    "accessories": "As listed",
                    "lock_status": "Factory Unlocked",
                    "verified": _TRUSTSEAL in chunk,
                    "negotiable": True,
                    "views": 0,
                    "color": "",
                    "listing_title": title[:180],
                    "listing_date": as_of,
                    "url": url[:300],
                }
            )
        return rows
