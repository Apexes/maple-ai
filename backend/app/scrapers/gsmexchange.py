"""gsmExchange adapter — global B2B wholesale trading floor (LIVE).

The backbone of the B2B price map and the live global device-pricing view.
gsmExchange's trading floor is server-rendered and public: every offer shows
model, lot quantity, per-unit indicative price (USD/EUR/GBP), condition + spec,
seller country and posting time. Full company identity sits behind the vetted
login — when Maple's session cookie is seeded it is injected automatically,
but the price/qty/country data we need is available anonymously.

Scrape strategy (all plain HTTP, no browser needed):
  1. ``/en/phones/buy/apple`` — the Apple floor — lists per-model trading pages
     (~320 model slugs across iPhone + iPad).
  2. Map each slug onto Maple's device catalogue (iPhone 13–17, iPads); skip
     out-of-catalogue models (iPhone 8, 2018 iPads, …).
  3. Fetch each catalogue model page and parse its offer list (top ~20 most
     recent WTS offers per model, each a wholesale lot).

Offers with a masked price (shown as "USD 1" to anonymous visitors — the
"Negotiable" placeholder) are skipped; only real indicative prices are
ingested. Prices are USD; restated to INR via config. The seller's country
flag (ISO-2) becomes the listing region — this is what feeds the globe.
"""
from __future__ import annotations

import html as html_mod
import os
import re
from datetime import date, datetime

from ..catalog import Device, device_by_sku
from ..util import as_of_date
from .base import B2BWholesaleScraper, ScrapeBlocked
from .http import fetch_html

BASE = "https://www.gsmexchange.com"
APPLE_FLOOR = f"{BASE}/en/phones/buy/apple"

# Seconds between page fetches (politeness; the site is not rate-limited).
_THROTTLE = float(os.getenv("MAPLE_GSMX_THROTTLE", "0.8"))
# Cap the number of model pages fetched (0 = all catalogue matches).
_MAX_MODELS = int(os.getenv("MAPLE_GSMX_MAX_MODELS", "0"))

# --- slug -> catalogue SKU ------------------------------------------------- #
_IPHONE_SLUG_RE = re.compile(
    r"^(?:apple-)?iphone-(\d{1,2})(-mini|-plus|-pro-max|-pro)?-(\d+(?:gb|tb))$"
)
_IPAD_STORAGE_RE = re.compile(r"-(\d+(?:gb|tb))$")
_IPAD_PREFIXES = [  # ordered: most specific first
    ("ipad-mini", "ipadmini"),
    ("apple-ipad-mini", "ipadmini"),
    ("ipad-air-11", "ipadair11"),
    ("ipad-air-13", "ipadair13"),
    ("ipad-pro-11", "ipadpro11"),
    ("ipad-pro-13", "ipadpro13"),
    ("ipad-11", "ipad"),
    ("ipad-11th-gen", "ipad"),
]
_IPHONE_VARIANT = {
    None: "Base",
    "-mini": "Mini",
    "-plus": "Plus",
    "-pro": "Pro",
    "-pro-max": "Pro Max",
}


def sku_for_slug(slug: str) -> str | None:
    """Map a gsmExchange model slug onto a Maple catalogue SKU (or None)."""
    m = _IPHONE_SLUG_RE.match(slug)
    if m:
        series = int(m.group(1))
        variant = _IPHONE_VARIANT.get(m.group(2), "Base")
        storage = m.group(3).upper()
        sku = Device(series, variant, storage).sku
        return sku if device_by_sku(sku) else None
    for prefix, sku_prefix in _IPAD_PREFIXES:
        if slug.startswith(prefix):
            sm = _IPAD_STORAGE_RE.search(slug)
            if not sm:
                return None
            sku = f"{sku_prefix}-{sm.group(1)}"
            return sku if device_by_sku(sku) else None
    return None


# --- offer-block field extraction ------------------------------------------ #
_TRADE_SPLIT_RE = re.compile(r'<li id="trade(\d+)"')
_MODEL_RE = re.compile(r'<span class="model ?">([^<]+)</span>')
_PARENS_RE = re.compile(r'<span class="hint t-parens">([^<]+)</span>')
_QTY_RE = re.compile(r'class="c-tl-pq-q">([\d,]+)\s*pcs')
_FLAG_RE = re.compile(r"flags/([A-Za-z]{2})\.gif")
_FLAG_NAME_RE = re.compile(r'flags/[A-Za-z]{2}\.gif"[^>]*?(?:alt|title)="([^"]+)"')
_FROM_RE = re.compile(r"\bfrom ([^<]+)</label>")

# Country-name -> ISO-2 fallback when an offer carries no flag image.
_COUNTRY_ISO = {
    "united states": "US", "usa": "US", "united kingdom": "GB", "uk": "GB",
    "hong kong": "HK", "china": "CN", "united arab emirates": "AE",
    "india": "IN", "singapore": "SG", "germany": "DE", "spain": "ES",
    "netherlands": "NL", "france": "FR", "italy": "IT", "canada": "CA",
    "australia": "AU", "japan": "JP", "south korea": "KR", "taiwan": "TW",
    "poland": "PL", "czech republic": "CZ", "sweden": "SE", "denmark": "DK",
    "ireland": "IE", "belgium": "BE", "austria": "AT", "switzerland": "CH",
    "portugal": "PT", "greece": "GR", "romania": "RO", "hungary": "HU",
    "turkey": "TR", "israel": "IL", "saudi arabia": "SA", "qatar": "QA",
    "kuwait": "KW", "oman": "OM", "bahrain": "BH", "pakistan": "PK",
    "bangladesh": "BD", "sri lanka": "LK", "vietnam": "VN", "thailand": "TH",
    "malaysia": "MY", "indonesia": "ID", "philippines": "PH", "mexico": "MX",
    "brazil": "BR", "argentina": "AR", "chile": "CL", "colombia": "CO",
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "egypt": "EG",
    "new zealand": "NZ", "norway": "NO", "finland": "FI", "estonia": "EE",
    "latvia": "LV", "lithuania": "LT", "slovakia": "SK", "bulgaria": "BG",
    "ukraine": "UA", "miami": "US",
}
_TIME_RE = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})')
_RATING_RE = re.compile(r"Rating: \+?(-?\d+)")


def _price_usd(block: str) -> float | None:
    """Per-unit USD price; None when masked ('USD 1' = negotiable/hidden)."""
    m = re.search(
        r'class="c-tl-pq-c">USD</span><span class="c-tl-pq-v">([\d,\.]+)</span>',
        block,
    )
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # Anonymous placeholder is 1; anything under $20 is not a real Apple price.
    return v if v >= 20 else None


# Trading-floor condition vocabulary -> battery-health proxy (the floor does
# not publish battery %; grade normalization runs off raw_condition anyway).
_CONDITION_BATTERY = {
    "new": 100,
    "cpo": 97,
    "refurbished": 95,
    "used and tested": 89,
    "14 day": 88,
    "7 day / 14 day": 88,
    "asis": 82,
}


class GsmExchangeScraper(B2BWholesaleScraper):
    platform_key = "gsmexchange"
    platform_name = "gsmExchange"
    region = "GL"
    base_url = APPLE_FLOOR

    def fetch_raw(self, devices: list | None = None) -> list[dict]:
        sess = self.session()  # optional — the floor is public; cookies enrich
        as_of = as_of_date()

        floor = fetch_html(APPLE_FLOOR, self.platform_key, session=sess)
        slugs = sorted(
            set(re.findall(r'href="/en/phones/buy/apple/([^"?#]+)"', floor))
        )
        targets = [(s, sku_for_slug(s)) for s in slugs]
        targets = [(s, sku) for s, sku in targets if sku]
        if not targets:
            raise ScrapeBlocked(f"{self.platform_key}: no catalogue models on floor")
        if _MAX_MODELS > 0:
            targets = targets[:_MAX_MODELS]

        out: list[dict] = []
        seen_trades: set[str] = set()
        for slug, sku in targets:
            url = f"{APPLE_FLOOR}/{slug}"
            try:
                page = fetch_html(
                    url, self.platform_key, session=sess, throttle=_THROTTLE
                )
            except Exception:
                continue  # one dead model page must not kill the run
            out.extend(
                self._parse_offers(page, sku, url, as_of, seen_trades)
            )

        if not out:
            raise ScrapeBlocked(f"{self.platform_key}: parsed zero priced offers")
        return out

    # ------------------------------------------------------------------ #
    def _parse_offers(
        self, page: str, sku: str, page_url: str, as_of: date, seen: set[str]
    ) -> list[dict]:
        device = device_by_sku(sku)
        if device is None:
            return []
        parts = _TRADE_SPLIT_RE.split(page)
        offers: list[dict] = []
        # parts = [prefix, id1, block1, id2, block2, ...]
        for trade_id, block in zip(parts[1::2], parts[2::2]):
            if trade_id in seen:
                continue
            if ">WTB<" in block[:600]:  # requests, not offers
                continue
            usd = _price_usd(block)
            if usd is None:
                continue
            # Plausibility band vs MSRP (restated to INR): drops mis-keyed and
            # accessory-level prices without touching genuine wholesale levels.
            inr_check = usd * self.cfg.usd_to_inr
            if not (0.15 * device.msrp <= inr_check <= 1.6 * device.msrp):
                continue

            qty_m = _QTY_RE.search(block)
            qty = int(qty_m.group(1).replace(",", "")) if qty_m else 1

            parens_m = _PARENS_RE.search(block)
            raw_condition, spec = "", ""
            if parens_m:
                bits = [b.strip() for b in html_mod.unescape(parens_m.group(1)).split(",")]
                raw_condition = bits[0] if bits else ""
                spec = bits[1] if len(bits) > 1 else ""

            flag_m = _FLAG_RE.search(block)
            name_m = _FLAG_NAME_RE.search(block)
            country_code = flag_m.group(1).upper() if flag_m else ""
            country_name = name_m.group(1) if name_m else ""

            from_m = _FROM_RE.search(block)
            city = country_name or country_code
            if from_m:
                loc = html_mod.unescape(from_m.group(1)).strip()
                bits = [b.strip() for b in loc.split(",")]
                city = bits[0] or city
                if not country_name and len(bits) > 1:
                    country_name = bits[-1]
            if not country_code:  # no flag — fall back to the label's country
                country_code = _COUNTRY_ISO.get(country_name.strip().lower(), "GL")

            time_m = _TIME_RE.search(block)
            listing_date = as_of
            if time_m:
                try:
                    listing_date = datetime.strptime(time_m.group(1), "%Y-%m-%d").date()
                except ValueError:
                    pass

            rating_m = _RATING_RE.search(block)
            trader_rating = int(rating_m.group(1)) if rating_m else 0

            battery = _CONDITION_BATTERY.get(raw_condition.strip().lower(), 90)
            inr = round(usd * self.cfg.usd_to_inr / 50) * 50

            seen.add(trade_id)
            offers.append(
                {
                    "platform": self.platform_key,
                    "region": country_code,
                    "segment": "b2b",
                    "sku": sku,
                    "series": getattr(device, "series", 0),
                    "model": device.model,
                    "variant": getattr(device, "variant", ""),
                    "storage": device.storage,
                    "battery_health": battery,
                    "raw_condition": raw_condition or "Used and tested",
                    "city": city,
                    "asking_price": float(inr),          # per-unit INR
                    "asking_price_native": float(usd),   # per-unit USD
                    "currency": "USD",
                    "quantity": qty,
                    "seller_type": "wholesaler",
                    "seller_name": f"Vetted trader · {country_name or country_code}",
                    "seller_rating": 0.0,
                    "seller_reviews": max(0, trader_rating),
                    "warranty": "Trade terms (no consumer warranty)",
                    "accessories": "Bulk packed",
                    "lock_status": "Factory Unlocked",
                    "verified": True,  # gsmExchange traders are vetted members
                    "negotiable": True,
                    "views": 0,
                    "color": "",
                    "listing_title": (
                        f"{device.model} {device.storage} · {raw_condition or 'wholesale'}"
                        f"{' · ' + spec if spec else ''} · lot of {qty}"
                    ),
                    "listing_date": listing_date,
                    "url": f"{page_url}#trade{trade_id}",
                }
            )
        return offers
