"""Technical indicators (pure pandas) and multi-timeframe snapshots per trade.

Computes, at each trade's entry time, the state of popular 5-min day-trading
indicators across 1H / 15m / 5m: trend, Supertrend, EMA cross, RSI, MACD — plus
alignment flags (do 1H/15m/5m Supertrends agree, and with the trade direction).
No external TA library — everything is derived with pandas.
"""
from __future__ import annotations

import pandas as pd

from . import config, market


# --- Core indicator math --------------------------------------------------
def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, n: int = 10) -> pd.Series:
    h, l, c = df["h"], df["l"], df["c"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    """Return the Supertrend direction series: +1 (up) / -1 (down)."""
    atr = _atr(df, period)
    hl2 = (df["h"] + df["l"]) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    c = df["c"].values
    up, dn = upper.values, lower.values
    fu = [up[0]] * len(c)
    fl = [dn[0]] * len(c)
    dir_ = [1] * len(c)
    for i in range(1, len(c)):
        fu[i] = up[i] if (up[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = dn[i] if (dn[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if c[i] > fu[i - 1]:
            dir_[i] = 1
        elif c[i] < fl[i - 1]:
            dir_[i] = -1
        else:
            dir_[i] = dir_[i - 1]
    return pd.Series(dir_, index=df.index)


def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's ADX — trend strength (not direction). >25 trend, <20 chop."""
    h, l, c = df["h"], df["l"], df["c"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up.clip(lower=0)
    minus_dm = ((dn > up) & (dn > 0)) * dn.clip(lower=0)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, 1e-9)
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, 1e-9)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def _df_from_bars(bars: list[list]) -> pd.DataFrame:
    cols = ["t", "o", "h", "l", "c", "v"][:len(bars[0])] if bars else \
        ["t", "o", "h", "l", "c"]
    return pd.DataFrame(bars, columns=cols)


def _bars_since_flip(vals) -> int | None:
    """Bars since the sign of `vals` last flipped (0 = flipped on the last bar).

    Used to date the most recent EMA or MACD crossover, so the app can say
    'crossed 3 bars ago' — freshness matters a lot on the 5-min chart.
    """
    n = len(vals)
    for k in range(n - 1, 0, -1):
        if (vals[k] > 0) != (vals[k - 1] > 0):
            return n - 1 - k
    return None


def _snapshot(bars: list[list]) -> dict | None:
    """Indicator snapshot at the last bar of `bars`."""
    if len(bars) < 30:
        return None
    df = _df_from_bars(bars)
    close = df["c"]
    ema9, ema21, ema50 = _ema(close, 9), _ema(close, 21), _ema(close, 50)
    rsi = _rsi(close, 14)
    st = _supertrend(df, 10, 3.0)
    adx = _adx(df, 14)
    atr = _atr(df, 14)
    macd_line = _ema(close, 12) - _ema(close, 26)
    signal = _ema(macd_line, 9)
    hist_s = macd_line - signal
    hist = float(hist_s.iloc[-1])
    hist_prev = float(hist_s.iloc[-2]) if len(hist_s) > 1 else hist
    i = -1
    c = close.iloc[i]
    trend = "up" if c > ema50.iloc[i] and ema21.iloc[i] > ema50.iloc[i] else (
        "down" if c < ema50.iloc[i] and ema21.iloc[i] < ema50.iloc[i] else "flat")
    rv = round(float(rsi.iloc[i]), 1)
    ema_gap = (ema9 - ema21).values
    e9, e21 = float(ema9.iloc[i]), float(ema21.iloc[i])
    return {
        "trend": trend,
        "st": "up" if st.iloc[i] > 0 else "down",
        "rsi": rv,
        "rsi_zone": "overbought" if rv >= 70 else ("oversold" if rv <= 30 else "neutral"),
        # --- Trend strength / volatility ---
        "adx": round(float(adx.iloc[i]), 1),
        "adx_regime": ("strong trend" if adx.iloc[i] >= 25 else
                       ("trend" if adx.iloc[i] >= 20 else "chop / range")),
        "atr": round(float(atr.iloc[i]), 2),
        # --- EMA 9/21 (popular 5-min trigger) ---
        "emacross": "bull" if e9 > e21 else "bear",
        "ema9": round(e9, 2),
        "ema21": round(e21, 2),
        "ema_gap": round(e9 - e21, 2),
        "ema_cross_bars": _bars_since_flip(ema_gap),
        # --- MACD (12/26/9) ---
        "macd": "+" if hist > 0 else "-",                       # kept for stats
        "macd_state": "bullish" if macd_line.iloc[i] > signal.iloc[i] else "bearish",
        "macd_line": round(float(macd_line.iloc[i]), 2),
        "macd_signal": round(float(signal.iloc[i]), 2),
        "macd_hist": round(hist, 2),
        "macd_mom": "rising" if hist > hist_prev else "falling",
        "macd_cross_bars": _bars_since_flip(hist_s.values),
    }


def _clv(o, h, l, c) -> float:
    """Close-location value in [-1, +1]: +1 = closed on the high (buy pressure)."""
    rng = h - l
    return 0.0 if rng <= 0 else ((c - l) - (h - c)) / rng


def _session(trade, entry_ep: int) -> dict | None:
    """Volume-based context at entry: VWAP (+distance), VPOC, RVOL, est. delta.

    Computed over the RTH session (from 09:30 ET) up to the entry bar, using
    5-min OHLCV bars. VWAP/VPOC/RVOL are genuine (volume-weighted); est. delta
    is a close-location proxy (no bid/ask data), so it is labelled 'est.'.
    """
    import datetime as _dt
    bars = market.series_v_for(trade.asset, "5m", "1mo")   # [[t,o,h,l,c,v],...]
    if not bars:
        return None
    ts = trade.timestamp
    tod = ts.hour * 60 + ts.minute
    anchor_day = ts.date() if tod >= 9 * 60 + 30 else ts.date() - _dt.timedelta(days=1)
    anchor_ep = market.et_epoch(_dt.datetime(anchor_day.year, anchor_day.month,
                                             anchor_day.day, 9, 30))
    sess = [b for b in bars if anchor_ep <= b[0] <= entry_ep and len(b) >= 6]
    if len(sess) < 3:
        return None

    # VWAP (typical price * volume) — falls back to simple avg if volume is absent
    vsum = sum(b[5] for b in sess)
    if vsum > 0:
        vwap = sum(((b[1] + b[2] + b[3] + b[4]) / 4) * b[5] for b in sess) / vsum
    else:
        vwap = sum(b[4] for b in sess) / len(sess)

    # Volume Point of Control: price bucket holding the most volume
    lo = min(b[3] for b in sess)
    hi = max(b[2] for b in sess)
    span = hi - lo
    vpoc = sess[-1][4]
    if span > 0 and vsum > 0:
        nb = 40
        buckets = [0.0] * nb
        for b in sess:
            mid = (b[2] + b[3]) / 2
            k = min(nb - 1, int((mid - lo) / span * nb))
            buckets[k] += b[5]
        kmax = max(range(nb), key=lambda k: buckets[k])
        vpoc = lo + (kmax + 0.5) / nb * span

    # RVOL: entry-bar volume vs the median volume for that time-of-day (lookback)
    entry_bar = sess[-1]
    entry_min = ts.hour * 60 + ts.minute
    same_time = []
    for b in bars:
        if b[0] > entry_ep or len(b) < 6 or b[5] <= 0:
            continue
        bt = _dt.datetime.utcfromtimestamp(b[0] + market.ET_OFFSET_HOURS * 3600)
        if bt.hour * 60 + bt.minute == (entry_min // 5) * 5:
            same_time.append(b[5])
    rvol = None
    if len(same_time) >= 5 and entry_bar[5] > 0:
        srt = sorted(same_time)
        med = srt[len(srt) // 2]
        if med > 0:
            rvol = round(entry_bar[5] / med, 2)

    # Estimated cumulative delta (proxy): sum(CLV * volume) over the session
    est_delta = sum(_clv(b[1], b[2], b[3], b[4]) * b[5] for b in sess)

    price = trade.entry or sess[-1][4]
    return {
        "vwap": round(vwap, 2),
        "vwap_dist": round(price - vwap, 2),
        "vwap_side": "above" if price >= vwap else "below",
        "vpoc": round(vpoc, 2),
        "vpoc_dist": round(price - vpoc, 2),
        "rvol": rvol,
        "est_delta": round(est_delta),
        "est_delta_side": "buyers" if est_delta > 0 else "sellers",
        "sess_bars": len(sess),
    }


# Round-number step per instrument root (major intraday round levels).
_ROUND_STEP = {"MNQ": 50.0, "NQ": 50.0, "MES": 25.0, "ES": 25.0,
               "MYM": 100.0, "YM": 100.0, "MGC": 10.0, "GC": 10.0,
               "MCL": 1.0, "CL": 1.0, "RTY": 10.0, "M2K": 10.0, "QM": 1.0}


def _key_levels(trade, entry_ep: int, atr) -> dict | None:
    """Detect whether entry sits at a horizontal level: prior-day H/L, overnight
    H/L, opening-range H/L, or a round number. Tolerance ~ 0.5 ATR."""
    import datetime as _dt
    entry = trade.entry
    if entry is None:
        return None
    root = config.root_from_symbol(trade.asset) or (trade.asset or "").upper()
    tol = (atr * 0.5) if atr else entry * 0.0007
    d = trade.timestamp.date()
    levels: dict[str, float] = {}
    # Prior-day high/low (daily bars)
    try:
        tk = config.YAHOO_MAP.get(trade.asset.upper())
        daily = market._fetch_series(tk) if tk else []
        prior = [b for b in daily if b["date"] < d]
        if prior:
            levels["PDH"] = round(prior[-1]["high"], 2)
            levels["PDL"] = round(prior[-1]["low"], 2)
    except Exception:
        pass
    # Overnight H/L (prev 18:00 ET -> 09:30) and opening range (09:30-10:00)
    try:
        bars = market.series_v_for(trade.asset, "5m", "1mo")
        rth = market.et_epoch(_dt.datetime(d.year, d.month, d.day, 9, 30))
        prev18 = market.et_epoch(_dt.datetime(d.year, d.month, d.day, 0, 0)) - 6 * 3600
        orend = market.et_epoch(_dt.datetime(d.year, d.month, d.day, 10, 0))
        on = [b for b in bars if prev18 <= b[0] < rth]
        if on:
            levels["ONH"] = round(max(b[2] for b in on), 2)
            levels["ONL"] = round(min(b[3] for b in on), 2)
        if entry_ep >= orend:                      # OR only valid once formed
            orb = [b for b in bars if rth <= b[0] < orend]
            if orb:
                levels["ORH"] = round(max(b[2] for b in orb), 2)
                levels["ORL"] = round(min(b[3] for b in orb), 2)
    except Exception:
        pass
    # Round number
    step = _ROUND_STEP.get(root, 0)
    if step:
        rn = round(entry / step) * step
        levels["Round"] = round(rn, 2)
    near = [nm for nm, px in levels.items() if abs(entry - px) <= tol]
    return {"levels": levels, "near": near, "at_level": bool(near),
            "tol": round(tol, 2)}


def _entry_bar_signals(trade, entry_ep: int) -> dict | None:
    """Candlestick trigger + trigger-bar volume at the entry (last 5m bar)."""
    bars = market.series_v_for(trade.asset, "5m", "1mo")
    hist = [b for b in bars if b[0] <= entry_ep]
    if len(hist) < 21:
        return None
    cur, prev = hist[-1], hist[-2]
    o, h, l, c = cur[1], cur[2], cur[3], cur[4]
    po, pc = prev[1], prev[4]
    body = abs(c - o)
    rng = (h - l) or 1e-9
    lower = min(o, c) - l
    upper = h - max(o, c)
    is_long = trade.direction == "Long"
    bull_engulf = c > o and pc < po and c >= po and o <= pc
    bear_engulf = c < o and pc > po and c <= po and o >= pc
    bull_pin = body > 0 and lower >= 2 * body and upper <= body
    bear_pin = body > 0 and upper >= 2 * body and lower <= body
    strong_bull = (c - l) / rng >= 0.7 and c > o
    strong_bear = (h - c) / rng >= 0.7 and c < o
    ctype, cdir = "", 0
    if bull_engulf:
        ctype, cdir = "bullish engulfing", 1
    elif bear_engulf:
        ctype, cdir = "bearish engulfing", -1
    elif bull_pin:
        ctype, cdir = "bullish pin/hammer", 1
    elif bear_pin:
        ctype, cdir = "bearish pin", -1
    elif strong_bull:
        ctype, cdir = "strong bullish close", 1
    elif strong_bear:
        ctype, cdir = "strong bearish close", -1
    candle_ok = (cdir == 1) == is_long and cdir != 0
    candle_against = cdir != 0 and (cdir == 1) != is_long
    vols = [b[5] for b in hist[-21:-1] if len(b) >= 6]
    avg = (sum(vols) / len(vols)) if vols else 0
    tv = round(cur[5] / avg, 2) if (avg > 0 and len(cur) >= 6) else None
    return {"candle_type": ctype, "candle_dir": cdir, "candle_ok": candle_ok,
            "candle_against": candle_against, "trigvol": tv,
            "trigvol_ok": tv is not None and tv >= 1.2}


def _fib(trade, entry_ep: int) -> dict | None:
    """Fibonacci retracement of the last 5-min impulse leg before entry.

    Detects the swing (low→high for a long, high→low for a short) in the recent
    window and reports where the entry sits as a % retracement — the 38.2–61.8%
    'golden zone' is the classic trend-pullback entry area.
    """
    bars = market.series_for(trade.asset, "5m", "1mo")
    hist = [b for b in bars if b[0] <= entry_ep]
    if len(hist) < 20:
        return None
    win = hist[-60:]
    highs = [b[2] for b in win]
    lows = [b[3] for b in win]
    is_long = trade.direction == "Long"
    entry = trade.entry or win[-1][4]

    if is_long:
        i_lo = min(range(len(win)), key=lambda i: lows[i])
        if i_lo + 1 >= len(win):
            return None
        i_hi = max(range(i_lo + 1, len(win)), key=lambda i: highs[i])
        leg_low, leg_high = lows[i_lo], highs[i_hi]
    else:
        i_hi = max(range(len(win)), key=lambda i: highs[i])
        if i_hi + 1 >= len(win):
            return None
        i_lo = min(range(i_hi + 1, len(win)), key=lambda i: lows[i])
        leg_low, leg_high = lows[i_lo], highs[i_hi]

    rng = leg_high - leg_low
    if rng <= 0:
        return None
    if is_long:
        retr = (leg_high - entry) / rng
        lvl = lambda r: round(leg_high - rng * r, 2)
    else:
        retr = (entry - leg_low) / rng
        lvl = lambda r: round(leg_low + rng * r, 2)
    zone = ("extended (no pullback)" if retr <= 0.15 else
            "shallow" if retr < 0.382 else
            "golden" if retr <= 0.618 else
            "deep" if retr <= 0.786 else
            "broke the leg (reversal risk)")
    return {
        "leg_low": round(leg_low, 2), "leg_high": round(leg_high, 2),
        "f382": lvl(0.382), "f50": lvl(0.5), "f618": lvl(0.618), "f786": lvl(0.786),
        "retr": round(retr, 3), "zone": zone,
        "in_golden": 0.382 <= retr <= 0.618,
    }


def _pullback(trade, snap: dict, fib: dict | None) -> dict:
    """Score a trend-pullback entry: trend confirmed + at a confluence zone +
    a fresh re-cross trigger. 0-3 (A+ = all three)."""
    m5 = snap.get("m5", {})
    se = snap.get("session", {})
    is_long = trade.direction == "Long"
    entry = trade.entry
    atr = m5.get("atr") or (entry * 0.001 if entry else None)

    def near(level):
        return (level is not None and entry is not None and atr
                and abs(entry - level) <= 0.6 * atr)

    # (a) confirmed trend: with the 1H trend AND ADX >= 20
    adx = m5.get("adx")
    trend_ok = bool(snap.get("trend_match")) and (adx is not None and adx >= 20)

    # (b) at a confluence zone (near 21 EMA / VWAP / in the Fib golden zone)
    zones = []
    if near(m5.get("ema21")):
        zones.append("21 EMA")
    if near(se.get("vwap")):
        zones.append("VWAP")
    if fib and fib.get("in_golden"):
        zones.append("Fib golden")
    zone_ok = bool(zones)

    # (c) fresh re-cross trigger in the trade's direction (<= 2 bars old)
    trig = []
    eb, mb = m5.get("ema_cross_bars"), m5.get("macd_cross_bars")
    if eb is not None and eb <= 2 and (m5.get("emacross") == "bull") == is_long:
        trig.append("EMA9/21 re-cross")
    if mb is not None and mb <= 2 and (m5.get("macd_state") == "bullish") == is_long:
        trig.append("MACD re-cross")
    trigger_ok = bool(trig)

    score = int(trend_ok) + int(zone_ok) + int(trigger_ok)
    grade = ["No setup", "Weak", "Good", "A+"][score]
    return {"score": score, "grade": grade, "trend_ok": trend_ok,
            "zone_ok": zone_ok, "trigger_ok": trigger_ok,
            "zones": zones, "triggers": trig}


# --- Per-trade multi-timeframe snapshot -----------------------------------
_TF = [("h1", "1h", "3mo"), ("m15", "15m", "1mo"), ("m5", "5m", "1mo")]


def for_trade(trade) -> dict | None:
    """Compute the indicator state at a trade's entry across 1H/15m/5m."""
    if not trade.timestamp or not trade.asset:
        return None
    ep = market.et_epoch(trade.timestamp)
    out = {}
    for key, interval, rng in _TF:
        bars = market.series_for(trade.asset, interval, rng)
        hist = [b for b in bars if b[0] <= ep]
        snap = _snapshot(hist) if hist else None
        if snap:
            out[key] = snap
    if not out:
        return None

    dir_ = trade.direction  # "Long"/"Short"
    want = "up" if dir_ == "Long" else "down"
    sts = [out[k]["st"] for k in ("h1", "m15", "m5") if k in out]
    out["st_aligned"] = len(sts) >= 3 and len(set(sts)) == 1
    out["st_with_trade"] = len(sts) >= 3 and all(s == want for s in sts)
    out["trend_match"] = ("h1" in out) and (out["h1"]["trend"] == want)
    try:
        sess = _session(trade, ep)
        if sess:
            out["session"] = sess
    except Exception:
        pass
    try:
        fib = _fib(trade, ep)
        if fib:
            out["fib"] = fib
    except Exception:
        fib = None
    try:
        kl = _key_levels(trade, ep, out.get("m5", {}).get("atr"))
        if kl:
            out["levels"] = kl
    except Exception:
        pass
    try:
        eb = _entry_bar_signals(trade, ep)
        if eb:
            out["entry"] = eb
    except Exception:
        pass
    try:
        out["pullback"] = _pullback(trade, out, out.get("fib"))
    except Exception:
        pass
    return out


def summarize(trades) -> dict:
    """{trade_index: snapshot} for all trades (fetches series once, cached)."""
    return {i: for_trade(t) for i, t in enumerate(trades) if t.timestamp}


def sheet_rows(trades, snaps: dict) -> list[dict]:
    """Flatten per-trade indicator snapshots into rows for the Excel sheet."""
    out = []
    for i, t in enumerate(trades):
        if not t.timestamp:
            continue
        s = snaps.get(i) or {}
        h1, m15, m5 = s.get("h1", {}), s.get("m15", {}), s.get("m5", {})
        se = s.get("session", {})
        fib = s.get("fib", {})
        pb = s.get("pullback", {})
        kl = s.get("levels", {})
        eb = s.get("entry", {})
        out.append({
            "date": str(t.timestamp.date()), "time": t.timestamp.strftime("%H:%M"),
            "asset": t.asset, "dir": t.direction,
            "pnl": round(t.pnl, 2) if t.pnl is not None else "",
            "h1_trend": h1.get("trend", ""), "h1_st": h1.get("st", ""),
            "m15_st": m15.get("st", ""), "m5_st": m5.get("st", ""),
            "m5_rsi": m5.get("rsi", ""), "m5_ema": m5.get("emacross", ""),
            "m5_macd": m5.get("macd", ""),
            "m5_adx": m5.get("adx", ""), "m5_atr": m5.get("atr", ""),
            "vwap": se.get("vwap", ""), "vwap_side": se.get("vwap_side", ""),
            "vpoc": se.get("vpoc", ""), "rvol": se.get("rvol", ""),
            "est_delta": se.get("est_delta", ""),
            "fib_retr": round(fib["retr"] * 100) if fib.get("retr") is not None else "",
            "fib_zone": fib.get("zone", ""),
            "pb_grade": pb.get("grade", ""), "pb_score": pb.get("score", ""),
            "at_level": ("/".join(kl.get("near", [])) if kl.get("at_level") else "No"),
            "candle": eb.get("candle_type", ""),
            "trigvol": eb.get("trigvol", ""),
            "aligned": "Yes" if s.get("st_with_trade") else "No",
            "with_1h": "Yes" if s.get("trend_match") else "No",
        })
    return out


def _pct(x) -> str:
    return f"{round(x * 100)}%"


def _usd(x) -> str:
    x = round(x)
    return f"-${abs(x):,}" if x < 0 else f"+${x:,}"


def analysis(trade, snap: dict | None, perf: list | None = None,
             setup_perf: list | None = None) -> list | None:
    """A per-trade, indicator-driven read: confluence, the 1H-trend edge, key
    confirmations/conflicts, an RSI caution, and whether the outcome matched the
    signal. Grounded in the trader's own aggregate numbers (from `performance`),
    so it stays accurate as more trades accumulate.
    """
    if not snap:
        return None
    idx = {r["name"]: r for r in (perf or [])}
    setup_idx = {r["name"]: r for r in (setup_perf or [])}
    with_row = idx.get("With the 1H trend")
    against_row = idx.get("Against / unclear 1H trend")
    h1, m15, m5 = snap.get("h1", {}), snap.get("m15", {}), snap.get("m5", {})
    se = snap.get("session") or {}
    is_long = trade.direction == "Long"
    want = "up" if is_long else "down"
    won = (trade.pnl or 0) > 0

    # --- Confluence tally: only the 3 NON-redundant signals -----------------
    # (1H Supertrend duplicates 1H trend; 15m/5m Supertrend add no edge; MACD is
    #  a slower duplicate of the EMA cross. Those still show below for info, but
    #  do NOT count toward confluence.)
    signals: list[tuple[str, bool]] = []
    if snap.get("trend_match") is not None and h1:
        signals.append(("1H trend", bool(snap.get("trend_match"))))
    if m5.get("emacross"):
        signals.append(("5m EMA9/21", (m5["emacross"] == "bull") == is_long))
    if se.get("vwap_side"):
        signals.append(("VWAP side", (se["vwap_side"] == "above") == is_long))
    agree = [s for s, ok in signals if ok]
    against = [s for s, ok in signals if not ok]
    n = len(signals)
    na = len(agree)

    if n:
        if na == n:
            conf = "full confluence"
        elif na >= n - 1:
            conf = "strong confluence"
        elif na * 2 >= n:
            conf = "mixed signals"
        else:
            conf = "mostly counter-signal"
    else:
        conf = "no indicator read"

    side = trade.direction
    kl = snap.get("levels") or {}
    eb = snap.get("entry") or {}
    fib = snap.get("fib")
    pb = snap.get("pullback")
    adx_v = m5.get("adx")

    # ================= CONFLUENCE (direction) — 3 signals ==================
    conf_items: list[str] = []
    if h1.get("trend"):
        tr = h1["trend"]
        ok = bool(snap.get("trend_match"))
        note = (f"agrees with the {side}" if ok
                else ("flat / choppy" if tr == "flat" else f"{tr} — opposing the {side}"))
        conf_items.append(f"{'✓' if ok else '✗'} **1H trend:** {tr} — {note}")
        if with_row and against_row:
            conf_items.append(
                f"↳ track record: with-trend {_pct(with_row['win_rate'])} "
                f"({_usd(with_row['total_pnl'])}) vs {_pct(against_row['win_rate'])} "
                f"({_usd(against_row['total_pnl'])}) against")
    if m5.get("emacross"):
        eb_bull = m5["emacross"] == "bull"
        ok = eb_bull == is_long
        fr = m5.get("ema_cross_bars")
        fresh = f" · fresh cross {fr}b ago" if (fr is not None and fr <= 2) else ""
        conf_items.append(
            f"{'✓' if ok else '✗'} **5m EMA 9/21:** {'bullish' if eb_bull else 'bearish'}"
            f"{fresh} — {'with' if ok else 'against'} the {side}")
    if se.get("vwap_side"):
        ok = (se["vwap_side"] == "above") == is_long
        conf_items.append(
            f"{'✓' if ok else '✗'} **VWAP:** price {se['vwap_side']} ({se.get('vwap')}) "
            f"— {'right' if ok else 'wrong'} side")

    # ================= ENTRY QUALITY — 3 factors ===========================
    qual_items: list[str] = []
    qn = qtot = 0
    if kl:
        qtot += 1
        if kl.get("at_level"):
            qn += 1
            qual_items.append(f"✓ **Key level:** at {'/'.join(kl['near'])}")
        else:
            qual_items.append("✗ **Key level:** not at a level")
    if eb.get("candle_type"):
        qtot += 1
        if eb.get("candle_ok"):
            qn += 1
            qual_items.append(f"✓ **Candlestick:** {eb['candle_type']} (with trade)")
        elif eb.get("candle_against"):
            qual_items.append(f"✗ **Candlestick:** {eb['candle_type']} (against trade)")
        else:
            qual_items.append(f"– **Candlestick:** {eb['candle_type']}")
    if eb.get("trigvol") is not None:
        qtot += 1
        ok = eb.get("trigvol_ok")
        if ok:
            qn += 1
        qual_items.append(
            f"{'✓' if ok else '✗'} **Trigger volume:** {eb['trigvol']}× "
            f"({'conviction' if ok else 'weak participation'})")

    # ================= PULLBACK & FIBONACCI ================================
    pull_items: list[str] = []
    if pb:
        checks = (f"{'✓' if pb['trend_ok'] else '✗'} trend · "
                  f"{'✓' if pb['zone_ok'] else '✗'} zone"
                  + (f" ({', '.join(pb['zones'])})" if pb['zones'] else "")
                  + f" · {'✓' if pb['trigger_ok'] else '✗'} trigger"
                  + (f" ({', '.join(pb['triggers'])})" if pb['triggers'] else ""))
        pull_items.append(f"**{pb['grade']} ({pb['score']}/3)** — {checks}")
    if fib:
        pct = round(fib["retr"] * 100)
        if fib["in_golden"]:
            pull_items.append(f"**Fib:** {pct}% retrace ({fib['leg_low']}→{fib['leg_high']}) "
                              f"— **golden zone** (38–62%)")
        else:
            pull_items.append(f"**Fib:** {pct}% retrace — {fib['zone']} (golden is 38–62%)")

    # --- The right play: prescriptive verdict from indicators + history ------
    opp = "Short" if is_long else "Long"
    action = "buy" if is_long else "sell"
    # Verdict weighs only the non-redundant confluences: 1H trend, 5m EMA9/21,
    # VWAP side, plus pullback quality. (STs and MACD are info-only now.)
    pro = con = 0
    if h1.get("trend"):
        if snap.get("trend_match"):
            pro += 1
        elif h1["trend"] != "flat":
            con += 1
    if m5.get("emacross"):
        ok = (m5["emacross"] == "bull") == is_long
        pro, con = pro + (1 if ok else 0), con + (0 if ok else 1)
    if se.get("vwap_side"):
        ok = (se["vwap_side"] == "above") == is_long
        pro, con = pro + (1 if ok else 0), con + (0 if ok else 1)
    if pb:
        if pb["zone_ok"] and pb["trigger_ok"]:
            pro += 1                       # entered at a zone on a fresh trigger
        elif not pb["zone_ok"] and not pb["trigger_ok"]:
            con += 1                       # no zone, no trigger — a poor pullback
    if kl.get("at_level"):
        pro += 1                           # entered at a horizontal level (retest)
    if eb.get("candle_ok"):
        pro += 1                           # reversal/momentum candle in trade dir
    elif eb.get("candle_against"):
        con += 1
    if eb.get("trigvol_ok"):
        pro += 1                           # conviction: high-volume trigger bar

    trend_ok = bool(snap.get("trend_match"))
    trend_opp = h1.get("trend") in ("up", "down") and not trend_ok
    chop = adx_v is not None and adx_v < 20
    if pro >= con + 2 and (trend_ok or h1.get("trend") == "flat") and not chop:
        label = f"Take the {side} ({action})"
        reason = (f"{pro} of {pro + con} signals lined up"
                  + (" with the 1H trend" if trend_ok else "")
                  + " — this is your kind of entry.")
    elif con >= pro + 2 and trend_opp:
        label = f"Reverse — a {opp} was the play"
        reason = (f"The 1H trend and most timeframes pointed the other way, so "
                  f"the {side} fought the tape. If anything, the {opp} had the edge.")
    elif chop and pro < con + 2:
        label = "Avoid — chop"
        reason = (f"ADX {adx_v} says range/no-trend. Even with some signals lined up, "
                  f"trend entries whip out here — stand aside until ADX > 20.")
    elif con > pro or trend_opp:
        label = "Avoid — no trade"
        reason = (f"Confluence was against the {side}; the disciplined move is to "
                  f"stand aside and wait for the timeframes to line up.")
    else:
        label = "Avoid / wait for confluence"
        reason = (f"Signals were split ({pro} for / {con} against) — no clear edge "
                  f"to press. Wait for alignment.")
    verdict_items = [f"**{label}** — {reason}"]

    bits = []
    row = with_row if trend_ok else against_row
    if row and row.get("n"):
        bits.append(f"in this 1H state your trades win {_pct(row['win_rate'])} "
                    f"(avg {_usd(row['expectancy'])}/trade)")
    sp = setup_idx.get((trade.setup or "").strip())
    if sp and sp.get("n", 0) >= 3:
        bits.append(f"your **{trade.setup}** setup runs {_pct(sp['win_rate'])} "
                    f"over {sp['n']} trades (avg {_usd(sp['expectancy'])})")
    if bits:
        lead = ("Likely outcome if taken anyway" if label.startswith("Avoid")
                or label.startswith("Reverse") else "Likely outcome")
        verdict_items.append(f"**{lead}:** " + "; ".join(bits) + ".")

    if trade.pnl is not None:
        strong = na >= max(1, n - 1)
        if won and strong:
            oc = "matched the setup — repeatable."
        elif won and not strong:
            oc = "win despite weak confluence — likely favorable, don't over-learn from it."
        elif (not won) and strong:
            oc = "loss despite good confluence — variance/execution, not a bad read. Keep taking these."
        else:
            oc = "loss on a low-confluence entry — the setup was warning you. Skippable."
        verdict_items.append(
            f"**Result:** {trade.winloss or ('Win' if won else 'Loss')} "
            f"({_usd(trade.pnl)}) — {oc}")

    # ================= assemble categorized sections =======================
    sections = []
    conf_title = (f"Confluence — {na}/{n} · {conf}" if n else "Confluence")
    if conf_items:
        sections.append({"cat": conf_title, "items": conf_items})
    if qtot:
        sections.append({"cat": f"Entry quality — {qn}/{qtot}", "items": qual_items})
    if pull_items:
        sections.append({"cat": "Pullback & Fibonacci", "items": pull_items})
    sections.append({"cat": f"🎯 The right play — {label}", "items": verdict_items})
    return sections


def performance(trades, snaps: dict) -> list[dict]:
    """Win rate / P&L by indicator state — how each condition affects outcomes."""
    from collections import defaultdict
    b = defaultdict(lambda: {"pnl": 0.0, "n": 0, "w": 0})

    def add(name, pnl):
        x = b[name]
        x["pnl"] += pnl
        x["n"] += 1
        x["w"] += 1 if pnl > 0 else 0

    for i, t in enumerate(trades):
        s = snaps.get(i)
        if not s or t.pnl is None:
            continue
        p = t.pnl
        is_long = t.direction == "Long"
        add("All 3 Supertrends aligned with trade" if s.get("st_with_trade")
            else "Supertrends NOT aligned with trade", p)
        add("With the 1H trend" if s.get("trend_match")
            else "Against / unclear 1H trend", p)
        m5 = s.get("m5", {})
        if m5:
            if (m5.get("emacross") == "bull") == is_long:
                add("5m EMA9/21 cross with trade", p)
            else:
                add("5m EMA9/21 cross against trade", p)
            if (m5.get("macd") == "+") == is_long:
                add("5m MACD with trade", p)
            else:
                add("5m MACD against trade", p)
            z = m5.get("rsi_zone")
            if z == "overbought":
                add("Entered at 5m RSI overbought (>=70)", p)
            elif z == "oversold":
                add("Entered at 5m RSI oversold (<=30)", p)
            adx = m5.get("adx")
            if adx is not None:
                if adx < 20:
                    add("ADX < 20 (chop / range)", p)
                elif adx >= 25:
                    add("ADX >= 25 (strong trend)", p)
                else:
                    add("ADX 20-25 (developing trend)", p)
        se = s.get("session", {})
        if se.get("vwap_side"):
            if (se["vwap_side"] == "above") == is_long:
                add("On the right side of VWAP", p)
            else:
                add("Wrong side of VWAP", p)
        if se.get("rvol") is not None:
            if se["rvol"] >= 1.5:
                add("High RVOL (>=1.5x)", p)
            elif se["rvol"] < 0.7:
                add("Thin RVOL (<0.7x)", p)
        pb = s.get("pullback")
        if pb:
            add(f"Pullback grade: {pb['grade']}", p)
        fib = s.get("fib")
        if fib:
            if fib.get("in_golden"):
                add("Entered in Fib golden zone (38-62%)", p)
            elif fib["retr"] <= 0.15:
                add("Entered extended (no pullback)", p)
            elif fib["retr"] > 0.786:
                add("Entered past 78.6% (deep/reversal)", p)
        kl = s.get("levels")
        if kl:
            add("Entered at a key level" if kl.get("at_level") else "Not at a key level", p)
        eb = s.get("entry", {})
        if eb.get("candle_type"):
            if eb.get("candle_ok"):
                add("Reversal candle with trade", p)
            elif eb.get("candle_against"):
                add("Candle against trade", p)
        if eb.get("trigvol") is not None:
            add("High trigger-bar volume (>=1.2x)" if eb.get("trigvol_ok")
                else "Weak trigger-bar volume", p)
    rows = [{"name": k, "n": v["n"], "win_rate": v["w"] / v["n"],
             "total_pnl": round(v["pnl"], 2), "expectancy": round(v["pnl"] / v["n"], 2)}
            for k, v in b.items() if v["n"]]
    rows.sort(key=lambda r: r["total_pnl"])
    return rows
