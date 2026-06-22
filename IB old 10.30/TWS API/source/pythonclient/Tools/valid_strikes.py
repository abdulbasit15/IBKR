from ib_insync import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Define the underlying (e.g., SPY)
option_contract = Option('SPY', '', 0.0, 'C', 'SMART')

# Request all matching option contracts
contracts = ib.reqContractDetails(option_contract)

# Extract all unique strike prices
valid_strikes = sorted({c.contract.strike for c in contracts})

# Print some of them
print(valid_strikes[:10])
