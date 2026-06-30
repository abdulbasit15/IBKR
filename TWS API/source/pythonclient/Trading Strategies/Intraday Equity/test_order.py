"""Place ONE 1-share protected bracket on the paper account to validate the live order
path (entry -> attached take-profit + stop) end-to-end, independent of a strategy signal.

Usage:  python test_order.py [SYMBOL]   (default AAPL)
PAPER ONLY. Opens a 1-share position + bracket; flatten it in the Gateway when done.
"""
import asyncio
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from ib_async import IB, Stock
import equity_order as eo

SYM = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
ACCOUNT = "DU672616"

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
ib = IB()
ib.connect("127.0.0.1", 4002, clientId=95)          # own clientId; NOT readonly (we trade)
ib.reqMarketDataType(3)                              # delayed ok for the test

c = Stock(SYM, "SMART", "USD")
ib.qualifyContracts(c)
tk = ib.reqMktData(c, "", False, False)
ib.sleep(3)
price = tk.marketPrice()
if price != price or not price:                      # NaN guard
    price = tk.last if (tk.last == tk.last and tk.last) else tk.close
print(f"{SYM} reference price ~ {price}")
if not price or price != price:
    print("No price for symbol; aborting."); ib.disconnect(); sys.exit(1)

entry = round(price * 1.003, 2)                      # marketable BUY limit (fills now)
stop = round(price * 0.99, 2)
target = round(price * 1.02, 2)
print(f"TEST bracket: BUY 1 {SYM}  entry<= {entry}  stop {stop}  target {target}")

pt, tp, st = eo.place_protected_entry(
    ib, c, 1, entry, target, stop, order_ref="TEST", account=ACCOUNT, log=print,
    tick=0.01, entry_timeout_sec=30, max_chase_pct=0.01,
)
if pt:
    print("ENTRY:", pt.orderStatus.status, "avgFill", pt.orderStatus.avgFillPrice, "filled", pt.orderStatus.filled)
    print("TP   :", tp.orderStatus.status, "lmt", getattr(tp.order, "lmtPrice", None))
    print("STOP :", st.orderStatus.status, "aux", getattr(st.order, "auxPrice", None))
    print(">>> TEST TRADE PLACED — check the Gateway (1-share paper). Flatten when done.")
else:
    print(">>> entry did not fill within the walk; no position opened.")
ib.sleep(2)
ib.disconnect()
