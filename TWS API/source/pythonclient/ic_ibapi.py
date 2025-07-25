import json
import time
import threading
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ComboLeg
from ibapi.order import Order

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

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.strikes = []
        self.delta_map = {}
        self.order_filled = False
        self.nextOrderId = None
        self.underlyingConId = None  # <-- Add this line

    def nextValidId(self, orderId):
        self.nextOrderId = orderId
        
    def contractDetails(self, reqId, details):
        self.underlyingConId = details.contract.conId  # <-- Set attribute here
        print(f"✅ Underlying ConId for {symbol}: {self.underlyingConId}")

    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):
        self.strikes = sorted([s for s in strikes if s > 0])

    def tickOptionComputation(self, reqId, tickType, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        self.delta_map[reqId] = delta

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        if status == 'Filled':
            self.order_filled = True
            print(f"✅ Iron Condor order {orderId} filled!")

def run_loop(app):
    app.run()

app = IBApp()
app.connect('127.0.0.1', 7497, 1)

thread = threading.Thread(target=run_loop, args=(app,), daemon=True)
thread.start()

# 1. Create the underlying contract
contract = Contract()
contract.symbol = symbol
contract.secType = "IND"
contract.exchange = exchange
contract.currency = currency

# 2. Request contract details to get conId
app.reqContractDetails(1, contract)
time.sleep(2)  # Wait for response

# 3. In your EWrapper, implement contractDetails to capture conId
def contractDetails(self, reqId, details):
    self.underlyingConId = details.contract.conId

# 4. After you have underlyingConId, call reqSecDefOptParams
chains = app.reqSecDefOptParams(2, symbol, "", "IND", app.underlyingConId)

time.sleep(2)  # Wait for strikes to populate

def get_strike_by_delta(right, target_delta):
    best_strike = None
    min_diff = float('inf')
    for i, strike in enumerate(app.strikes):
        opt_contract = Contract()
        opt_contract.symbol = symbol
        opt_contract.secType = "OPT"
        opt_contract.exchange = exchange
        opt_contract.currency = currency
        opt_contract.lastTradeDateOrContractMonth = expiry
        opt_contract.strike = strike
        opt_contract.right = right
        opt_contract.multiplier = multiplier
        opt_contract.tradingClass = tradingClass

        reqId = 1000 + i
        app.reqMktData(reqId, opt_contract, "", False, False, [])
        time.sleep(0.2)
        delta = app.delta_map.get(reqId)
        if delta is not None:
            diff = abs(delta - target_delta)
            if diff < min_diff:
                min_diff = diff
                best_strike = strike
        app.cancelMktData(reqId)
    return best_strike

# Find strikes based on delta from config
short_call_strike = get_strike_by_delta('C', short_call_delta)
long_call_strike = get_strike_by_delta('C', long_call_delta)
short_put_strike = get_strike_by_delta('P', short_put_delta)
long_put_strike = get_strike_by_delta('P', long_put_delta)

print(f"Selected strikes: Short Call {short_call_strike}, Long Call {long_call_strike}, Short Put {short_put_strike}, Long Put {long_put_strike}")

# Build combo contract
combo = Contract()
combo.symbol = symbol
combo.secType = 'BAG'
combo.currency = currency
combo.exchange = exchange
combo.comboLegs = []

def add_leg(strike, right, action):
    leg = ComboLeg()
    leg.conId = 0  # You should use contractDetails to get conId for each leg
    leg.ratio = 1
    leg.action = action
    leg.exchange = exchange
    combo.comboLegs.append(leg)

add_leg(short_call_strike, 'C', 'SELL')
add_leg(long_call_strike, 'C', 'BUY')
add_leg(short_put_strike, 'P', 'SELL')
add_leg(long_put_strike, 'P', 'BUY')

order = Order()
order.action = "SELL"
order.orderType = "MKT"
order.totalQuantity = 1

# Submit and retry if not filled
while not app.order_filled:
    if app.nextOrderId is not None:
        app.placeOrder(app.nextOrderId, combo, order)
        print(f"Order {app.nextOrderId} submitted.")
        time.sleep(10)
        if not app.order_filled:
            print(f"⏳ Order not filled, retrying in {retry_interval_min} minutes...")
            time.sleep(retry_interval_min * 60)
    else:
        time.sleep(1)

app.disconnect()