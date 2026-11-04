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


_BLOCK_MARKERS = (
    "quota exceeded",
    "too many requests",
    "just a moment...",
    "cf-chl-",
    "challenge-platform",
    "access denied",
    "oops, sorry",
    "you have been blocked",
)


def looks_blocked(status: int, text: str) -> bool:
    if status in (403, 429, 503):
        return True
    head = text[:6000].lower()
    # Real catalog pages are large; block pages are small.
    return len(text) < 20000 and any(m in head for m in _BLOCK_MARKERS)


class Client:
    """requests.Session wrapper.

    * caches HTML pages on disk (default 7 days) so a second run hardly
      touches BrickLink,
    * waits between page requests,
    * backs off and retries when BrickLink rate-limits us,
    * falls back to curl_cffi (browser TLS fingerprint) when the plain
      client is blocked and curl_cffi is installed.
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
        self._cffi = None
        self._last_page = 0.0
        self._lock = threading.Lock()
        self._local = threading.local()   # one session per image thread
        self.page_requests = 0

    @staticmethod
    def _new_session() -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        # BrickLink shows a cookie banner; pretend it was answered.
        s.cookies.set("blCookieConsent", "Y", domain=".bricklink.com")
        return s

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

    def _cffi_get(self, url: str, timeout: float):
        if self._cffi is False:
            return None
        if self._cffi is None:
            try:
                from curl_cffi import requests as creq  # type: ignore
                self._cffi = creq.Session(impersonate="chrome")
                self.log("Wechsle auf Browser-Modus (curl_cffi) …")
            except Exception:  # not installed / not bundled
                self._cffi = False
                return None
        return self._cffi.get(url, timeout=timeout,
                              headers={"Accept-Language": "en-US,en;q=0.9"})

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
            status, text = self._fetch_text(url)
            if status == 200 and not looks_blocked(status, text):
                cpath.write_text(text, encoding="utf-8")
                return text
            if status == 404:
                return ""
            if attempt >= len(delays):
                raise BlockedError(
                    "BrickLink blockiert gerade die Anfragen (HTTP %s). Bitte "
                    "15–30 Minuten warten und erneut starten – bereits geladene "
                    "Seiten bleiben gespeichert." % status)
            wait = delays[attempt]
            attempt += 1
            self.log(f"BrickLink bremst (HTTP {status}) – warte {wait} s und versuche es erneut …")
            self._sleep(wait)

    def _fetch_text(self, url: str) -> tuple[int, str]:
        try:
            r = self._session.get(url, timeout=40)
            status, text = r.status_code, r.text
        except requests.RequestException as exc:
            self.log(f"Netzwerkfehler: {exc}")
            return 0, ""
        if status == 200 and not looks_blocked(status, text):
            return status, text
        # Blocked by bot protection? Try a browser-like TLS fingerprint.
        try:
            r2 = self._cffi_get(url, timeout=40)
        except Exception as exc:  # pragma: no cover - network dependent
            self.log(f"Browser-Modus fehlgeschlagen: {exc}")
            r2 = None
        if r2 is not None:
            return r2.status_code, r2.text
        return status, text

    def get_binary(self, url: str, timeout: float = 30) -> bytes | None:
        """GET an image. Returns None on 404 / non-image answers."""
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = self._new_session()
        for attempt in range(3):
            self._check_cancel()
            try:
                r = session.get(url, timeout=timeout)
            except requests.RequestException:
                self._sleep(2 + attempt * 3)
                continue
            if r.status_code == 200 and r.content and \
                    r.headers.get("Content-Type", "image").startswith("image"):
                return r.content
            if r.status_code in (404, 410):
                return None
            if r.status_code in (403, 429, 503):
                self._sleep(5 + attempt * 10)
                continue
            return None
        return None
