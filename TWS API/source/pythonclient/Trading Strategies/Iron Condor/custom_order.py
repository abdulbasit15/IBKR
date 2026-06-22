import time
import math
from decimal import Decimal, ROUND_HALF_UP
from ib_insync import LimitOrder, MarketOrder

def place_custom_order(ib, contract, quantity, log, action='BUY', price_increment=0.05, account=None):
    """
    Places a custom order that tries to fill at the bid/ask and then walks the price.
    For a BUY order, it starts at the bid and walks up to the ask.
    For a SELL order, it starts at the ask and walks down to the bid.
    """
    def to_2dp(value):
        return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    log("Starting custom order logic")
    price_increment = to_2dp(price_increment)
    ticker = ib.reqMktData(contract, '', False, False)
    ib.sleep(5)  # Allow time for the ticker to update

    bid = to_2dp(ticker.bid)
    ask = to_2dp(ticker.ask)

    # Handle case where ticker might not have updated yet # or bid <= 0 or ask <= 0 or bid >= ask:
    if math.isnan(bid) or math.isnan(ask):
        log(f"Invalid or missing bid/ask prices: Bid={bid}, Ask={ask}. Falling back to MarketOrder.")
        order = MarketOrder(action, quantity)
        if account:
            order.account = account
        trade = ib.placeOrder(contract, order)
        return trade

    log(f"Initial Bid: {bid:.2f}, Ask: {ask:.2f}")
    mid_price = to_2dp((bid + ask) / 2)
    price = mid_price
    log(f"Starting at midpoint price: {price:.2f}")


    while True:
        # Round price to nearest tick size, assuming 0.01 for now
        price = to_2dp(price)
        order = LimitOrder(action, quantity, price)
        if account:
            order.account = account
        trade = ib.placeOrder(contract, order)
        log(f"Placed LimitOrder to {action} at {price:.2f}. OrderID: {trade.order.orderId}")

        ib.sleep(10)  # Wait for 10 seconds

        if trade.orderStatus.status == 'Filled':
            log(f"✅ Order filled at {trade.orderStatus.avgFillPrice}")
            return trade
        else:
            log(f"Order not filled at {price:.2f}. Status: {trade.orderStatus.status}. Cancelling.")
            ib.cancelOrder(trade.order)
            ib.sleep(1) # Give time for cancellation to process

            if action.upper() == 'BUY':
                if price >= ask:
                    log("Price has reached ask. Exiting custom order logic.")
                    break
                price = to_2dp(min(price + price_increment, ask)) # Do not go over ask
                log(f"Increasing price to {price:.2f}")
            else: # SELL
                if price <= bid:
                    log("Price has reached bid. Exiting custom order logic.")
                    break
                price = to_2dp(max(price - price_increment, bid)) # Do not go under bid
                log(f"Decreasing price to {price:.2f}")

    log("Custom order logic failed to fill the order. Placing a market order as a final attempt.")
    final_order = MarketOrder(action, quantity)
    if account:
        final_order.account = account
    final_trade = ib.placeOrder(contract, final_order)
    ib.sleep(5)

    if final_trade.orderStatus.status == 'Filled':
        log(f"✅ Final market order filled at {final_trade.orderStatus.avgFillPrice}")
        return final_trade
    else:
        log("❌ Final market order also failed to fill.")
        ib.cancelOrder(final_trade.order)
        return None