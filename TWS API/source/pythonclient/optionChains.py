import time
import threading
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract

symbol = "SPX"
exchange = "CBOE"
currency = "USD"
expiry = "20250822"  # Example expiry

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.underlyingConId = None
        self.strikes = []
        self.last_price = None
        self.call_prices = {}
        self.put_prices = {}

    def nextValidId(self, orderId):
        self.nextOrderId = orderId

    def contractDetails(self, reqId, details):
        self.underlyingConId = details.contract.conId
        print(f"Underlying ConId: {self.underlyingConId}")

    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):
        self.strikes = sorted([s for s in strikes if s > 0])

    def tickPrice(self, reqId, tickType, price, attrib):
        if tickType == 4:  # Last price
            if reqId >= 2000 and reqId < 3000:
                self.call_prices[reqId] = price
                print(f"Call Strike {reqId-2000}: Price {price}")
            elif reqId >= 3000 and reqId < 4000:
                self.put_prices[reqId] = price
                print(f"Put Strike {reqId-3000}: Price {price}")
            elif reqId == 999:
                self.last_price = price
                print(f"SPX Last Price: {price}")

def run_loop(app):
    app.run()

app = IBApp()
app.connect('127.0.0.1', 7497, 1)
thread = threading.Thread(target=run_loop, args=(app,), daemon=True)
thread.start()

# Request contract details for SPX to get conId
spx_contract = Contract()
spx_contract.symbol = symbol
spx_contract.secType = "IND"
spx_contract.exchange = exchange
spx_contract.currency = currency
app.reqContractDetails(1, spx_contract)

while app.underlyingConId is None:
    time.sleep(0.1)

app.reqSecDefOptParams(2, symbol, "", "IND", app.underlyingConId)
time.sleep(2)

# Request current SPX index price
reqId_spx = 999
app.reqMktData(reqId_spx, spx_contract, "", False, False, [])
time.sleep(2)
current_price = app.last_price if app.last_price is not None else 6300

# Get 20 closest strikes
if current_price:
    closest_strikes = sorted(app.strikes, key=lambda x: abs(x - current_price))[:20]
else:
    closest_strikes = app.strikes[:20]

print(f"Using {len(closest_strikes)} strikes closest to price {current_price}")

# Request market data for each strike and print call and put prices
for i, strike in enumerate(closest_strikes):
    # Call
    print(f"Requesting Call for SPX, Strike, expiry:  {strike} , {expiry}" )
    call_contract = Contract()
    call_contract.symbol = symbol
    call_contract.secType = "OPT"
    call_contract.exchange = exchange
    call_contract.currency = currency
    call_contract.lastTradeDateOrContractMonth = expiry
    call_contract.strike = strike
    call_contract.right = "C"
    call_contract.multiplier = "100"
    call_contract.tradingClass = "SPX"
    reqId_call = 2000 + i
    app.reqMktData(reqId_call, call_contract, "", False, False, [])

    # Put
    print(f"Requesting Put for SPX, Strike, expiry:  {strike} , {expiry}" )
    put_contract = Contract()
    put_contract.symbol = symbol
    put_contract.secType = "OPT"
    put_contract.exchange = exchange
    put_contract.currency = currency
    put_contract.lastTradeDateOrContractMonth = expiry
    put_contract.strike = strike
    put_contract.right = "P"
    put_contract.multiplier = "100"
    put_contract.tradingClass = "SPX"
    reqId_put = 3000 + i
    app.reqMktData(reqId_put, put_contract, "", False, False, [])

    time.sleep(0.2)
    # app.cancelMktData(reqId_call)
    # app.cancelMktData(reqId_put)

time.sleep(2)
app.disconnect()