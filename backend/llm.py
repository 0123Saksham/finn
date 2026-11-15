"""One door to the models.

* Routing by tier: 'lite' (bulk triage) -> 'fast' (document extraction) -> 'deep'
  (multi-document reasoning). Callers ask for a tier, never a model name.
* Content-addressed disk cache: the same prompt + document is never paid for twice.
  Filings are immutable, so cache hits are the common case after the first run.
* Every call is metered (tokens + indicative $), so the UI can show what an answer cost.
* Rate-limit aware: retries with backoff, then degrades a tier instead of failing.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from . import config
from .util import h, read_cache, write_cache

log = logging.getLogger("finn.llm")
_client = None
_lock = threading.Lock()
LEDGER: dict[str, dict[str, float]] = {}

MODELS = {"lite": config.MODEL_LITE, "fast": config.MODEL_FAST, "deep": config.MODEL_DEEP}
POOLS = config.MODEL_POOLS
FALLBACK = {"deep": "fast", "fast": "lite", "lite": None}


class LLMUnavailable(RuntimeError):
    pass


# Free-tier quotas are per model, so each tier is a pool of interchangeable models.
# When one model's daily quota runs out we move along the pool; only when the whole
# pool is dry do we degrade to a cheaper tier. Quotas reset at midnight Pacific.
_EXHAUSTED: dict[str, str] = {}


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - 8 * 3600))


def _exhaust(model: str) -> None:
    _EXHAUSTED[model] = _today()
    log.warning("model %s out of daily quota", model)


def _pool(tier: str) -> list[str]:
    return [m for m in config.MODEL_POOLS[tier] if _EXHAUSTED.get(m) != _today()]


def _reset() -> None:
    global _client
    _client = None


def available() -> bool:
    return bool(config.GEMINI_API_KEY)


def client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise LLMUnavailable("GEMINI_API_KEY not set")
        from google import genai
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _record(tier: str, model: str, usage: dict, meter: list | None, cached: bool):
    pin, pout = config.PRICES[tier]
    cost = (usage.get("in", 0) * pin + usage.get("out", 0) * pout) / 1e6
    row = {"tier": tier, "model": model, "in": usage.get("in", 0), "out": usage.get("out", 0),
           "usd": 0.0 if cached else round(cost, 6), "cached": cached}
    if meter is not None:
        meter.append(row)
    with _lock:
        agg = LEDGER.setdefault(tier, {"calls": 0, "cached": 0, "in": 0, "out": 0, "usd": 0.0})
        agg["calls"] += 1
        agg["cached"] += int(cached)
        if not cached:
            agg["in"] += row["in"]
            agg["out"] += row["out"]
            agg["usd"] += row["usd"]


def _parse_json(text: str) -> Any:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            return json.loads(m.group(1))
        raise


def call(tier: str, prompt: str, *, system: str | None = None, pdf: bytes | None = None,
         as_json: bool = True, temperature: float = 0.1, meter: list | None = None,
         think: bool = False, cache: bool = True) -> Any:
    model = _pool(tier)[0] if _pool(tier) else MODELS[tier]
    key = "llm/" + h("|".join([tier, system or "", prompt, h(pdf.hex()[:20000] + str(len(pdf))) if pdf else "", str(as_json)]))
    if cache:
        hit = read_cache(key)
        if hit is not None:
            _record(tier, hit.get("model", model), hit.get("usage", {}), meter, cached=True)
            return hit["output"]

    from google.genai import types
    parts: list[Any] = []
    if pdf:
        parts.append(types.Part.from_bytes(data=pdf, mime_type="application/pdf"))
    parts.append(prompt)

    cfg: dict[str, Any] = {"temperature": temperature}
    if system:
        cfg["system_instruction"] = system
    if as_json:
        cfg["response_mime_type"] = "application/json"
    level = "high" if think else config.THINKING.get(tier)
    if level:
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=level)

    last_err: Exception | None = None
    for model in _pool(tier):
        for attempt in range(3):
            try:
                resp = client().models.generate_content(
                    model=model, contents=parts, config=types.GenerateContentConfig(**cfg))
                text = resp.text or ""
                out = _parse_json(text) if as_json else text.strip()
                if as_json and isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
                    out = out[0]  # some models wrap a single object in a list
                um = resp.usage_metadata
                usage = {"in": getattr(um, "prompt_token_count", 0) or 0,
                         "out": (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)}
                _record(tier, model, usage, meter, cached=False)
                if cache:
                    write_cache(key, {"model": model, "usage": usage, "output": out, "at": time.time()})
                return out
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e)
                if "client has been closed" in msg:
                    _reset()
                    continue
                if "thinking" in msg.lower() and "thinking_config" in cfg:
                    cfg.pop("thinking_config")
                    continue
                if "PerDay" in msg or "per day" in msg.lower() or "NOT_FOUND" in msg:
                    _exhaust(model)  # this model's free daily quota is gone: next model in the pool
                    break
                if any(c in msg for c in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500")):
                    time.sleep(min(20, 3 * (attempt + 1)))
                    continue
                if isinstance(e, json.JSONDecodeError):
                    continue
                break
    nxt = FALLBACK.get(tier)
    if nxt:
        log.warning("tier %s exhausted (%s); degrading to %s", tier, str(last_err)[:120], nxt)
        return call(nxt, prompt, system=system, pdf=pdf, as_json=as_json, temperature=temperature,
                    meter=meter, think=think or tier == "deep", cache=cache)
    raise LLMUnavailable(str(last_err)[:300])


def summarize_meter(meter: list) -> dict[str, Any]:
    out = {"calls": len(meter), "cached": sum(1 for m in meter if m["cached"]),
           "tokens": sum(m["in"] + m["out"] for m in meter if not m["cached"]),
           "usd": round(sum(m["usd"] for m in meter), 4), "by_tier": {}}
    for m in meter:
        t = out["by_tier"].setdefault(m["tier"], {"calls": 0, "model": m["model"]})
        t["calls"] += 1
    return out
