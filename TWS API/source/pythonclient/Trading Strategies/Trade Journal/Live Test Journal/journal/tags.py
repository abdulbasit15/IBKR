"""Curated trade-journal tag taxonomy (7 categories).

Categories requested by the trader, seeded with sensible defaults drawn from the
ZTH Post-Challenge Reflection framework + trade-journal best practice. Each
category maps to its own column in the workbook, and the defaults are also
written to a "Tag Options" reference sheet.
"""
from __future__ import annotations

# Display/storage order — Setup first (it's the primary tag).
TAXONOMY = {
    "Setup": [
        "Break and Retest", "A+ setup", "Full confluence", "Breakout",
        "Breakdown", "Pullback", "Reversal", "Range fade",
        "Trend continuation", "VWAP bounce", "Support / Resistance",
    ],
    "Rules": [
        "Followed plan", "Broke a rule", "Within daily loss limit",
        "Hit daily loss limit", "Within max size", "Risked >1R per trade",
        "Traded planned session", "Waited for A+ only", "Stopped after 2 losses",
    ],
    "Market conditions": [
        "Trending up", "Trending down", "Ranging", "Choppy",
        "High volatility", "Low volatility", "News day", "Thin / overnight",
        "Strong trend", "Reversal day",
    ],
    "Emotion before trade": [
        "Calm", "Confident", "Focused", "FOMO", "Fear", "Greed",
        "Impatient", "Frustrated", "Bored", "Pressure to recover",
        "Tilted", "Anxious",
    ],
    "Process": [
        "Pre-market done", "Wrote entry reason", "A+ process day",
        "Cooled off between trades", "Journaled", "No pre-market",
        "Distracted", "Multitasking", "Rushed entry",
    ],
    "Mistakes": [
        "Revenge trade", "Oversized", "Moved stop", "Cut winner early",
        "Blew stop", "No confluence", "Early entry", "Late entry",
        "Overtraded", "Chased entry", "Out-of-plan", "No stop",
    ],
    "Learning": [
        "Wait for confluence", "Size down on news", "Let winners run",
        "Honor the stop", "Trade only A+", "Reduce overnight trading",
        "Stick to Pullbacks", "Take the 2R", "Be patient", "Smaller size",
    ],
}

# Every trade defaults to this setup when none is set.
DEFAULT_SETUP = "Break and Retest"

# Setup labels the old price-action auto-tagger produced — treated as
# unset "defaults" that may be replaced by DEFAULT_SETUP.
AUTO_SETUP_LABELS = {"Breakout", "Breakdown", "Pullback", "Reversal",
                     "With-trend", "Counter-trend", "BR"}

# Category -> workbook column key (see excel_io.COL).
CATEGORY_FIELD = {
    "Rules": "rules",
    "Market conditions": "market",
    "Emotion before trade": "emotion",
    "Setup": "setup",
    "Process": "process",
    "Mistakes": "mistakes",
    "Learning": "learning",
}

# The column keys, in category order — used when reading/writing/aggregating.
FIELD_KEYS = [CATEGORY_FIELD[c] for c in TAXONOMY]

# Reverse: column key -> category name.
FIELD_CATEGORY = {v: k for k, v in CATEGORY_FIELD.items()}

# Column header text for each field (written into the sheet).
FIELD_HEADER = {
    "setup": "Trade Setup", "mistakes": "Mistakes", "rules": "Rules",
    "market": "Market Conditions", "emotion": "Emotion Before Trade",
    "process": "Process", "learning": "Learning",
}

TAG_CATEGORY = {t.lower(): cat for cat, tags in TAXONOMY.items() for t in tags}

# --- Trading rules checklist (seed defaults) ------------------------------
# Hard rules = must not be broken. Other rules = judgment calls, overridable.
DEFAULT_HARD_RULES = [
    "Check Economic News.",
    "Mark Levels before market open. Mark the opening print as a 4/5 Level.",
    "Create a plan — only long if 1H is uptrend; only short if 1H is downtrend.",
    ("Pick the levels you want to go long/short off based on that analysis. "
     "Label the levels AND where the analysis could switch — e.g. an uptrend "
     "holds until a level breaks; if the hourly candle closes beneath it, bias "
     "can flip down. Mark out both."),
    "Trade only after 9:45. Don't trade after 12 pm.",
    "Target 2–2.5 Risk to Reward.",
    ("Aim for 1–3 trades a day with a predefined daily stop loss and an overall "
     "assumed profit target."),
]
DEFAULT_OTHER_RULES = [
    ("Re-taking a BR/Bounce at a level that already worked: OK, but with caution. "
     "The first Break & Retest/Bounce cleared out most of the immediate sell "
     "liquidity, so a second test at the same exact level carries higher "
     "break-through risk. Only take it if the 1H trend is still strong — "
     "otherwise size down or skip."),
]


def category_of(tag: str) -> str:
    return TAG_CATEGORY.get((tag or "").strip().lower(), "Other")


def split(value: str) -> list[str]:
    return [t.strip() for t in (value or "").split(",") if t.strip()]
