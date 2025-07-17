import json
from ib_insync import *
import numpy as np

# Remove reading from JSON file
# Set symbol and duration_year directly
symbol = 'SPX'
duration_year = 1

# Connect to IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=2)

# Define SPX index
spx = Index(symbol, 'CBOE')

# Pull daily price bars
bars = ib.reqHistoricalData(
    spx,
    endDateTime='',
    durationStr=f'{duration_year} Y',
    barSizeSetting='1 day',
    whatToShow='TRADES',
    useRTH=True
)

# Pull implied volatility history
iv_bars = ib.reqHistoricalData(
    spx,
    endDateTime='',
    durationStr=f'{duration_year} Y',
    barSizeSetting='1 day',
    whatToShow='OPTION_IMPLIED_VOLATILITY',
    useRTH=True
)

# Convert to DataFrame
df_price = util.df(bars)[['date', 'close']]
df_iv = util.df(iv_bars)[['date', 'close']]
df_iv.rename(columns={'close': 'IV'}, inplace=True)
df_iv['IV'] = df_iv['IV'] * 100  # <-- Multiply IV by 100

# Merge data
df = df_price.merge(df_iv, on='date')

# Calculate expected move
df['Expected_Move'] = df['close'] * (df['IV'] / 100) * np.sqrt(1 / 365)

# Add SPX low and high columns
df['SPX_Low'] = df['close'] - df['Expected_Move']
df['SPX_High'] = df['close'] + df['Expected_Move']

# Round values to 2 decimal places
df['IV'] = df['IV'].round(2)
df['Expected_Move'] = df['Expected_Move'].round(2)
df['SPX_Low'] = df['SPX_Low'].round(2)
df['SPX_High'] = df['SPX_High'].round(2)
df['close'] = df['close'].round(2)

# Save to CSV
df.to_csv(f"{symbol}_with_IV_ExpectedMove.csv", index=False)
print(f"✅ File saved: {symbol}_with_IV_ExpectedMove.csv")

ib.disconnect()