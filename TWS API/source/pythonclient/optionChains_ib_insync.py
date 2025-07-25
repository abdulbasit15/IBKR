from ib_insync import *
import time

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=11)

# Define SPX Index Contract
spx = Index('SPX', 'CBOE')

# Get Contract Details (to fetch conId)
contract_details = ib.reqContractDetails(spx)
if not contract_details:
    print("❌ SPX contract not found. Check subscriptions.")
    ib.disconnect()
    exit()

spx_conId = contract_details[0].contract.conId

# Request Option Chain Parameters for both trading classes
opt_params_spx = ib.reqSecDefOptParams('SPX', '', 'IND', spx_conId)
opt_params_spxw = ib.reqSecDefOptParams('SPX', '', 'IND', spx_conId)

# Filter for CBOE and tradingClass SPX and SPXW
params_spx = [p for p in opt_params_spx if p.exchange == 'CBOE' and p.tradingClass == 'SPX']
params_spxw = [p for p in opt_params_spxw if p.exchange == 'CBOE' and p.tradingClass == 'SPXW']

# Combine all expirations and strikes
all_expirations = set()
all_strikes = set()
for p in params_spx + params_spxw:
    all_expirations.update(p.expirations)
    all_strikes.update(p.strikes)

all_expirations = sorted(all_expirations)
all_strikes = sorted(all_strikes)

print(f"✅ Got {len(all_strikes)} strikes and {len(all_expirations)} expirations (including daily/weekly).")
print("All available expirations (including daily/weekly):")
for exp in all_expirations:
    print(exp)

# Get current SPX index price
spx_ticker = ib.reqMktData(spx)
timeout = 10  # seconds
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
        current_price = 6360  # fallback default

print(f"Last: {spx_ticker.last}, Bid: {spx_ticker.bid}, Ask: {spx_ticker.ask}, MarketPrice: {spx_ticker.marketPrice()}")
print(f"✅ Current SPX price: {current_price}")

# Choose an Expiration (for example, the first available)
chosen_exp = all_expirations[0]
print("Chosen expiration:", chosen_exp)

# Find the SecDefOptParams object that contains the chosen expiration
chosen_params = None
for p in params_spx + params_spxw:
    if chosen_exp in p.expirations:
        chosen_params = p
        break

if not chosen_params:
    print(f"No option params found for expiration {chosen_exp}")
    ib.disconnect()
    exit()

valid_strikes = sorted([s for s in chosen_params.strikes if s > 0])

# Get N strikes above and below current price
N = 20
strikes_below = sorted([s for s in valid_strikes if s < current_price], reverse=True)[:N]
strikes_above = sorted([s for s in valid_strikes if s > current_price])[:N]
strikes_to_check = sorted(strikes_below) + strikes_above
print(f"Selected strikes: {strikes_to_check}")

# Collect Matching Option Contracts (try both trading classes)
options_to_check = []
for strike in strikes_to_check:
    for right in ['C', 'P']:
        for trading_class in ['SPXW']: # for trading_class in ['SPX', 'SPXW']:
            opt = Option(
                'SPX',
                chosen_exp,
                strike,
                right,
                'CBOE',
                currency='USD',
                multiplier='100',
                tradingClass=trading_class
            )
            options_to_check.append(opt)

# Request Market Data for Options (Delta will come in ticker.greeks)
tickers = ib.reqTickers(*options_to_check)
ib.sleep(3)

# Print Delta and Price for each option
for ticker in tickers:
    if ticker.modelGreeks:
        delta = ticker.modelGreeks.delta
        price = ticker.marketPrice()
        print(f"TradingClass: {ticker.contract.tradingClass} | Expiry: {ticker.contract.lastTradeDateOrContractMonth} | {ticker.contract.localSymbol} | Strike: {ticker.contract.strike} | Right: {ticker.contract.right} | Delta: {delta:.3f} | Price: {price}")

ib.disconnect()