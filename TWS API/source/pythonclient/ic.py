import os
import json
import time
from datetime import datetime, timedelta
from ib_insync import *
from ib_insync import ComboLeg, Contract

# Load config using absolute path
config_path = os.path.join(os.path.dirname(__file__), 'ic.json')
with open(config_path, 'r') as f:
    config = json.load(f)

symbol = config['symbol']
exchange = config['exchange']
currency = config['currency']
multiplier = str(config['multiplier'])
tradingClass = config['tradingClass']
short_call_delta = config['short_call_delta']
short_put_delta = config['short_put_delta']
long_call_delta = config['long_call_delta']
long_put_delta = config['long_put_delta']
width = config['width']
retry_interval_min = config['retry_interval_min']
expiry = config['expiry']
trade_start_time = config['trade_start_time']
trade_end_time = config['trade_end_time']

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=22)

# Get option chain params for both SPX and SPXW
spx = Index(symbol, exchange)
contract_details = ib.reqContractDetails(spx)
if not contract_details:
    print("SPX contract not found.")
    ib.disconnect()
    exit()
spx_conId = contract_details[0].contract.conId

opt_params = ib.reqSecDefOptParams(symbol, '', 'IND', spx_conId)
params = [p for p in opt_params if p.exchange == exchange and p.tradingClass == tradingClass]
if not params:
    print(f"No option params for {exchange} {tradingClass}")
    ib.disconnect()
    exit()
params = params[0]

# 1) If expiry is not defined, use next expiry
expirations = sorted(params.expirations)
if not expiry:
    today = datetime.now().strftime('%Y%m%d')
    expiry = next(e for e in expirations if e >= today)
print(f"Using expiry: {expiry}")

# Get current price
spx_ticker = ib.reqMktData(spx)
timeout = 10
start = time.time()
while (spx_ticker.marketPrice() is None or spx_ticker.marketPrice() != spx_ticker.marketPrice()) and time.time() - start < timeout:
    ib.sleep(0.2)
current_price = spx_ticker.marketPrice()
if current_price is None or current_price != current_price:
    if spx_ticker.bid > 0 and spx_ticker.ask > 0:
        current_price = (spx_ticker.bid + spx_ticker.ask) / 2
    elif spx_ticker.bid > 0:
        current_price = spx_ticker.bid
    elif spx_ticker.ask > 0:
        current_price = spx_ticker.ask
    else:
        current_price = 6360  # fallback

num_strikes = config.get('num_strikes', 20)

# Get all strikes for this expiry, but only num_strikes above and below current price
all_strikes = sorted([s for s in params.strikes if s > 0])
strikes_below = sorted([s for s in all_strikes if s < current_price], reverse=True)[:num_strikes]
strikes_above = sorted([s for s in all_strikes if s > current_price])[:num_strikes]
valid_strikes = sorted(strikes_below) + strikes_above

# Helper to find strike by delta
def find_strike_by_delta(right, target_delta):
    best_strike = None
    best_delta = None
    min_diff = float('inf')
    for strike in valid_strikes:
        opt = Option(symbol, expiry, strike, right, exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
        ticker = ib.reqMktData(opt)
        # Wait up to 2 seconds for delta to become available
        for _ in range(10):
            ib.sleep(0.1)
            if ticker.modelGreeks and ticker.modelGreeks.delta is not None:
                break
        if ticker.modelGreeks and ticker.modelGreeks.delta is not None:
            diff = abs(ticker.modelGreeks.delta - target_delta)
            if diff < min_diff:
                min_diff = diff
                best_strike = strike
                best_delta = ticker.modelGreeks.delta
        ib.cancelMktData(opt)
    if best_strike is not None:
        print(f"Selected {right} strike {best_strike} with closest delta {best_delta:.3f} (target was {target_delta})")
        if min_diff > 0.05:
            print(f"⚠️ Closest delta is {min_diff:.3f} away from target.")
    else:
        print(f"❌ No strike found for {right} with delta near {target_delta}")
    return best_strike

# 2) If long_call_delta and long_put_delta are null, use width to select long legs
short_call_strike = find_strike_by_delta('C', short_call_delta)
short_put_strike = find_strike_by_delta('P', short_put_delta)
if long_call_delta is not None:
    long_call_strike = find_strike_by_delta('C', long_call_delta)
else:
    long_call_strike = short_call_strike + width
if long_put_delta is not None:
    long_put_strike = find_strike_by_delta('P', long_put_delta)
else:
    long_put_strike = short_put_strike - width

print(f"Short Call: {short_call_strike}, Long Call: {long_call_strike}, Short Put: {short_put_strike}, Long Put: {long_put_strike}")

# Build option contracts for the legs
short_call = Option(symbol, expiry, short_call_strike, 'C', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
long_call = Option(symbol, expiry, long_call_strike, 'C', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
short_put = Option(symbol, expiry, short_put_strike, 'P', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
long_put = Option(symbol, expiry, long_put_strike, 'P', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)

# Build combo contract for iron condor
combo = Contract()
combo.symbol = symbol
combo.secType = 'BAG'
combo.exchange = exchange
combo.currency = currency

combo.comboLegs = [
    ComboLeg(conId=ib.reqContractDetails(short_call)[0].contract.conId, ratio=1, action='SELL', exchange=exchange),
    ComboLeg(conId=ib.reqContractDetails(long_call)[0].contract.conId, ratio=1, action='BUY', exchange=exchange),
    ComboLeg(conId=ib.reqContractDetails(short_put)[0].contract.conId, ratio=1, action='SELL', exchange=exchange),
    ComboLeg(conId=ib.reqContractDetails(long_put)[0].contract.conId, ratio=1, action='BUY', exchange=exchange),
]

# Wait for trade window
def get_today_time(tstr):
    now = datetime.now()
    hour, minute = map(int, tstr.split(':'))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

start_time = get_today_time(trade_start_time)
end_time = get_today_time(trade_end_time)
if end_time <= start_time:
    end_time += timedelta(days=1)

if datetime.now() < start_time:
    wait = (start_time - datetime.now()).total_seconds()
    print(f"Waiting {wait/60:.1f} minutes to start...")
    time.sleep(wait)

# Trade logic
order = MarketOrder('BUY', 2)
order_filled = False
while datetime.now() < end_time:
    trade = ib.placeOrder(combo, order)
    print("Submitted market order. Waiting for fill...")
    ib.sleep(10)
    if trade.orderStatus.status == 'Filled':
        order_filled = True
        fill_price = trade.orderStatus.avgFillPrice
        print(f"Filled at: {fill_price}")

        def round_to_tick(price):
            return round(price * 20) / 20 if price < 3 else round(price * 10) / 10

        profit_target_price = round_to_tick(fill_price * 0.8)
        stop_loss_price = round_to_tick(fill_price * 1.15)
        print(f"Placing profit target: {profit_target_price}, stop loss: {stop_loss_price}")

        profit_order = LimitOrder('SELL', 1, profit_target_price)
        stop_order = StopOrder('SELL', 1, stop_loss_price)
        
        profit_trade = ib.placeOrder(combo, profit_order)
        stop_trade = ib.placeOrder(combo, stop_order)

        while profit_trade.orderStatus.status not in ['Filled', 'Cancelled'] and stop_trade.orderStatus.status not in ['Filled', 'Cancelled']:
            ib.sleep(5)
            print(f"Profit: {profit_trade.orderStatus.status}, Stop: {stop_trade.orderStatus.status}")
            ib.reqAllOpenOrders()

        if profit_trade.orderStatus.status == 'Filled':
            print("✅ Profit target filled!")
            ib.cancelOrder(stop_trade.order)
        elif stop_trade.orderStatus.status == 'Filled':
            print("⚠️ Stop loss triggered!")
            ib.cancelOrder(profit_trade.order)
        else:
            print(f"Orders ended - Profit: {profit_trade.orderStatus.status}, Stop: {stop_trade.orderStatus.status}")
        break
    else:
        print(f"Order not filled yet, retrying in {retry_interval_min} minutes...")
        ib.sleep(retry_interval_min * 60)

if not order_filled:
    print("Trade window closed. Order not filled.")

ib.disconnect()