import json
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import threading
import time

# Load symbol from config.json
with open('C:/Repo/IBKR/TWS API/source/pythonclient/config.json', 'r') as f:
    config = json.load(f)

symbol = config['symbol']

class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.prices = {}

    def tickPrice(self, reqId, tickType, price, attrib):
        if tickType == 4:  # Last price
            self.prices[reqId] = price
            if reqId == 1:
                print(f"✅ Live SPX index price: {price}")
            elif reqId == 2:
                print(f"✅ Live SPX 6300 Call price: {price}")
            elif reqId == 3:
                print(f"✅ Live SPX 6300 Put price: {price}")

def run_loop(app):
    app.run()

app = IBApp()
app.connect('127.0.0.1', 7497, 1)

# Define the SPX index contract
contract = Contract()
contract.symbol = symbol
contract.secType = "IND"
contract.exchange = "CBOE"
contract.currency = "USD"

# Define call and put option contracts for SPX, 6300 strike, example expiry
expiry = "20250717"  # Update as needed

call_option = Contract()
call_option.symbol = symbol
call_option.secType = "OPT"
call_option.exchange = "CBOE"
call_option.currency = "USD"
call_option.lastTradeDateOrContractMonth = expiry
call_option.strike = 6300
call_option.right = "C"
call_option.multiplier = "100"

put_option = Contract()
put_option.symbol = symbol
put_option.secType = "OPT"
put_option.exchange = "CBOE"
put_option.currency = "USD"
put_option.lastTradeDateOrContractMonth = expiry
put_option.strike = 6300
put_option.right = "P"
put_option.multiplier = "100"

# Start the message processing thread
thread = threading.Thread(target=run_loop, args=(app,), daemon=True)
thread.start()

# Request market data for index, call, and put
app.reqMktData(1, contract, "", False, False, [])
app.reqMktData(2, call_option, "", False, False, [])
app.reqMktData(3, put_option, "", False, False, [])

# Keep script running to print live prices
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    app.disconnect()