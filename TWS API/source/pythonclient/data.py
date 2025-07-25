import json
from ib_insync import *

# Load symbol from config.json
with open('C:/Repo/IBKR/TWS API/source/pythonclient/config.json', 'r') as f:
    config = json.load(f)

symbol = config['symbol']

# Connect to IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Define the index contract
contract = Index(symbol, 'CBOE', currency='USD')

# Define option legs (example: call and put, same expiry/strike)
expiry = '20250717'  # Update to desired expiry
strike = 6300       # Update to desired strike

call_option = Option(
    symbol, expiry, strike, 'C', 'CBOE', currency='USD', multiplier='100', tradingClass='SPX'
)
put_option = Option(
    symbol, expiry, strike, 'P', 'CBOE', currency='USD', multiplier='100', tradingClass='SPX'
)

# Request market data for index and options
ticker_index = ib.reqMktData(contract)
ticker_call = ib.reqMktData(call_option)
ticker_put = ib.reqMktData(put_option)

# Wait for price update
ib.sleep(2)

# Print latest prices
print(f"✅ Latest price for {symbol} index: {ticker_index.marketPrice()}")
print(f"✅ Call option ({expiry}, {strike}): {ticker_call.marketPrice()}")
print(f"✅ Put option ({expiry}, {strike}): {ticker_put.marketPrice()}")

# Disconnect
ib.disconnect()