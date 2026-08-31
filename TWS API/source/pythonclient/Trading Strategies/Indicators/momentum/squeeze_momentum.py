"""Squeeze Momentum Indicator (LazyBear) — shared, reusable by any strategy.

Faithful port of LazyBear's "Squeeze Momentum Indicator [SQZMOM_LB]" (TradingView Pine):

    - Bollinger Bands (BB) vs Keltner Channels (KC) define the "squeeze":
        squeeze_on  = BB inside KC   (low volatility, energy building)  -> black dot
        squeeze_off = BB outside KC  (squeeze released, expansion)      -> gray dot
        no_squeeze  = neither                                           -> blue dot
    - Momentum histogram `val` = linear-regression (LSMA) of price minus the average of the
      Donchian midline and the SMA, over the KC length. Color:
        val > 0: lime if rising else green ;  val < 0: red if falling else maroon

NOTE (matches the original exactly): in LazyBear's code the BB deviation is
``dev = multKC * stdev(close, length)`` — i.e. it uses the KC multiplier (1.5), and the
``mult`` (BB MultFactor, 2.0) input is defined but never actually used. This port reproduces
that behavior so values line up with the TradingView indicator. ``mult`` is accepted for
API completeness but, as in the source, does not affect the result.

Two layers (same pattern as supertrend.py / dema.py):

1. Pure math: ``squeeze_momentum(highs, lows, closes, ...)`` -> dict of aligned lists.
2. Config-driven value: ``squeeze_value(...)`` — give it a symbol + timeframe + params (and
   an `ib` to fetch with, OR pre-fetched `bars`) and it returns a SqueezeResult for the last
   completed bar, e.g.::

       res = squeeze_value(ib=ib, symbol="SOXL", bar_size="15 mins")
       res.value        # the momentum histogram value
       res.squeeze_on   # True while BB is inside KC (squeeze building)
       res.positive, res.rising, res.color, res.squeeze_color

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def _sma_series(values, n):
    """Simple moving average; out[i] is the mean of values[i-n+1..i] (None before that)."""
    out = [None] * len(values)
    if n <= 0:
        return out
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= n:
            run -= values[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def _stdev_series(values, n):
    """Population standard deviation (divides by n), matching TradingView's ta.stdev."""
    out = [None] * len(values)
    if n <= 0:
        return out
    for i in range(len(values)):
        if i >= n - 1:
            window = values[i - n + 1:i + 1]
            m = sum(window) / n
            var = sum((x - m) ** 2 for x in window) / n
            out[i] = var ** 0.5
    return out


def _true_range_series(highs, lows, closes):
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return tr


def _highest_series(values, n):
    out = [None] * len(values)
    for i in range(len(values)):
        if i >= n - 1:
            out[i] = max(values[i - n + 1:i + 1])
    return out


def _lowest_series(values, n):
    out = [None] * len(values)
    for i in range(len(values)):
        if i >= n - 1:
            out[i] = min(values[i - n + 1:i + 1])
    return out


def _linreg_endpoint(seq):
    """Value of the least-squares regression line at the most recent point of `seq`
    (oldest..newest) — i.e. Pine's linreg(src, len, 0) / the LSMA endpoint."""
    L = len(seq)
    sum_x = sum_y = sum_xx = sum_xy = 0.0
    for x in range(L):
        y = seq[x]
        sum_x += x
        sum_y += y
        sum_xx += x * x
        sum_xy += x * y
    denom = L * sum_xx - sum_x * sum_x
    slope = (L * sum_xy - sum_x * sum_y) / denom if denom else 0.0
    intercept = (sum_y - slope * sum_x) / L
    return intercept + slope * (L - 1)


def _linreg_series(values, n):
    out = [None] * len(values)
    for i in range(len(values)):
        if i >= n - 1:
            window = values[i - n + 1:i + 1]
            if all(v is not None for v in window):
                out[i] = _linreg_endpoint(window)
    return out


def squeeze_momentum(highs, lows, closes, length=20, mult=2.0, length_kc=20,
                     mult_kc=1.5, use_true_range=True):
    """Compute the LazyBear Squeeze Momentum series. Returns a dict of lists aligned to the
    inputs (None where not yet computable):
        'val'     -> momentum histogram (linreg/LSMA of price vs midline)
        'sqz_on'  -> True while BB is inside KC (squeeze building)
        'sqz_off' -> True while BB is outside KC (squeeze released)
        'no_sqz'  -> True when neither
    `mult` is accepted but unused (see module note); BB dev uses `mult_kc`, as in the source."""
    n = len(closes)
    basis = _sma_series(closes, length)
    stdev = _stdev_series(closes, length)
    # LazyBear original: BB deviation uses the KC multiplier (mult is unused).
    upper_bb = [None] * n
    lower_bb = [None] * n
    for i in range(n):
        if basis[i] is not None and stdev[i] is not None:
            dev = mult_kc * stdev[i]
            upper_bb[i] = basis[i] + dev
            lower_bb[i] = basis[i] - dev

    ma = _sma_series(closes, length_kc)
    rng = _true_range_series(highs, lows, closes) if use_true_range else [highs[i] - lows[i] for i in range(n)]
    rangema = _sma_series(rng, length_kc)
    upper_kc = [None] * n
    lower_kc = [None] * n
    for i in range(n):
        if ma[i] is not None and rangema[i] is not None:
            upper_kc[i] = ma[i] + rangema[i] * mult_kc
            lower_kc[i] = ma[i] - rangema[i] * mult_kc

    sqz_on = [None] * n
    sqz_off = [None] * n
    no_sqz = [None] * n
    for i in range(n):
        if None in (lower_bb[i], lower_kc[i], upper_bb[i], upper_kc[i]):
            continue
        on = (lower_bb[i] > lower_kc[i]) and (upper_bb[i] < upper_kc[i])
        off = (lower_bb[i] < lower_kc[i]) and (upper_bb[i] > upper_kc[i])
        sqz_on[i] = on
        sqz_off[i] = off
        no_sqz[i] = (not on) and (not off)

    hh = _highest_series(highs, length_kc)
    ll = _lowest_series(lows, length_kc)
    src = [None] * n
    for i in range(n):
        if hh[i] is not None and ll[i] is not None and ma[i] is not None:
            midline = ((hh[i] + ll[i]) / 2.0 + ma[i]) / 2.0
            src[i] = closes[i] - midline
    val = _linreg_series(src, length_kc)

    return {"val": val, "sqz_on": sqz_on, "sqz_off": sqz_off, "no_sqz": no_sqz}


@dataclass
class SqueezeResult:
    value: float            # momentum histogram value (val)
    prev: float             # previous bar's val (nz: 0.0 if none), for rising/falling
    rising: bool            # val > prev
    positive: bool          # val > 0
    squeeze_on: bool        # BB inside KC (squeeze building) -> black dot
    squeeze_off: bool       # BB outside KC (squeeze released) -> gray dot
    no_squeeze: bool        # neither -> blue dot
    color: str              # 'lime' | 'green' | 'red' | 'maroon' (histogram bar color)
    squeeze_color: str      # 'blue' | 'black' | 'gray' (the squeeze dot color)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def squeeze_value(symbol=None, bar_size="15 mins", *, length=20, mult=2.0, length_kc=20,
                  mult_kc=1.5, use_true_range=True, ib=None, bars=None, duration=None,
                  use_rth=True, what="TRADES", exchange="SMART", currency="USD",
                  throttle=None, completed=True):
    """Compute the Squeeze Momentum for one symbol/timeframe and return the value on the last
    (completed) bar as a SqueezeResult, or None if there is not enough history.

    Provide EITHER ``bars`` OR ``ib`` + ``symbol`` (see supertrend_value for the rationale).
    ``completed`` True evaluates the last CLOSED bar (bars[-2]); False uses the forming bar."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("squeeze_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    if len(bars) < 2 * length_kc + length + 2:
        return None
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    res = squeeze_momentum(highs, lows, closes, length, mult, length_kc, mult_kc, use_true_range)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    val = res["val"][i]
    if val is None:
        return None
    prev_raw = res["val"][i - 1]
    prev = prev_raw if prev_raw is not None else 0.0           # nz(val[1])
    if val > 0:
        color = "lime" if val > prev else "green"
    else:
        color = "red" if val < prev else "maroon"
    on = bool(res["sqz_on"][i])
    off = bool(res["sqz_off"][i])
    no = bool(res["no_sqz"][i])
    squeeze_color = "blue" if no else ("black" if on else "gray")
    return SqueezeResult(value=val, prev=prev, rising=val > prev, positive=val > 0,
                         squeeze_on=on, squeeze_off=off, no_squeeze=no, color=color,
                         squeeze_color=squeeze_color, close=closes[i], time=bars[i].date)
