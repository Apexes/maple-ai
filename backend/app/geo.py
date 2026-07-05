"""Country geometry for the global price globe (ISO-2 -> centroid + name).

Covers every market gsmExchange traders operate from; unknown codes simply
don't render on the globe (they still count in the region rollups).
"""
from __future__ import annotations

# iso2: (name, lat, lng)
COUNTRY_COORDS: dict[str, tuple[str, float, float]] = {
    "US": ("United States", 39.8, -98.6),
    "CA": ("Canada", 56.1, -106.3),
    "MX": ("Mexico", 23.6, -102.6),
    "BR": ("Brazil", -14.2, -51.9),
    "AR": ("Argentina", -38.4, -63.6),
    "CL": ("Chile", -35.7, -71.5),
    "CO": ("Colombia", 4.6, -74.3),
    "GB": ("United Kingdom", 54.0, -2.0),
    "IE": ("Ireland", 53.4, -8.2),
    "FR": ("France", 46.6, 2.2),
    "DE": ("Germany", 51.2, 10.4),
    "NL": ("Netherlands", 52.1, 5.3),
    "BE": ("Belgium", 50.5, 4.5),
    "ES": ("Spain", 40.5, -3.7),
    "PT": ("Portugal", 39.4, -8.2),
    "IT": ("Italy", 41.9, 12.6),
    "CH": ("Switzerland", 46.8, 8.2),
    "AT": ("Austria", 47.5, 14.6),
    "PL": ("Poland", 51.9, 19.1),
    "CZ": ("Czech Republic", 49.8, 15.5),
    "SK": ("Slovakia", 48.7, 19.7),
    "HU": ("Hungary", 47.2, 19.5),
    "RO": ("Romania", 45.9, 25.0),
    "BG": ("Bulgaria", 42.7, 25.5),
    "GR": ("Greece", 39.1, 21.8),
    "SE": ("Sweden", 60.1, 18.6),
    "NO": ("Norway", 60.5, 8.5),
    "DK": ("Denmark", 56.3, 9.5),
    "FI": ("Finland", 61.9, 25.7),
    "EE": ("Estonia", 58.6, 25.0),
    "LV": ("Latvia", 56.9, 24.6),
    "LT": ("Lithuania", 55.2, 23.9),
    "UA": ("Ukraine", 48.4, 31.2),
    "TR": ("Türkiye", 39.0, 35.2),
    "IL": ("Israel", 31.0, 34.9),
    "AE": ("United Arab Emirates", 23.4, 53.8),
    "SA": ("Saudi Arabia", 23.9, 45.1),
    "QA": ("Qatar", 25.3, 51.2),
    "KW": ("Kuwait", 29.3, 47.5),
    "OM": ("Oman", 21.5, 55.9),
    "BH": ("Bahrain", 26.0, 50.5),
    "EG": ("Egypt", 26.8, 30.8),
    "ZA": ("South Africa", -30.6, 22.9),
    "NG": ("Nigeria", 9.1, 8.7),
    "KE": ("Kenya", -0.02, 37.9),
    "IN": ("India", 20.6, 79.0),
    "PK": ("Pakistan", 30.4, 69.3),
    "BD": ("Bangladesh", 23.7, 90.4),
    "LK": ("Sri Lanka", 7.9, 80.8),
    "CN": ("China", 35.9, 104.2),
    "HK": ("Hong Kong", 22.3, 114.2),
    "TW": ("Taiwan", 23.7, 121.0),
    "JP": ("Japan", 36.2, 138.3),
    "KR": ("South Korea", 35.9, 127.8),
    "SG": ("Singapore", 1.35, 103.8),
    "MY": ("Malaysia", 4.2, 102.0),
    "TH": ("Thailand", 15.9, 100.9),
    "VN": ("Vietnam", 14.1, 108.3),
    "ID": ("Indonesia", -0.8, 113.9),
    "PH": ("Philippines", 12.9, 121.8),
    "AU": ("Australia", -25.3, 133.8),
    "NZ": ("New Zealand", -40.9, 174.9),
}


def country_name(iso2: str) -> str:
    entry = COUNTRY_COORDS.get(iso2)
    return entry[0] if entry else iso2


def country_latlng(iso2: str) -> tuple[float, float] | None:
    entry = COUNTRY_COORDS.get(iso2)
    return (entry[1], entry[2]) if entry else None
