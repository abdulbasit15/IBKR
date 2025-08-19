import os
import sys
import json
import time
import pandas as pd
import threading
import asyncio
from datetime import datetime, timedelta
from ib_insync import *
from ib_insync import ComboLeg, Contract
from custom_order import place_custom_order
from collections import Counter

# Load config from same directory as executable
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    config_path = os.path.join(os.path.dirname(sys.executable), 'ic.json')
else:
    # Running as script
    config_path = os.path.join(os.path.dirname(__file__), 'ic.json')

with open(config_path, 'r') as f:
    config = json.load(f)

def run_strategy(strategy_name, strategy_config, client_id):
    # Get base directory (same as executable)
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(__file__)
    
    # Setup logging
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    # Create safe filename from strategy name
    safe_strategy_name = strategy_name.replace(' ', '_').replace('-', '').replace('.', '').replace('__', '_')
    log_filename = f"{safe_strategy_name}_{timestamp}.log"
    log_path = os.path.join(base_dir, log_filename)

    # Setup trade journal
    journal_filename = f"{strategy_config['symbol']}_journal.xlsx"
    journal_path = os.path.join(base_dir, journal_filename)

    def log(message):
        timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp_str}] {message}"
        console_message = f"[{timestamp_str}] [{strategy_name}] {message}"
        print(console_message)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_message + '\n')

    def write_journal_entry(trade_data, strategy='Iron Condor'):
        columns = ['Date', 'Symbol', 'Expiry', 'Strategy', 'Entry_Price', 'Exit_Price', 'PnL', 'Result', 'Short_Call', 'Long_Call', 'Short_Put', 'Long_Put', 'SPX_Price']
        
        if os.path.exists(journal_path):
            with pd.ExcelFile(journal_path) as xls:
                sheets = {sheet: pd.read_excel(xls, sheet) for sheet in xls.sheet_names}
        else:
            sheets = {}
        
        if strategy not in sheets:
            sheets[strategy] = pd.DataFrame(columns=columns)
        
        new_row = pd.DataFrame([trade_data], columns=columns)
        sheets[strategy] = pd.concat([sheets[strategy], new_row], ignore_index=True)
        
        with pd.ExcelWriter(journal_path, engine='openpyxl') as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

    symbol = strategy_config['symbol']
    secType = strategy_config['secType']
    exchange = strategy_config['exchange']
    currency = strategy_config['currency']
    multiplier = str(strategy_config['multiplier'])
    tradingClass = strategy_config['tradingClass']
    short_call_delta = strategy_config['short_call_delta']
    short_put_delta = strategy_config['short_put_delta']
    long_call_delta = strategy_config['long_call_delta']
    long_put_delta = strategy_config['long_put_delta']
    width = strategy_config['width']
    retry_interval_min = strategy_config['retry_interval_min']
    expiry = strategy_config['expiry']
    trade_start_time = strategy_config['trade_start_time']
    trade_end_time = strategy_config['trade_end_time']
    max_capital = strategy_config.get('max_capital', 50000)
    profit_target = strategy_config.get('profit_target', 0.2)  # 20% default
    stop_loss = strategy_config.get('stop_loss', 0.15)  # 15% default
    price_increment = strategy_config.get('price_increment', 0.05)  # Default increment

    log(f"🚀 Starting {strategy_name}")
    log(f"📊 Config: {symbol} {strategy_config.get('expiry', 'auto')} on {exchange}")
    log(f"💰 Max Capital: ${max_capital:,}")
    log(f"🎯 Profit Target: {profit_target*100:.0f}% | Stop Loss: {stop_loss*100:.0f}%")
    log(f"📄 Log file: {log_filename}")
    log(f"📊 Journal file: {journal_filename}")

    # Set up event loop for threading
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    ib = IB()
    log(f"🔌 Connecting to TWS with client ID {client_id}...")
    
    # Try connection with error handling and timeout
    try:
        # Try TWS port first, then IB Gateway port
        ports = [7497, 4002]
        connected = False
        for port in ports:
            try:
                log(f"🔌 Attempting connection to port {port}...")
                ib.connect('127.0.0.1', port, clientId=client_id, timeout=10)
                log(f"✅ Connected to {'TWS' if port == 7497 else 'IB Gateway'} on port {port}")
                connected = True
                break
            except (ConnectionRefusedError, TimeoutError) as e:
                log(f"⚠️ Port {port} failed: {type(e).__name__}")
                continue
        
        if not connected:
            raise ConnectionRefusedError("Both TWS (7497) and IB Gateway (4002) ports failed")
        log("✅ Connected to TWS")
    except ConnectionRefusedError:
        log("❌ TWS connection refused. Please check:")
        log("   1. TWS/IB Gateway is running")
        log("   2. API is enabled in TWS (File > Global Configuration > API > Settings)")
        log("   3. Port 7497 is correct (7497 for TWS, 4002 for IB Gateway)")
        log("   4. 'Enable ActiveX and Socket Clients' is checked")
        return
    except (ConnectionRefusedError, TimeoutError) as e:
        log(f"❌ Connection failed: {type(e).__name__}")
        log("💡 Troubleshooting tips:")
        log("   1. Ensure TWS/IB Gateway is running")
        log("   2. Check API settings: File > Global Configuration > API > Settings")
        log("   3. Enable 'ActiveX and Socket Clients'")
        log("   4. Verify client ID is unique")
        return
    except Exception as e:
        log(f"❌ Connection failed: {e}")
        return

    # Get underlying contract (Index or Stock)
    log(f"📈 Getting {symbol} contract...")
    if secType in ['IND', 'INDX']:  # Index symbols
        underlying = Index(symbol, exchange)
        # sec_type = 'IND'
    else:  # Stock/ETF symbols like QQQ
        underlying = Stock(symbol, exchange, currency)
        # sec_type = 'STK'
    
    contract_details = ib.reqContractDetails(underlying)
    if not contract_details:
        log(f"❌ {symbol} contract not found.")
        ib.disconnect()
        return
    underlying_conId = contract_details[0].contract.conId
    log(f"✅ {symbol} contract found, conId: {underlying_conId}")

    log(f"🔍 Getting option chain for {exchange} {tradingClass}...")
    opt_params = ib.reqSecDefOptParams(symbol, '', secType, underlying_conId)
    params = [p for p in opt_params if p.exchange == exchange and p.tradingClass == tradingClass]
    if not params:
        log(f"❌ No option params for {exchange} {tradingClass}")
        ib.disconnect()
        return
    params = params[0]
    log(f"✅ Option chain loaded: {len(params.expirations)} expirations, {len(params.strikes)} strikes")

    # Select expiry
    log("📅 Selecting expiry...")
    expirations = sorted(params.expirations)
    if not expiry:
        today = datetime.now().strftime('%Y%m%d')
        expiry = next(e for e in expirations if e >= today)
        log(f"✅ Auto-selected next expiry: {expiry}")
    else:
        log(f"✅ Using configured expiry: {expiry}")

    # Get current price
    log(f"💰 Getting {symbol} current price...")
    underlying_ticker = ib.reqMktData(underlying)
    timeout = 10
    start = time.time()
    while (underlying_ticker.marketPrice() is None or underlying_ticker.marketPrice() != underlying_ticker.marketPrice()) and time.time() - start < timeout:
        ib.sleep(0.2)
    current_price = underlying_ticker.marketPrice()
    if current_price is None or current_price != current_price:
        if underlying_ticker.bid > 0 and underlying_ticker.ask > 0:
            current_price = (underlying_ticker.bid + underlying_ticker.ask) / 2
            log(f"⚠️ Using bid/ask midpoint: {current_price}")
        elif underlying_ticker.bid > 0:
            current_price = underlying_ticker.bid
            log(f"⚠️ Using bid price: {current_price}")
        elif underlying_ticker.ask > 0:
            current_price = underlying_ticker.ask
            log(f"⚠️ Using ask price: {current_price}")
        else:
            fallback_price = 6360 if symbol == 'SPX' else 560  # Different fallbacks
            current_price = fallback_price
            log(f"⚠️ Using fallback price: {current_price}")
    else:
        log(f"✅ {symbol} market price: {current_price}")
    
    # Check trade window first
    def get_today_time(tstr):
        now = datetime.now()
        hour, minute = map(int, tstr.split(':'))
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    log(f"⏰ Trade window: {trade_start_time} - {trade_end_time}")
    start_time = get_today_time(trade_start_time)
    end_time = get_today_time(trade_end_time)
    if end_time <= start_time:
        end_time += timedelta(days=1)
        log("📅 Trade window spans overnight")

    if datetime.now() < start_time:
        wait = (start_time - datetime.now()).total_seconds()
        log(f"⏳ Waiting {wait/60:.1f} minutes until trade window opens...")
        time.sleep(wait)
    elif datetime.now() > end_time:
        log("❌ Trade window has closed for today")
        ib.disconnect()
        return
    else:
        log("✅ Trade window is open")
    
    num_strikes = 20

    # Get all strikes for this expiry
    all_strikes = sorted([s for s in params.strikes if s > 0])
    
    # Validate strikes by checking actual option contracts exist
    def get_valid_strikes(strikes, symbol, expiry, exchange, currency, multiplier, tradingClass):
        valid_strikes = []
        opt_exchange = strategy_config.get('option_exchange', exchange)
        
        for strike in strikes:
            try:
                # Test if call option exists
                test_option = Option(symbol, expiry, strike, 'C', opt_exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
                contract_details = ib.reqContractDetails(test_option)
                if contract_details:
                    valid_strikes.append(strike)
            except Exception as e:
                log(f"Error validating strike {strike}: {e}")
                continue
        
        return sorted(list(set(valid_strikes)))

    def get_strike_increment(strikes):
        if len(strikes) < 2:
            return None
        
        differences = []
        for i in range(1, len(strikes)):
            diff = round(strikes[i] - strikes[i-1], 2)
            if diff > 0:
                differences.append(diff)
        
        if not differences:
            return None

        # Find the most common difference (mode)
        from collections import Counter
        counts = Counter(differences)
        most_common = counts.most_common(1)
        
        if most_common:
            return most_common[0][0]
        return None
    
    # Get strikes around current price for validation
    strikes_to_test = sorted([s for s in all_strikes if abs(s - current_price) <= current_price * 0.02])  # Within 2%
    valid_all_strikes = get_valid_strikes(strikes_to_test, symbol, expiry, exchange, currency, multiplier, tradingClass)    
    log(f"Found {len(valid_all_strikes)} valid strikes for {symbol}")
    print(valid_all_strikes)
    
    strike_increment = get_strike_increment(valid_all_strikes)
    if strike_increment:
        log(f"Detected strike increment: {strike_increment}")
    else:
        log("⚠️ Could not determine strike increment. Using default rounding.")

    strikes_below = sorted([s for s in valid_all_strikes if s < current_price], reverse=True)[:num_strikes]
    strikes_above = sorted([s for s in valid_all_strikes if s > current_price])[:num_strikes]
    valid_strikes = sorted(strikes_below) + strikes_above

    def find_closest_strike(target_strike, available_strikes):
        if not available_strikes:
            return None
        closest_strike = None
        min_diff = float('inf')
        for strike in available_strikes:
            diff = abs(strike - target_strike)
            if diff < min_diff:
                min_diff = diff
                closest_strike = strike
        return closest_strike

    # Helper to find strike by delta (optimized)
    def find_strike_by_delta(right, target_delta):
        # Create all option contracts for this right type
        opt_exchange = strategy_config.get('option_exchange', exchange)
        options = [Option(symbol, expiry, strike, right, opt_exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass) for strike in valid_strikes]
        
        # Request market data for all options at once
        tickers = [ib.reqMktData(opt) for opt in options]
        
        # Wait for Greeks to populate, with a timeout
        greeks_timeout = 10  # seconds
        start_time = time.time()
        while time.time() - start_time < greeks_timeout:
            all_greeks_available = True
            for ticker in tickers:
                if not ticker.modelGreeks or ticker.modelGreeks.delta is None:
                    all_greeks_available = False
                    break
            if all_greeks_available:
                break
            ib.sleep(0.1) # Check every 100ms
        
        best_strike = None
        best_delta = None
        min_diff = float('inf')
        
        for ticker, strike in zip(tickers, valid_strikes):
            if ticker.modelGreeks and ticker.modelGreeks.delta is not None:
                diff = abs(ticker.modelGreeks.delta - target_delta)
                if diff < min_diff:
                    min_diff = diff
                    best_strike = strike
                    best_delta = ticker.modelGreeks.delta
        
        # Cancel all market data subscriptions
        for opt in options:
            ib.cancelMktData(opt)
        
        if best_strike is not None:
            log(f"Selected {right} strike {best_strike} with closest delta {best_delta:.3f} (target was {target_delta})")
            if min_diff > 0.05:
                log(f"⚠️ Closest delta is {min_diff:.3f} away from target.")
        else:
            log(f"❌ No strike found for {right} with delta near {target_delta}")
        return best_strike

    # Select strikes
    log("🎯 Selecting strikes...")
    short_call_strike = find_strike_by_delta('C', short_call_delta)
    short_put_strike = find_strike_by_delta('P', short_put_delta)
    
    # LONG CALL STRIKE (width-based or closest higher)
    if long_call_delta is not None:
        long_call_strike = find_strike_by_delta('C', long_call_delta)
    else:
        target_long_call_strike = short_call_strike + width
        long_call_strike = find_closest_strike(target_long_call_strike, [s for s in valid_strikes if s > short_call_strike])
        if long_call_strike and long_call_strike != short_call_strike:
            log(f"✅ Long call strike selected: {long_call_strike} (closest to target {target_long_call_strike})")
        else:
            log("❌ Could not find valid long call strike.")
            ib.disconnect()
            return

    # LONG PUT STRIKE (width-based or closest lower)
    if long_put_delta is not None:
        long_put_strike = find_strike_by_delta('P', long_put_delta)
    else:
        target_long_put_strike = short_put_strike - width
        long_put_strike = find_closest_strike(target_long_put_strike, [s for s in valid_strikes if s < short_put_strike])
        if long_put_strike and long_put_strike != short_put_strike:
            log(f"✅ Long put strike selected: {long_put_strike} (closest to target {target_long_put_strike})")
        else:
            log("❌ Could not find valid long put strike.")
            ib.disconnect()
            return

    log(f"🦀 Strategy Structure:")
    log(f"   Short Call: {short_call_strike} | Long Call: {long_call_strike}")
    log(f"   Short Put: {short_put_strike} | Long Put: {long_put_strike}")

    # Build option contracts
    log("🔧 Building option contracts...")
    opt_exchange = strategy_config.get('option_exchange', exchange)
    short_call = Option(symbol, expiry, short_call_strike, 'C', opt_exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
    long_call = Option(symbol, expiry, long_call_strike, 'C', opt_exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
    short_put = Option(symbol, expiry, short_put_strike, 'P', opt_exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
    long_put = Option(symbol, expiry, long_put_strike, 'P', opt_exchange, currency=currency, multiplier=multiplier, tradingClass=tradingClass)
    log("✅ Option contracts created")

    # Build combo contract
    log("🔗 Building combo contract...")
    combo = Contract()
    combo.symbol = symbol
    combo.secType = 'BAG'
    combo.exchange = exchange
    combo.currency = currency

    log("📋 Getting contract IDs for legs...")

    short_call_details = ib.reqContractDetails(short_call)
    if not short_call_details:
        log(f"❌ Could not retrieve contract details for short call: {short_call}")
        ib.disconnect()
        return
    short_call_conId = short_call_details[0].contract.conId

    long_call_details = ib.reqContractDetails(long_call)
    if not long_call_details:
        log(f"❌ Could not retrieve contract details for long call: {long_call}")
        ib.disconnect()
        return
    long_call_conId = long_call_details[0].contract.conId

    short_put_details = ib.reqContractDetails(short_put)
    if not short_put_details:
        log(f"❌ Could not retrieve contract details for short put: {short_put}")
        ib.disconnect()
        return
    short_put_conId = short_put_details[0].contract.conId

    long_put_details = ib.reqContractDetails(long_put)
    if not long_put_details:
        log(f"❌ Could not retrieve contract details for long put: {long_put}")
        ib.disconnect()
        return
    long_put_conId = long_put_details[0].contract.conId

    combo.comboLegs = [
        ComboLeg(conId=short_call_conId, ratio=1, action='SELL', exchange=exchange),
        ComboLeg(conId=long_call_conId, ratio=1, action='BUY', exchange=exchange),
        ComboLeg(conId=short_put_conId, ratio=1, action='SELL', exchange=exchange),
        ComboLeg(conId=long_put_conId, ratio=1, action='BUY', exchange=exchange),
    ]

    # Qualify the combo contract
    log("✅ Qualifying combo contract...")
    ib.qualifyContracts(combo)
    log(f"✅ Combo contract qualified with conId: {combo.conId}")

    # Calculate position size based on max capital
    max_loss_per_contract = width * 100 if width > 0 else 5000  # Default for straddles
    max_contracts = min(10, max_capital // max_loss_per_contract) if max_loss_per_contract > 0 else 1
    log(f"width: {width} max_loss_per_contract: ${max_loss_per_contract} max_capital: {max_capital} max_contracts: {max_contracts}")
    log(f"📊 Position sizing: Max {max_contracts} contracts (Max loss: ${max_loss_per_contract * max_contracts:,})")

    # Entry order logic
    log("\n📈 ENTRY ORDER PHASE")
    log("=" * 30)
    order_filled = False
    
    while datetime.now() < end_time:
        try:
            log("📤 Placing custom order...")
            trade = place_custom_order(ib, combo, max_contracts, log, action='BUY', price_increment=price_increment)
            if trade is None:
                log("❌ Custom order failed")
                break
            log(f"✅ Order submitted with ID: {trade.order.orderId}")
        except Exception as e:
            log(f"❌ Error placing order: {e}")
            break
        
        log("⏳ Waiting for fill...")
        ib.sleep(10)
        
        if trade.orderStatus.status == 'Filled':
            order_filled = True
            fill_price = trade.orderStatus.avgFillPrice
            log(f"✅ FILLED! Entry price: ${fill_price}")
            log(f"💰 Credit received: ${fill_price * max_contracts * 100}")

            log("\n🎯 EXIT ORDERS PHASE")
            log("=" * 30)
            
            def round_to_tick(price, increment=None):
                if increment:
                    return round(price / increment) * increment
                else:
                    return round(price * 20) / 20 if price < 3 else round(price * 10) / 10

            profit_target_price = round_to_tick(fill_price * (1 - profit_target), price_increment)
            stop_loss_price = round_to_tick(fill_price * (1 + stop_loss), price_increment)
            
            log(f"📊 Exit Strategy:")
            log(f"   💰 Entry Fill Price: ${fill_price}")
            log(f"   💚 Profit Target: ${profit_target_price} ({profit_target*100:.0f}% profit)")
            log(f"   🛑 Stop Loss: ${stop_loss_price} ({stop_loss*100:.0f}% loss)")
            
            profit_order = LimitOrder('SELL', max_contracts, profit_target_price)
            stop_order = StopOrder('SELL', max_contracts, stop_loss_price)
            
            log("📤 Placing exit orders...")
            profit_trade = ib.placeOrder(combo, profit_order)
            stop_trade = ib.placeOrder(combo, stop_order)
            log(f"✅ Profit order ID: {profit_trade.order.orderId}")
            log(f"✅ Stop order ID: {stop_trade.order.orderId}")

            log("\n⏳ MONITORING EXIT ORDERS")
            log("=" * 30)
            
            while profit_trade.orderStatus.status not in ['Filled', 'Cancelled'] and stop_trade.orderStatus.status not in ['Filled', 'Cancelled']:
                ib.sleep(5)
                log(f"📊 Status - Profit: {profit_trade.orderStatus.status} | Stop: {stop_trade.orderStatus.status}")
                ib.reqAllOpenOrders()

            log("\n🏁 TRADE COMPLETED")
            log("=" * 30)
            
            if profit_trade.orderStatus.status == 'Filled':
                exit_price = profit_trade.orderStatus.avgFillPrice
                profit = (fill_price - exit_price) * max_contracts * 100
                log(f"🎉 PROFIT TARGET HIT!")
                log(f"💰 Exit price: ${exit_price}")
                log(f"💵 Total profit: ${profit:.2f}")
                ib.cancelOrder(stop_trade.order)
                log("🗑️ Stop loss order cancelled")
                
                journal_data = [
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    symbol, expiry, strategy_name, fill_price, exit_price, f"{profit:.2f}", 'WIN',
                    short_call_strike, long_call_strike, short_put_strike, long_put_strike, current_price
                ]
                write_journal_entry(journal_data, strategy_name)
                log("📊 Trade recorded in journal")
                
            elif stop_trade.orderStatus.status == 'Filled':
                exit_price = stop_trade.orderStatus.avgFillPrice
                loss = (exit_price - fill_price) * max_contracts * 100
                log(f"🛑 STOP LOSS TRIGGERED")
                log(f"💸 Exit price: ${exit_price}")
                log(f"📉 Total loss: ${loss:.2f}")
                ib.cancelOrder(profit_trade.order)
                log("🗑️ Profit target order cancelled")
                
                journal_data = [
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    symbol, expiry, strategy_name, fill_price, exit_price, f"{loss:.2f}", 'LOSS',
                    short_call_strike, long_call_strike, short_put_strike, long_put_strike, current_price
                ]
                write_journal_entry(journal_data, strategy_name)
                log("📊 Trade recorded in journal")
                
            else:
                log(f"⚠️ Unexpected end - Profit: {profit_trade.orderStatus.status}, Stop: {stop_trade.orderStatus.status}")
                
                journal_data = [
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    symbol, expiry, strategy_name, fill_price, 'N/A', '0', 'INCOMPLETE',
                    short_call_strike, long_call_strike, short_put_strike, long_put_strike, current_price
                ]
                write_journal_entry(journal_data, strategy_name)
                log("📊 Incomplete trade recorded in journal")
            break
        else:
            log(f"⏳ Order status: {trade.orderStatus.status}")
            log(f"🔄 Retrying in {retry_interval_min} minutes...")
            ib.sleep(retry_interval_min * 60)

    if not order_filled:
        log("\n⏰ TRADE WINDOW CLOSED")
        log("❌ Entry order was not filled")
        
        journal_data = [
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            symbol, expiry, strategy_name, 'N/A', 'N/A', '0', 'NO_FILL',
            short_call_strike, long_call_strike, short_put_strike, long_put_strike, current_price
        ]
        write_journal_entry(journal_data, strategy_name)
        log("📊 Failed entry recorded in journal")

    log("\n🔌 Disconnecting from TWS...")
    ib.disconnect()
    log("✅ Disconnected. Trading session ended.")

# Main execution
if __name__ == "__main__":
    active_strategies = config.get('active_strategies', [])
    threads = []
    
    for i, strategy_name in enumerate(active_strategies):
        if strategy_name in config['strategies']:
            strategy_config = config['strategies'][strategy_name]
            client_id = 30 + i
            
            thread = threading.Thread(
                target=run_strategy,
                args=(strategy_name, strategy_config, client_id),
                name=f"Strategy-{strategy_name}"
            )
            threads.append(thread)
            thread.start()
            time.sleep(1)
    
    for thread in threads:
        thread.join()
    
    print("✅ All strategies completed")