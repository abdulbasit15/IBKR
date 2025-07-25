import json
import time
from ib_insync import *

# Load config
with open('C:/Repo/IBKR/TWS API/source/pythonclient/ic.json', 'r') as f:
    config = json.load(f)

symbol = config['symbol']
expiry = config['expiry']
exchange = config['exchange']
currency = config['currency']
multiplier = config['multiplier']
tradingClass = config['tradingClass']
width = config['width']
retry_interval_min = config['retry_interval_min']
short_call_delta = config['short_call_delta']
long_call_delta = config['long_call_delta']
short_put_delta = config['short_put_delta']
long_put_delta = config['long_put_delta']

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

contract = Index('SPX', 'CBOE')
details = ib.reqContractDetails(contract)
print(details)
# Get option chain
chains = ib.reqSecDefOptParams(symbol, '', 'IND', exchange)
# Try to find a matching chain, fallback to first if not found
chain = next((c for c in chains if c.tradingClass == tradingClass and c.exchange == exchange), None)
if chain is None:
    print(f"⚠️ No chain found for tradingClass={tradingClass} and exchange={exchange}. Using closest available chain:")
    # Print all available chains for reference
    for c in chains:
        print(f"tradingClass={c.tradingClass}, exchange={c.exchange}")
    chain = chains[0]
    tradingClass = chain.tradingClass
    exchange = chain.exchange

strikes = sorted(chain.strikes)
# Filter strikes within a reasonable range
strikes = [s for s in strikes if s > 0]

def get_strike_by_delta(right, target_delta):
    best_strike = None
    min_diff = float('inf')
    for strike in strikes:
        opt = Option(symbol, expiry, strike, right, exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
        ticker = ib.reqMktData(opt, '', False, False)
        ib.sleep(0.2)  # Give IB time to respond
        delta = None
        if ticker.modelGreeks:
            delta = ticker.modelGreeks.delta
            if delta is not None:
                diff = abs(delta - target_delta)
                if diff < min_diff:
                    min_diff = diff
                    best_strike = strike
        ib.cancelMktData(opt)
    return best_strike

# Find strikes based on delta from config
short_call_strike = get_strike_by_delta('C', short_call_delta)
long_call_strike = get_strike_by_delta('C', long_call_delta)
short_put_strike = get_strike_by_delta('P', short_put_delta)
long_put_strike = get_strike_by_delta('P', long_put_delta)

print(f"Selected strikes: Short Call {short_call_strike}, Long Call {long_call_strike}, Short Put {short_put_strike}, Long Put {long_put_strike}")

# Qualify option contracts
short_call = ib.qualifyContracts(Option(symbol, expiry, short_call_strike, 'C', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass))[0]
long_call = ib.qualifyContracts(Option(symbol, expiry, long_call_strike, 'C', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass))[0]
short_put = ib.qualifyContracts(Option(symbol, expiry, short_put_strike, 'P', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass))[0]
long_put = ib.qualifyContracts(Option(symbol, expiry, long_put_strike, 'P', exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass))[0]

# Build combo contract
combo = Contract()
combo.symbol = symbol
combo.secType = 'BAG'
combo.currency = currency
combo.exchange = exchange
combo.comboLegs = [
    ComboLeg(conId=short_call.conId, ratio=1, action='SELL', exchange=exchange),
    ComboLeg(conId=long_call.conId, ratio=1, action='BUY', exchange=exchange),
    ComboLeg(conId=short_put.conId, ratio=1, action='SELL', exchange=exchange),
    ComboLeg(conId=long_put.conId, ratio=1, action='BUY', exchange=exchange)
]

order = MarketOrder('BUY', 1)

# Submit and retry if not filled
while True:
    trade = ib.placeOrder(combo, order)
    ib.sleep(10)  # Give IB time to process
    ib.waitOnUpdate()
    if trade.orderStatus.status == 'Filled':
        print("✅ Iron Condor order filled!")
        break
    else:
        print(f"⏳ Order not filled, retrying in {retry_interval_min} minutes...")
        ib.cancelOrder(order)
        time.sleep(retry_interval_min * 60)

ib.disconnect()