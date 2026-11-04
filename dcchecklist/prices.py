"""6-month average prices from the official BrickLink API.

Uses the price guide endpoint of BrickLink's API v1
(GET /items/MINIFIG/{no}/price?guide_type=sold ...), which reports the sales
of the last six months. It needs the user's own API keys (consumer key /
secret, token / token secret) from bricklink.com. Results are stored in
prices.json, so they stay visible offline.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote, urlencode

import requests

from .net import CancelledError
from .storage import read_json, write_json

API_BASE = "https://api.bricklink.com/api/store/v1"
REGISTER_PAGE = "https://www.bricklink.com/v2/api/register_consumer.page"
DAILY_LIMIT = 5000          # BrickLink allows 5,000 API calls per day
SAFE_LIMIT = 4500

REGIONS: dict[str, tuple[str, list[dict]]] = {
    "dach": ("DACH (Deutschland, Österreich, Schweiz)",
             [{"country_code": "DE"}, {"country_code": "AT"}, {"country_code": "CH"}]),
    "eu": ("EU", [{"region": "eu"}]),
    "europe": ("Europa", [{"region": "europe"}]),
    "de": ("Deutschland", [{"country_code": "DE"}]),
    "world": ("Weltweit", [{}]),
}
CONDITIONS = {"U": "gebraucht", "N": "neu"}


class PriceError(RuntimeError):
    pass


# ------------------------------------------------------------- OAuth 1.0a

def _enc(s: str) -> str:
    return quote(str(s), safe="~-._")


def oauth_header(method: str, url: str, params: dict, consumer_key: str, consumer_secret: str,
                 token: str, token_secret: str, nonce: str | None = None,
                 timestamp: str | None = None, version: str | None = "1.0") -> str:
    """Authorization header value (HMAC-SHA1, RFC 5849)."""
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_token": token,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_nonce": nonce or secrets.token_hex(12),
    }
    if version:
        oauth["oauth_version"] = version
    allp = [(_enc(k), _enc(v)) for k, v in list(params.items()) + list(oauth.items())]
    allp.sort()
    norm = "&".join(f"{k}={v}" for k, v in allp)
    base = "&".join([method.upper(), _enc(url), _enc(norm)])
    key = f"{_enc(consumer_secret)}&{_enc(token_secret)}"
    sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{_enc(k)}="{_enc(v)}"' for k, v in oauth.items())


# ------------------------------------------------------------ data model

@dataclass
class Credentials:
    consumer_key: str = ""
    consumer_secret: str = ""
    token: str = ""
    token_secret: str = ""

    def complete(self) -> bool:
        return all(v.strip() for v in (self.consumer_key, self.consumer_secret,
                                       self.token, self.token_secret))


def load_credentials() -> Credentials:
    d = read_json("bricklink_api.json", {})
    d = d if isinstance(d, dict) else {}
    return Credentials(**{k: str(d.get(k, "")) for k in Credentials.__dataclass_fields__})


def save_credentials(c: Credentials) -> None:
    write_json("bricklink_api.json", c.__dict__)


def load_prices() -> dict:
    d = read_json("prices.json", {})
    return d if isinstance(d, dict) else {}


def save_prices(prices: dict) -> None:
    write_json("prices.json", prices)


def _usage() -> dict:
    u = read_json("api_usage.json", {})
    today = dt.date.today().isoformat()
    if not isinstance(u, dict) or u.get("day") != today:
        u = {"day": today, "calls": 0}
    return u


def calls_today() -> int:
    return int(_usage().get("calls", 0))


def _count_call() -> None:
    u = _usage()
    u["calls"] = int(u.get("calls", 0)) + 1
    write_json("api_usage.json", u)


def combine(parts: list[dict]) -> dict | None:
    """Merge several price guide answers (e.g. DE + AT + CH) weighted by quantity."""
    total_qty = sum(int(p.get("total_quantity") or 0) for p in parts)
    if not total_qty:
        return {"avg": None, "qty": 0, "lots": 0, "min": None, "max": None}
    weighted = sum(float(p.get("qty_avg_price") or p.get("avg_price") or 0) *
                   int(p.get("total_quantity") or 0) for p in parts)
    mins = [float(p["min_price"]) for p in parts if p.get("total_quantity") and p.get("min_price")]
    maxs = [float(p["max_price"]) for p in parts if p.get("total_quantity") and p.get("max_price")]
    return {"avg": round(weighted / total_qty, 2), "qty": total_qty,
            "lots": sum(int(p.get("unit_quantity") or 0) for p in parts),
            "min": min(mins) if mins else None, "max": max(maxs) if maxs else None}


# ---------------------------------------------------------------- client

class PriceClient:
    def __init__(self, creds: Credentials, currency: str = "EUR",
                 cancel: threading.Event | None = None, delay: float = 0.25):
        self.creds = creds
        self.currency = currency
        self.cancel = cancel or threading.Event()
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "DC-Minifig-Checkliste (BrickLink API)"

    def _get(self, path: str, params: dict) -> dict:
        if self.cancel.is_set():
            raise CancelledError("Abgebrochen")
        if calls_today() >= SAFE_LIMIT:
            raise PriceError(f"Tageslimit fast erreicht ({calls_today()} von {DAILY_LIMIT} "
                             "API-Abfragen heute). Morgen geht es weiter – bereits geladene "
                             "Preise bleiben gespeichert.")
        url = API_BASE + path
        c = self.creds
        header = oauth_header("GET", url, params, c.consumer_key.strip(), c.consumer_secret.strip(),
                              c.token.strip(), c.token_secret.strip())
        try:
            r = self.session.get(url, params=params, headers={"Authorization": header}, timeout=30)
        except requests.RequestException as exc:
            raise PriceError(f"Keine Verbindung zur BrickLink-API: {exc}") from exc
        _count_call()
        time.sleep(self.delay)
        try:
            data = r.json()
        except ValueError:
            raise PriceError(f"Unerwartete Antwort der BrickLink-API (HTTP {r.status_code}).")
        meta = data.get("meta") or {}
        code = int(meta.get("code") or r.status_code)
        if code == 200:
            return data.get("data") or {}
        msg = f"{meta.get('message', '')} {meta.get('description', '')}".strip()
        if code == 404:
            return {}
        if code in (401, 403):
            hint = ""
            if "IP" in msg.upper():
                hint = (" – der Token ist an eine andere IP-Adresse gebunden. Bei BrickLink "
                        "einen Token mit IP 0.0.0.0 und Maske 0.0.0.0 anlegen.")
            raise PriceError(f"BrickLink-API lehnt die Zugangsdaten ab: {msg}{hint}")
        if code == 429:
            raise PriceError("Zu viele API-Abfragen – bitte später weitermachen.")
        raise PriceError(f"BrickLink-API Fehler {code}: {msg}")

    def test(self) -> str:
        data = self._get("/items/MINIFIG/sh0532", {})
        return data.get("name") or "ok"

    def guide(self, item_id: str, condition: str, filt: dict) -> dict:
        params = {"guide_type": "sold", "new_or_used": condition,
                  "currency_code": self.currency, "vat": "Y", **filt}
        return self._get(f"/items/MINIFIG/{quote(item_id)}/price", params)

    def price_for(self, item_id: str, region: str, conditions: list[str]) -> dict:
        filters = REGIONS.get(region, REGIONS["dach"])[1]
        rec = {"date": dt.date.today().isoformat(), "region": region, "currency": self.currency}
        for cond in conditions:
            rec[cond] = combine([self.guide(item_id, cond, f) for f in filters])
        return rec


def calls_per_figure(region: str, conditions: list[str]) -> int:
    return len(REGIONS.get(region, REGIONS["dach"])[1]) * len(conditions)


def stale(rec: dict | None, region: str, max_age_days: int, conditions: list[str],
          currency: str) -> bool:
    if not rec or rec.get("region") != region or rec.get("currency") != currency:
        return True
    if any(c not in rec for c in conditions):
        return True
    try:
        age = (dt.date.today() - dt.date.fromisoformat(rec.get("date", ""))).days
    except ValueError:
        return True
    return age > max_age_days


def update_prices(item_ids: list[str], creds: Credentials, region: str, conditions: list[str],
                  currency: str, max_age_days: int, progress: Callable[[float, str], None],
                  log: Callable[[str], None], cancel: threading.Event) -> tuple[int, int]:
    """Fetch missing / outdated prices. Returns (updated, still_missing)."""
    prices = load_prices()
    todo = [i for i in item_ids if stale(prices.get(i), region, max_age_days, conditions, currency)]
    if not todo:
        progress(1.0, "Alle Preise sind aktuell")
        return 0, 0
    per = calls_per_figure(region, conditions)
    budget = max(0, SAFE_LIMIT - calls_today()) // per
    log(f"Lade Preise für {len(todo)} Figuren ({per} API-Abfragen pro Figur, "
        f"heute noch Platz für ca. {budget} Figuren) …")
    client = PriceClient(creds, currency=currency, cancel=cancel)
    done = 0
    try:
        for n, item_id in enumerate(todo, 1):
            if calls_today() + per > SAFE_LIMIT:
                log("Tageslimit der BrickLink-API fast erreicht – der Rest folgt morgen.")
                break
            prices[item_id] = client.price_for(item_id, region, conditions)
            done += 1
            if n % 10 == 0:
                save_prices(prices)
            progress(n / len(todo), f"Preise {n}/{len(todo)}")
    finally:
        save_prices(prices)
    return done, len(todo) - done


# ------------------------------------------------------------ formatting

def money(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "–"
    sym = {"EUR": "€", "CHF": "CHF", "USD": "$", "GBP": "£"}.get(currency, currency)
    txt = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{txt} {sym}"


def main_price(rec: dict | None, prefer: str = "U") -> float | None:
    """The price shown on cards: preferred condition, else the other one."""
    if not rec:
        return None
    for cond in (prefer, "N" if prefer == "U" else "U"):
        p = rec.get(cond) or {}
        if p.get("avg") is not None:
            return p["avg"]
    return None
