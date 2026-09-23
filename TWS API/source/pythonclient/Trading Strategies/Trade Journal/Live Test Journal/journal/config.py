"""Central configuration: paths, instruments, multipliers, and tunable thresholds."""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------
# The package lives inside the "Trade Journal" folder; that folder is our root.
ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = ROOT / "ZTH Trade Tracker - AB.xlsx"
TRADE_SHEET = "Trade Tracker - Eval"
MULTIPLIER_SHEET = "Multipliers"
REPORTS_DIR = ROOT / "reports"
BACKUP_DIR = ROOT / "backups"
CACHE_DIR = ROOT / ".cache"

# --- Contract multipliers ($ per full point) -------------------------------
# Mirrors the workbook's "Multipliers" sheet, with MYM added (Micro Dow).
MULTIPLIERS = {
    "ES": 50, "MES": 5,
    "NQ": 20, "MNQ": 2,
    "YM": 5, "MYM": 0.5,
    "RTY": 50, "M2K": 5,
    "GC": 100, "MGC": 10,
    "CL": 1000, "MCL": 100,
    "QM": 500,
}

# Known contract roots, longest first so "MNQ" matches before "NQ", etc.
ROOTS = sorted(MULTIPLIERS.keys(), key=len, reverse=True)

# --- Yahoo Finance continuous-future tickers -------------------------------
# Micro and full-size contracts share the same underlying chart.
YAHOO_MAP = {
    "ES": "ES=F", "MES": "ES=F",
    "NQ": "NQ=F", "MNQ": "NQ=F",
    "YM": "YM=F", "MYM": "YM=F",
    "RTY": "RTY=F", "M2K": "RTY=F",
    "GC": "GC=F", "MGC": "GC=F",
    "CL": "CL=F", "MCL": "CL=F",
    "QM": "CL=F",
}

# --- Behavior-analysis thresholds (tune to your style) ---------------------
OVERTRADING_PER_DAY = 6          # more trades than this in one day = flag
REVENGE_WINDOW_MIN = 15          # a new trade within N min of a loss = suspect
REVENGE_SIZE_FACTOR = 1.0        # ...and size >= factor * previous size
STOP_SLIPPAGE_RR = -1.15         # realized RR worse than this = stop overrun
CUT_WINNER_FRACTION = 0.5        # win realized RR < fraction*targeted = cut early
MIN_SAMPLE_FOR_EDGE = 3          # ignore buckets with fewer trades than this

# --- Claude backends -------------------------------------------------------
# Two ways to reach Claude, tried in this order:
#   1. The `claude` CLI (Claude Code) using your existing login  -> NO API key.
#   2. The Anthropic HTTP API, if ANTHROPIC_API_KEY is set.
# Force one with JOURNAL_AI_BACKEND = "cli" | "api" | "auto" (default auto).
AI_BACKEND = os.environ.get("JOURNAL_AI_BACKEND", "auto").lower()

# CLI backend: model alias understood by `claude --model` (e.g. sonnet, opus).
# "sonnet" = the current Claude Sonnet; set JOURNAL_CLI_MODEL=opus for max depth.
CLI_MODEL = os.environ.get("JOURNAL_CLI_MODEL", "sonnet")
CLI_TIMEOUT = int(os.environ.get("JOURNAL_CLI_TIMEOUT", "300"))

# API backend (only used if an API key is present).
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
ANTHROPIC_MODEL = os.environ.get("JOURNAL_MODEL", "claude-opus-5")
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
AI_MAX_TOKENS = 4096

# --- Data endpoints --------------------------------------------------------
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
HTTP_UA = "Mozilla/5.0 (compatible; LocalTradeJournal/1.0)"
HTTP_TIMEOUT = 20


def root_from_symbol(symbol: str) -> str | None:
    """Map a Tradovate/exchange symbol like 'MNQU6' or 'MGCZ6' to its root."""
    if not symbol:
        return None
    s = str(symbol).strip().upper()
    for root in ROOTS:  # longest-first
        if s.startswith(root):
            rest = s[len(root):]
            # rest should be a month-letter + year-digit(s), e.g. 'U6' or 'Z26'
            if rest == "" or (rest[0] in "FGHJKMNQUVXZ" and rest[1:].isdigit()):
                return root
    # Fallback: it may already be a bare root.
    return s if s in MULTIPLIERS else None


def load_dotenv() -> None:
    """Minimal .env loader (no python-dotenv dependency)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
