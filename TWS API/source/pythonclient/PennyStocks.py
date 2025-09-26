from ib_insync import *
import talib
import time

# Connect to TWS / Gateway
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Create Scanner Filter for US Small Cap Stocks
scanner = ScannerSubscription(
    instrument='STK',
    locationCode='STK.US.MAJOR',   # US stocks
    scanCode='MOST_ACTIVE',        # you can try TOP_PERC_GAIN, HOT_BY_VOLUME, etc.
    abovePrice=1,
    belowPrice=15                  # usually small caps < $15
)

# Function to compute RSI
def get_rsi(contract, period=14):
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 min',
        whatToShow='TRADES',
        useRTH=True,
        formatDate=1
    )
    df = util.df(bars)
    if len(df) < period:
        return None
    close = df['close'].values
    rsi = talib.RSI(close, timeperiod=period)
    return rsi[-1]

# Place bracket order
def place_bracket_order(contract, qty, entry_price):
    takeProfit = entry_price * 1.20
    stopLoss   = entry_price * 0.80
    bracket = ib.bracketOrder(
        action='BUY',
        quantity=qty,
        limitPrice=None,  # Market entry
        takeProfitPrice=takeProfit,
        stopLossPrice=stopLoss
    )
    for o in bracket:
        ib.placeOrder(contract, o)
    print(f"🚀 Order placed: Entry {entry_price}, TP {takeProfit}, SL {stopLoss}")

# Main Loop
while True:
    # Request scanner results
    scan_results = ib.reqScannerData(scanner, 50)  # up to 50 symbols
    
    for res in scan_results:
        contract = res.contractDetails.contract
        ib.qualifyContracts(contract)
        
        rsi = get_rsi(contract)
        if not rsi:
            continue
        
        print(f"{contract.symbol} RSI: {rsi}")
        
        if rsi > 90:
            md = ib.reqMktData(contract, '', False, False)
            ib.sleep(2)  # wait for price snapshot
            price = md.last if md.last else None
            
            if price:
                place_bracket_order(contract, qty=10, entry_price=price)
    
    time.sleep(5)  # refresh scanner every few seconds