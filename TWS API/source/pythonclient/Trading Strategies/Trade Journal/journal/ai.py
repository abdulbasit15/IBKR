"""Claude coaching over the computed metrics + market/news context.

Two backends, tried in order (configurable via JOURNAL_AI_BACKEND):

1. **CLI backend (default, no API key):** shells out to the `claude` CLI
   (Claude Code) using your existing login. Works wherever you're logged into
   Claude Code — no Anthropic API key required.
2. **API backend:** raw HTTP to the Messages API, used only when
   ANTHROPIC_API_KEY is set. (Raw HTTP because the `anthropic` SDK can't be
   pip-installed on this locked-down network.)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from . import config

SYSTEM_PROMPT = (
    "You are an elite futures-trading performance coach reviewing a discretionary "
    "trader's journal. They trade index and commodity futures (MNQ/NQ, MES/ES, "
    "MYM/YM, MGC/GC, MCL/CL) intraday. You are given computed statistics, "
    "detected behavior flags, per-setup/instrument/time breakdowns, the daily "
    "market context for the days traded, and relevant economic-calendar events.\n\n"
    "Write a focused, honest, actionable review. Be specific and quantitative — "
    "cite the trader's own numbers. Do NOT give generic advice. Answer directly "
    "in markdown (do not use any tools) with these sections:\n"
    "## Overall Assessment\n"
    "## What's Working\n"
    "## Behavioral Patterns & Leaks\n"
    "## Market & News Context\n"
    "## Instrument & Setup Notes\n"
    "## Top 3 Actionable Changes\n\n"
    "This is trading-performance coaching only, not investment advice, and never "
    "a recommendation to buy or sell any specific security."
)


# --- Prompt assembly -------------------------------------------------------
def _payload(metrics: dict, market: dict, news: dict, recent: list) -> dict:
    def slim_market(m):
        return {k: v for k, v in (m or {}).items()
                if k in ("date", "day_direction", "range_vs_avg", "gap",
                         "body_pct_of_range", "available")}

    return {
        "summary": metrics["summary"],
        "behavior_flags": metrics["behavior_flags"],
        "by_setup": metrics["by_setup"],
        "by_instrument": metrics["by_instrument"],
        "by_direction": metrics["by_direction"],
        "by_hour": metrics["by_hour"],
        "by_dayofweek": metrics["by_dayofweek"],
        "market_context": {f"{k[0]} {k[1]}": slim_market(v)
                           for k, v in (market or {}).items()},
        "news_context": {k: v for k, v in (news or {}).items() if v},
        "recent_trades": recent,
    }


def build_prompt(metrics, market, news, recent) -> str:
    data = _payload(metrics, market, news, recent)
    return (
        "Here is my trading data as JSON. Review it and coach me.\n\n"
        "```json\n" + json.dumps(data, indent=2, default=str) + "\n```"
    )


# --- Backend selection -----------------------------------------------------
def _cli_path() -> str | None:
    return shutil.which("claude") or shutil.which("claude.cmd")


def _api_key() -> str | None:
    return os.environ.get(config.ANTHROPIC_API_KEY_ENV)


def active_backend() -> tuple[str, str | None]:
    """Return (backend, model_label) for whichever backend will be used."""
    pref = config.AI_BACKEND
    have_key, have_cli = bool(_api_key()), bool(_cli_path())
    if pref == "api" and have_key:
        return "api", config.ANTHROPIC_MODEL
    if pref == "cli" and have_cli:
        return "cli", config.CLI_MODEL
    if pref == "auto":
        if have_cli:
            return "cli", config.CLI_MODEL
        if have_key:
            return "api", config.ANTHROPIC_MODEL
    return "none", None


def backend_label() -> str:
    b, m = active_backend()
    if b == "cli":
        return f"claude CLI · {m}"
    if b == "api":
        return f"API · {m}"
    return "none"


# --- CLI backend -----------------------------------------------------------
def call_cli(prompt: str) -> str:
    exe = _cli_path()
    if not exe:
        return "[AI skipped] `claude` CLI not found on PATH."
    try:
        proc = subprocess.run(
            [exe, "-p", "--model", config.CLI_MODEL,
             "--append-system-prompt", SYSTEM_PROMPT,
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True,
            encoding="utf-8", timeout=config.CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"[AI error] claude CLI timed out after {config.CLI_TIMEOUT}s."
    except Exception as e:
        return f"[AI error] {type(e).__name__}: {e}"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = ((proc.stderr or "").strip() or out or "no output")[:400]
        hint = ""
        if "log" in err.lower():
            hint = " — run `claude` in a terminal and `/login`, then retry."
        return f"[AI error via claude CLI] {err}{hint}"
    return out


# --- API backend -----------------------------------------------------------
def call_api(prompt: str) -> str:
    key = _api_key()
    if not key:
        return "[AI skipped] No ANTHROPIC_API_KEY set."
    body = json.dumps({
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": config.AI_MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        config.ANTHROPIC_URL, data=body, method="POST",
        headers={"x-api-key": key,
                 "anthropic-version": config.ANTHROPIC_VERSION,
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return f"[AI error] HTTP {e.code}: {e.read().decode('utf-8','ignore')[:400]}"
    except Exception as e:
        return f"[AI error] {type(e).__name__}: {e}"
    if resp.get("stop_reason") == "refusal":
        return "[AI refusal] The model declined to respond."
    parts = [b.get("text", "") for b in resp.get("content", [])
             if b.get("type") == "text"]
    return "\n".join(p for p in parts if p).strip() or "[AI returned no text]"


# --- Public entry ----------------------------------------------------------
def coach(metrics, market, news, recent) -> str:
    backend, _ = active_backend()
    prompt = build_prompt(metrics, market, news, recent)
    if backend == "cli":
        return call_cli(prompt)
    if backend == "api":
        return call_api(prompt)
    return ("[AI skipped] No Claude backend available. Either log into the "
            "`claude` CLI (Claude Code) or set ANTHROPIC_API_KEY in a .env file.")
