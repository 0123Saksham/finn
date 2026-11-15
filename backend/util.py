from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"          # committed: makes the demo instant + free on first open
CACHE.mkdir(parents=True, exist_ok=True)

UA = "FINN-research-prototype/0.1 (+student build challenge)"
_client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=40)


def http_get(url: str, tries: int = 3) -> httpx.Response:
    err = None
    for i in range(tries):
        try:
            r = _client.get(url)
            if r.status_code == 429 or r.status_code >= 500:
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            err = e
            if e.response is not None and e.response.status_code in (403, 404):
                break
        except httpx.HTTPError as e:
            err = e
        time.sleep(1.5 * (i + 1))
    raise err  # type: ignore[misc]


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:20]


def _path(key: str) -> Path:
    safe = key.replace(":", "_").replace("?", "_").replace("&", "_")
    p = CACHE / f"{safe}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read_cache(key: str) -> Any | None:
    p = _path(key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def write_cache(key: str, value: Any) -> None:
    p = _path(key)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)


def cache_json(key: str, fn: Callable[[], Any], max_age_h: float | None = None) -> Any:
    """Disk cache. Stale entries are refreshed, but if the refresh fails we still
    serve the stale copy — a demo must never break because a source hiccuped."""
    p = _path(key)
    if p.exists():
        fresh = max_age_h is None or (time.time() - p.stat().st_mtime) < max_age_h * 3600
        if fresh:
            v = read_cache(key)
            if v is not None:
                return v
        try:
            v = fn()
            write_cache(key, v)
            return v
        except Exception:
            v = read_cache(key)
            if v is not None:
                return v
            raise
    v = fn()
    write_cache(key, v)
    return v
