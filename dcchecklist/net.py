"""Polite HTTP client for BrickLink with caching, throttling and retries."""
from __future__ import annotations

import hashlib
import random
import threading
import time
from pathlib import Path
from typing import Callable

import requests

from . import config
from .storage import cache_dir


class BlockedError(RuntimeError):
    """BrickLink refused us (rate limit / bot protection)."""


class CancelledError(RuntimeError):
    pass


class NetworkError(RuntimeError):
    """No connection at all (offline, firewall, DNS)."""


_BLOCK_MARKERS = (
    "quota exceeded",
    "too many requests",
    "access denied",
    "you have been blocked",
)
_CHALLENGE_MARKERS = ("awswaf", "gokuprops", "challenge.js", "captcha.js")

CHALLENGE_MESSAGE = (
    "BrickLink verlangt für die Katalog-Listen gerade eine Browser-Prüfung "
    "(Bot-Schutz). Das Programm umgeht diesen Schutz nicht und hört deshalb hier auf. "
    "Bereits geladene Seiten bleiben gespeichert – später erneut versuchen."
)


def is_challenge(status: int, text: str, headers: dict | None = None) -> bool:
    """BrickLink's firewall asks for a JavaScript check (HTTP 202 / 405)."""
    if headers and str(headers.get("x-amzn-waf-action", "")).lower() in ("challenge", "captcha"):
        return True
    if status in (202, 405):
        return True
    head = text[:20000].lower()
    return len(text) < 30000 and any(m in head for m in _CHALLENGE_MARKERS)


def looks_blocked(status: int, text: str) -> bool:
    if status in (403, 429, 503) or is_challenge(status, text):
        return True
    head = text[:6000].lower()
    return len(text) < 20000 and any(m in head for m in _BLOCK_MARKERS)


class Client:
    """requests.Session wrapper.

    * caches HTML pages on disk (default 7 days) so a second run hardly
      touches BrickLink,
    * waits between page requests,
    * backs off and retries when BrickLink rate-limits us,
    * stops with a clear message when BrickLink asks for a browser check.
    """

    def __init__(self, log: Callable[[str], None] | None = None,
                 cancel: threading.Event | None = None,
                 use_cache: bool = True,
                 page_delay: tuple[float, float] = config.PAGE_DELAY_SECONDS):
        self.log = log or (lambda _m: None)
        self.cancel = cancel or threading.Event()
        self.use_cache = use_cache
        self.page_delay = page_delay
        self._session = self._new_session()
        self._last_page = 0.0
        self._lock = threading.Lock()
        self._local = threading.local()   # one session per image thread
        self.page_requests = 0

    @staticmethod
    def _new_session() -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        return s

    def close(self) -> None:
        """Nothing to release; kept so callers can always close a client."""

    # ------------------------------------------------------------------ utils
    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise CancelledError("Abgebrochen")

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._check_cancel()
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def _throttle(self) -> None:
        with self._lock:
            wait = random.uniform(*self.page_delay) - (time.monotonic() - self._last_page)
            if wait > 0:
                self._sleep(wait)
            self._last_page = time.monotonic()

    @staticmethod
    def _cache_path(url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return cache_dir("html") / f"{h}.html"

    # ------------------------------------------------------------- requests
    def get_page(self, url: str, max_age_days: float = config.HTML_CACHE_DAYS) -> str:
        """GET an HTML page from www.bricklink.com (cached + throttled)."""
        cpath = self._cache_path(url)
        if self.use_cache and cpath.exists():
            age = (time.time() - cpath.stat().st_mtime) / 86400
            if age <= max_age_days:
                return cpath.read_text(encoding="utf-8", errors="replace")

        delays = [20, 60, 180]
        attempt = 0
        while True:
            self._check_cancel()
            self._throttle()
            self.page_requests += 1
            status, text, headers = self._fetch_text(url)
            if status == 200 and not looks_blocked(status, text):
                cpath.write_text(text, encoding="utf-8")
                return text
            if status == 404:
                return ""
            if is_challenge(status, text, headers):
                raise BlockedError(CHALLENGE_MESSAGE)
            if attempt >= len(delays):
                raise BlockedError(
                    "BrickLink blockiert gerade die Anfragen (HTTP %s). Bitte "
                    "15–30 Minuten warten und erneut starten – bereits geladene "
                    "Seiten bleiben gespeichert." % status)
            wait = delays[attempt]
            attempt += 1
            self.log(f"BrickLink bremst (HTTP {status}) – warte {wait} s und versuche es erneut …")
            self._sleep(wait)

    def _fetch_text(self, url: str) -> tuple[int, str, dict]:
        try:
            r = self._session.get(url, timeout=40)
            return r.status_code, r.text, {k.lower(): v for k, v in r.headers.items()}
        except requests.RequestException as exc:
            self.log(f"Netzwerkfehler: {exc}")
            return 0, "", {}

    def get_binary(self, url: str, timeout: float = 30) -> bytes | None:
        """GET an image. Returns None on 404 / non-image answers."""
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = self._new_session()
        for attempt in range(3):
            self._check_cancel()
            try:
                r = session.get(url, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= 1:
                    raise NetworkError(str(exc)) from exc
                self._sleep(1.5)
                continue
            except requests.RequestException:
                return None
            ctype = r.headers.get("Content-Type", "image")
            if r.status_code == 200 and r.content and ctype.startswith("image"):
                return r.content
            if r.status_code in (404, 410):
                return None
            if r.status_code in (429, 503):
                self._sleep(5 + attempt * 10)
                continue
            return None
        return None
