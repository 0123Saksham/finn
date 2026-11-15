"""Portfolio, defaults and model routing. Everything an operator would tune lives here."""
import os

from dotenv import load_dotenv

load_dotenv()

# Mock portfolio: 18 NSE names across sectors and sizes (mega-cap to mid-cap),
# chosen so a normal week contains every kind of event worth filtering.
# weight = % of portfolio value (used to rank what matters to *this* investor).
PORTFOLIO = [
    {"symbol": "RELIANCE",   "sector": "Energy & Retail",      "weight": 9.0},
    {"symbol": "HDFCBANK",   "sector": "Private Bank",         "weight": 9.0},
    {"symbol": "BHARTIARTL", "sector": "Telecom",              "weight": 7.0},
    {"symbol": "LT",         "sector": "Infra & Engineering",  "weight": 7.0},
    {"symbol": "BAJFINANCE", "sector": "NBFC",                 "weight": 6.0},
    {"symbol": "SUNPHARMA",  "sector": "Pharma",               "weight": 5.0},
    {"symbol": "TITAN",      "sector": "Consumer",             "weight": 5.0},
    {"symbol": "HAL",        "sector": "Defence",              "weight": 6.0},
    {"symbol": "TRENT",      "sector": "Retail",               "weight": 5.0},
    {"symbol": "ASIANPAINT", "sector": "Paints",               "weight": 4.0},
    {"symbol": "APOLLOHOSP", "sector": "Healthcare",           "weight": 5.0},
    {"symbol": "TATASTEEL",  "sector": "Metals",               "weight": 4.0},
    {"symbol": "BEL",        "sector": "Defence Electronics",  "weight": 5.0},
    {"symbol": "POLYCAB",    "sector": "Cables & Wires",       "weight": 4.0},
    {"symbol": "IRCTC",      "sector": "Travel (PSU)",         "weight": 3.0},
    {"symbol": "DIXON",      "sector": "Electronics Mfg",      "weight": 4.0},
    {"symbol": "KPITTECH",   "sector": "Auto Software",        "weight": 3.0},
    {"symbol": "SUZLON",     "sector": "Renewables",           "weight": 4.0},
]
SYMBOLS = [p["symbol"] for p in PORTFOLIO]
WEIGHT = {p["symbol"]: p["weight"] for p in PORTFOLIO}
SECTOR = {p["symbol"]: p["sector"] for p in PORTFOLIO}

# Ad-hoc research demo set (outside the portfolio). The engine works on any NSE symbol.
RESEARCH_DEMO = ["INFY", "NYKAA", "DEEPAKNTR", "HINDALCO"]

# Default alert rules — the investor overrides these in the app.
DEFAULT_RULES = {
    "price_move_pct": 5.0,          # |1-day move| beyond this fires
    "volume_multiple": 2.0,         # volume vs 20-day average
    "categories": ["results", "M&A", "management_change", "fund_raise",
                   "litigation", "pledging", "credit_rating", "insider_trading"],
}

# --- Model routing -----------------------------------------------------------
# Tier 0 = rules/code (free). LLM tiers only where language understanding is needed.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Defaults are what Gemini's free tier serves today (Pro has no free quota). Set
# FINN_MODEL_DEEP=gemini-3.1-pro-preview on a paid key to upgrade only the judgement step.
MODEL_LITE = os.getenv("FINN_MODEL_LITE", "gemini-3.5-flash-lite")  # bulk triage, one-liners, bios
MODEL_FAST = os.getenv("FINN_MODEL_FAST", "gemini-3.5-flash")       # PDF/transcript extraction, thinking=low
MODEL_DEEP = os.getenv("FINN_MODEL_DEEP", "gemini-3.5-flash")       # promise-vs-delivery reasoning, thinking=high
THINKING = {"lite": None, "fast": "low", "deep": "high"}
_pool = lambda env, first, rest: [m for m in [first] + [x for x in os.getenv(env, rest).split(",") if x] if m]  # noqa: E731
MODEL_POOLS = {
    "lite": _pool("FINN_POOL_LITE", MODEL_LITE, "gemini-flash-lite-latest,gemini-3.1-flash-lite"),
    "fast": _pool("FINN_POOL_FAST", MODEL_FAST, "gemini-3-flash-preview,gemini-flash-latest"),
    "deep": _pool("FINN_POOL_DEEP", MODEL_DEEP, "gemini-3-flash-preview,gemini-flash-latest"),
}

# Indicative paid-tier prices (USD / 1M tokens: input, output) for the cost ledger.
PRICES = {
    "lite": (0.10, 0.40),
    "fast": (0.30, 2.50),
    "deep": (0.30, 2.50),
}

REFRESH_MINUTES = int(os.getenv("FINN_REFRESH_MINUTES", "20"))
