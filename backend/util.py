from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"          # committed: makes the demo instant + free on first open
CACHE.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("finn.cache")
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


# Parsed-object memo, keyed on (mtime, size): JSON parsing was 60-75% of request time.
# Objects handed out with shared=True are shared across requests and must be treated as
# read-only; writers (the feed refresh) always take a private parse.
_MEMO: "OrderedDict[str, tuple[int, int, Any]]" = OrderedDict()
_MEMO_MAX = 64
_guard = threading.Lock()


def read_cache(key: str, shared: bool = False) -> Any | None:
    p = _path(key)
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    if shared:
        with _guard:
            m = _MEMO.get(key)
            if m and m[0] == st.st_mtime_ns and m[1] == st.st_size:
                _MEMO.move_to_end(key)
                return m[2]
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if shared:
        with _guard:
            _MEMO[key] = (st.st_mtime_ns, st.st_size, v)
            _MEMO.move_to_end(key)
            while len(_MEMO) > _MEMO_MAX:
                _MEMO.popitem(last=False)
    return v


def write_cache(key: str, value: Any) -> None:
    p = _path(key)
    tmp = p.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)
    with _guard:
        _MEMO.pop(key, None)


# ----------------------------------------------------------------------------- fetch-through cache

_key_locks: dict[str, threading.Lock] = {}
_inflight: set[str] = set()
_failed_at: dict[str, float] = {}
RETRY_AFTER_FAIL_S = 600


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        return _key_locks.setdefault(key, threading.Lock())


def _fresh(p: Path, max_age_h: float | None) -> bool:
    try:
        return max_age_h is None or (time.time() - p.stat().st_mtime) < max_age_h * 3600
    except FileNotFoundError:
        return False


def _revalidate(key: str, fn: Callable[[], Any], max_age_h: float | None) -> None:
    """Refresh one key in the background, at most once at a time, and not again for
    10 minutes after a failure (so a blocked source isn't hammered on every request)."""
    with _guard:
        if key in _inflight or time.time() - _failed_at.get(key, 0) < RETRY_AFTER_FAIL_S:
            return
        _inflight.add(key)

    def run():
        try:
            with _lock_for(key):
                if not _fresh(_path(key), max_age_h):
                    write_cache(key, fn())
        except Exception as e:  # noqa: BLE001
            _failed_at[key] = time.time()
            log.warning("background refresh of %s failed: %s", key, str(e)[:120])
        finally:
            with _guard:
                _inflight.discard(key)

    threading.Thread(target=run, daemon=True, name=f"swr:{key[:40]}").start()


def cache_json(key: str, fn: Callable[[], Any], max_age_h: float | None = None, swr: bool = False) -> Any:
    """Fetch-through disk cache. Results are shared: treat them as read-only.

    * fresh hit  -> served from memory/disk.
    * stale hit  -> swr=True (request paths): serve the stale copy now, refresh in the
                    background. swr=False (background jobs): refresh now.
    * concurrent misses for one key collapse into a single fetch (per-key lock).
    * if a refresh fails we still serve the stale copy: a source hiccup never breaks the app."""
    p = _path(key)
    if p.exists():
        if _fresh(p, max_age_h) or swr:
            v = read_cache(key, shared=True)
            if v is not None:
                if swr and not _fresh(p, max_age_h):
                    _revalidate(key, fn, max_age_h)
                return v
    with _lock_for(key):
        if _fresh(p, max_age_h):  # someone else refreshed it while we waited
            v = read_cache(key, shared=True)
            if v is not None:
                return v
        try:
            v = fn()
        except Exception:
            v = read_cache(key, shared=True)
            if v is not None:
                return v
            raise
        write_cache(key, v)
        return v
