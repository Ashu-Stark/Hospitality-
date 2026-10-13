"""Render's free servers sleep after about 15 minutes without traffic; the first call then takes 30-60 seconds.

Two parts:
  * retry rules for the low-level HTTP helpers (lib.platform._send, lib.api_client._http): one retry with a longer
    timeout on a timeout or a 502/503/504 from the host while the server boots. A request that may already have been
    processed (a POST/PUT/PATCH/DELETE that timed out while reading the answer) is NOT retried, so nothing is done twice.
  * ensure_awake(): called once per page run (app.py) before the first real call. If a server has not answered for a
    while it pings /health in a background thread; when the ping is slow, a fixed-position notice ("Waking up the server,
    this can take about 30 seconds…") is shown and removed again, so the page layout does not jump.
Local and embedded servers never sleep, so nothing here runs for them (tests and offline runs are unaffected).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import requests

AWAKE_FOR_S = 600  # ASSUMED: Render sleeps after ~15 min idle; re-check after 10 min without a successful call
SHOW_AFTER_S = 1.5  # show the notice only when the ping is actually slow
FIRST_TIMEOUT_S = 30.0
RETRY_TIMEOUT_S = 90.0
RETRY_STATUSES = {502, 503, 504}  # what Render's proxy returns while the app is still starting
MESSAGE = "Waking up the server, this can take about 30 seconds…"

_last_ok: dict[str, float] = {}  # base URL -> time of the last successful answer (process-wide; servers are shared)
_lock = threading.Lock()


def mark_ok(base: str) -> None:
    with _lock:
        _last_ok[base] = time.time()


def recently_ok(base: str) -> bool:
    return time.time() - _last_ok.get(base, 0.0) < AWAKE_FOR_S


def is_local(base: str) -> bool:
    b = base.lower()
    return not b.startswith("http") or "localhost" in b or "127.0.0.1" in b


def request(method: str, url: str, base: str, *, timeout: float | None = None, session=None, **kw) -> requests.Response:
    """requests.request with the wake-up retry rules. Raises requests exceptions like requests does."""
    send = (session or requests).request
    first = timeout or FIRST_TIMEOUT_S
    safe = method.upper() in ("GET", "HEAD", "OPTIONS")
    try:
        r = send(method, url, timeout=first, **kw)
    except requests.exceptions.ConnectTimeout:  # never reached the server: always safe to retry
        r = None
    except requests.exceptions.ReadTimeout:
        if not safe:  # the server may have done it already; do not do it twice
            raise
        r = None
    except requests.exceptions.ConnectionError:  # refused / reset while the host swaps the instance in
        r = None
    if r is not None and r.status_code not in RETRY_STATUSES:
        if r.status_code < 500:
            mark_ok(base)
        return r
    r = send(method, url, timeout=max(RETRY_TIMEOUT_S, first), **kw)
    if r.status_code < 500:
        mark_ok(base)
    return r


def ensure_awake(base: str, health_path: str = "/health") -> None:
    """Ping a remote server that may be asleep; show the waking-up notice while the ping is slow. Never raises."""
    if is_local(base) or recently_ok(base):
        return
    box: dict = {}

    def ping() -> None:
        try:
            box["r"] = request("GET", base.rstrip("/") + health_path, base, timeout=FIRST_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - the page's own calls report problems in plain words
            box["e"] = e

    t = threading.Thread(target=ping, daemon=True)
    t.start()
    t.join(SHOW_AFTER_S)
    if not t.is_alive():
        return
    _show_while(lambda: t.join(FIRST_TIMEOUT_S + RETRY_TIMEOUT_S))


def _show_while(wait: Callable[[], None]) -> None:
    import streamlit as st

    slot = st.empty()
    slot.markdown(notice_html(), unsafe_allow_html=True)
    try:
        wait()
    finally:
        slot.empty()


def notice_html(text: str = MESSAGE) -> str:
    """A small fixed banner at the top of the screen (position: fixed, so the page underneath does not move)."""
    return (
        "<style>.ss-wake{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:999999;background:#0b0b0b;"
        "color:#fff;border-radius:999px;padding:10px 18px;font-size:.9rem;display:flex;gap:10px;align-items:center;"
        "box-shadow:0 6px 24px rgba(0,0,0,.18);max-width:calc(100vw - 32px)}"
        ".ss-wake i{width:14px;height:14px;border-radius:50%;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;"
        "flex:none;animation:sswake 0.9s linear infinite}@keyframes sswake{to{transform:rotate(360deg)}}</style>"
        f'<div class="ss-wake" role="status" aria-live="polite"><i></i><span>{text}</span></div>'
    )
