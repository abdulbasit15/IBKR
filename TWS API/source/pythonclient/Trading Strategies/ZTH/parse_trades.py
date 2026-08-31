import csv
from datetime import datetime

# Multipliers for P&L calculation
MULTIPLIERS = {'MGC': 10, 'MNQ': 2}
TICK_SIZES = {'MGC': 0.1, 'MNQ': 0.25}

def round_to_tick(price, product):
    """Round price to the product's tick size to fix floating-point errors."""
    if price is None:
        return None
    tick = TICK_SIZES.get(product, 0.1)
    return round(round(price / tick) * tick, 6)

def parse_orders(filepath):
    orders = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Use 'Avg Fill Price' (clean display value) over 'avgPrice' (has FP errors)
            avg_fill = row.get('Avg Fill Price', '').strip()
            avg_price_raw = row.get('avgPrice', '').strip()
            fill_price = float(avg_fill) if avg_fill else (float(avg_price_raw) if avg_price_raw else None)
            
            order = {
                'orderId': row['orderId'].strip(),
                'bs': row['B/S'].strip(),
                'product': row['Product'].strip(),
                'status': row['Status'].strip(),
                'type': row['Type'].strip(),
                'qty': int(row['Quantity']) if row['Quantity'].strip() else 0,
                'avgPrice': fill_price,
                'limitPrice': float(row['decimalLimit']) if row['decimalLimit'].strip() else None,
                'stopPrice': float(row['decimalStop']) if row['decimalStop'].strip() else None,
                'fillTime': row['Fill Time'].strip() if row['Fill Time'].strip() else None,
                'timestamp': row['Timestamp'].strip(),
                'filledQty': int(row['Filled Qty']) if row['Filled Qty'].strip() else 0,
                'text': row['Text'].strip() if row['Text'].strip() else '',
            }
            orders.append(order)
    return orders


def group_into_trades(orders):
    """Group orders into trade brackets.
    Each trade bracket has: entry, TP orders, SL orders, and an exit.
    """
    trades = []
    used = set()  # indices already assigned to a trade
    
    for i in range(len(orders)):
        if i in used:
            continue
            
        entry = orders[i]
        
        # Skip if not filled
        if entry['status'] != 'Filled':
            continue
        
        entry_dir = entry['bs']  # 'Buy' or 'Sell'
        opposite_dir = 'Sell' if entry_dir == 'Buy' else 'Buy'
        product = entry['product']
        
        # Check if this is an entry by looking at nearby orders for opposite direction
        # (must be same product + opposite direction within next 5 rows)
        has_opposite = False
        for k in range(i+1, min(i+6, len(orders))):
            if k not in used and orders[k]['bs'] == opposite_dir and orders[k]['product'] == product:
                has_opposite = True
                break
        
        if not has_opposite:
            continue
        
        # Collect ALL bracket members: scan forward for same product + opposite direction
        bracket_members = []
        exit_found = False
        canceled_after_exit = 0
        
        for j in range(i+1, min(i+20, len(orders))):
            if j in used:
                continue
            o = orders[j]
            
            # Skip orders of different products
            if o['product'] != product:
                continue
            
            # Stop if we hit same direction as entry (next trade's entry for same product)
            if o['bs'] == entry_dir:
                break
            
            # This is same product + opposite direction
            bracket_members.append((j, o))
            
            if o['status'] == 'Filled' and not exit_found:
                exit_found = True
            elif exit_found:
                if o['status'] == 'Filled':
                    # Another filled order = next trade's bracket, remove and stop
                    bracket_members.pop()
                    break
                else:
                    canceled_after_exit += 1
                    if canceled_after_exit >= 3:
                        break
        
        # From bracket members, identify exit, TP orders, SL orders
        trade = {
            'entry_order': entry,
            'tp_orders': [],
            'sl_orders': [],
            'exit_order': None,
            'product': product,
            'entry_dir': entry_dir,
        }
        
        for idx, o in bracket_members:
            if o['type'] == 'Limit':
                trade['tp_orders'].append(o)
                if o['status'] == 'Filled' and trade['exit_order'] is None:
                    trade['exit_order'] = o
            elif o['type'] == 'Stop':
                trade['sl_orders'].append(o)
                if o['status'] == 'Filled' and trade['exit_order'] is None:
                    trade['exit_order'] = o
            elif o['type'] == 'Market':
                if o['status'] == 'Filled' and trade['exit_order'] is None:
                    trade['exit_order'] = o
        
        if trade['exit_order'] is not None:
            trades.append(trade)
            used.add(i)
            for idx, o in bracket_members:
                used.add(idx)
    
    return trades


def calculate_trade_metrics(trade):
    """Calculate all metrics for a single trade."""
    entry = trade['entry_order']
    exit_order = trade['exit_order']
    product = trade['product']
    entry_dir = trade['entry_dir']
    
    # Basic fields - round to tick size to fix any remaining FP errors
    entry_price = round_to_tick(entry['avgPrice'], product)
    exit_price = round_to_tick(exit_order['avgPrice'], product)
    position_size = entry['qty']
    multiplier = MULTIPLIERS.get(product, 1)
    
    # Determine direction
    direction = 'Long' if entry_dir == 'Buy' else 'Short'
    
    # Determine SL and TP
    if exit_order['type'] == 'Stop':
        # Exit via stop loss
        sl_price = exit_price  # actual fill
        # TP = last limit order price (canceled)
        tp_price = None
        for tp_order in reversed(trade['tp_orders']):
            if tp_order['limitPrice'] is not None:
                tp_price = tp_order['limitPrice']
                break
            elif tp_order['avgPrice'] is not None:
                tp_price = tp_order['avgPrice']
                break
    elif exit_order['type'] == 'Limit':
        # Exit via take profit
        tp_price = exit_price  # actual fill
        # SL = last stop order price (canceled)
        sl_price = None
        for sl_order in reversed(trade['sl_orders']):
            if sl_order['stopPrice'] is not None:
                sl_price = sl_order['stopPrice']
                break
    elif exit_order['type'] == 'Market':
        # Manual exit
        tp_price = None
        sl_price = None
        for tp_order in reversed(trade['tp_orders']):
            if tp_order['limitPrice'] is not None:
                tp_price = tp_order['limitPrice']
                break
        for sl_order in reversed(trade['sl_orders']):
            if sl_order['stopPrice'] is not None:
                sl_price = sl_order['stopPrice']
                break
    
    # Calculate P&L
    if direction == 'Long':
        pnl = (exit_price - entry_price) * position_size * multiplier
    else:
        pnl = (entry_price - exit_price) * position_size * multiplier
    
    # Win/Loss
    win_loss = 'Win' if pnl > 0 else 'Loss'
    
    # RR Targeted and Realized
    rr_targeted = None
    rr_realized = None
    
    if sl_price is not None and tp_price is not None:
        if direction == 'Long':
            risk = abs(entry_price - sl_price)
            reward_targeted = tp_price - entry_price
            reward_realized = exit_price - entry_price
        else:
            risk = abs(sl_price - entry_price)
            reward_targeted = entry_price - tp_price
            reward_realized = entry_price - exit_price
        
        if risk != 0:
            rr_targeted = round(reward_targeted / risk, 2)
            rr_realized = round(reward_realized / risk, 2)
    
    # Date and Time from entry fill time (or timestamp as fallback)
    time_source = entry['fillTime'] if entry['fillTime'] else entry['timestamp']
    try:
        dt = datetime.strptime(time_source, '%m/%d/%Y %H:%M:%S')
        date_str = dt.strftime('%m/%d/%Y')
        time_str = f"{dt.hour}:{dt.minute:02d}"
    except:
        date_str = time_source.split(' ')[0] if ' ' in time_source else time_source
        time_str = time_source.split(' ')[1] if ' ' in time_source else ''
    
    return {
        'date': date_str,
        'time': time_str,
        'asset': product,
        'direction': direction,
        'entry_price': round(entry_price, 2) if entry_price else '',
        'exit_price': round(exit_price, 2) if exit_price else '',
        'position_size': position_size,
        'stop_loss': round(sl_price, 2) if sl_price else '',
        'take_profit': round(tp_price, 2) if tp_price else '',
        'rr_targeted': rr_targeted if rr_targeted else '',
        'rr_realized': rr_realized if rr_realized else '',
        'win_loss': win_loss,
        'pnl': round(pnl, 2),
    }


def main():
    orders = parse_orders('Orders (1).csv')
    trades = group_into_trades(orders)
    
    # Calculate metrics for each trade
    results = []
    for trade in trades:
        metrics = calculate_trade_metrics(trade)
        results.append(metrics)
    
    # Write output CSV
    output_file = 'ZTH_Trade_Journal_v2.csv'
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # Header
        writer.writerow([
            'ZTH', 'Date', 'Time', 'Asset Traded', 'Direction',
            'Entry Price', 'Exit Price', 'Position Size',
            'Stop Loss', 'Take Profit', 'RR Targeted', 'RR Realized',
            'Win/Loss', 'P&L Amount'
        ])
        # Data rows
        for i, r in enumerate(results, 1):
            writer.writerow([
                i, r['date'], r['time'], r['asset'], r['direction'],
                r['entry_price'], r['exit_price'], r['position_size'],
                r['stop_loss'], r['take_profit'], r['rr_targeted'], r['rr_realized'],
                r['win_loss'], r['pnl']
            ])
    
    print(f"Generated {len(results)} trades in {output_file}")
    for i, r in enumerate(results, 1):
        print(f"  {i}: {r['date']} {r['time']} {r['asset']} {r['direction']} "
              f"Entry={r['entry_price']} Exit={r['exit_price']} Size={r['position_size']} "
              f"SL={r['stop_loss']} TP={r['take_profit']} RR_T={r['rr_targeted']} RR_R={r['rr_realized']} "
              f"{r['win_loss']} P&L={r['pnl']}")


if __name__ == '__main__':
    main()
