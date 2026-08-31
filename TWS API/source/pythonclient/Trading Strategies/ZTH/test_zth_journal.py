"""Unit tests for zth_journal (stdlib unittest, no third-party deps).

Run:  python test_zth_journal.py
"""
import unittest

import zth_journal as zj

# The known Tradovate export (9 orders = 3 bracket trades) used to design the tool.
SAMPLE_CSV = """Symbol,Side,Type,Qty,Remaining Qty,Filled Qty,Limit Price,Stop Price,Take Profit,Stop Loss,Avg Fill Price,Status,Update Time,Order ID,Expiry,Expiry Time
MNQU6,Buy,Limit,3,0,3,30240.75,,,,30240.75,Filled,8/17/2026 9:55,6.18403E+11,Day,
MNQU6,Sell,Take Profit,3,,,30280.75,,,,,Cancelled,8/17/2026 9:58,6.18403E+11,Day,
MNQU6,Sell,Stop Loss,3,0,3,,30220.75,,,30220,Filled,8/17/2026 9:58,6.18403E+11,Day,
MGCZ6,Buy,Limit,2,0,2,4461.4,,,,4461.4,Filled,8/17/2026 10:09,6.18403E+11,Day,
MGCZ6,Sell,Take Profit,2,0,2,4473.4,,,,4473.4,Filled,8/17/2026 10:16,6.18403E+11,Day,
MGCZ6,Sell,Stop Loss,2,,,,4455.4,,,,Cancelled,8/17/2026 10:16,6.18403E+11,Day,
MNQU6,Sell,Limit,3,0,3,30237.75,,,,30237.75,Filled,8/17/2026 11:51,6.18403E+11,Day,
MNQU6,Buy,Stop Loss,3,,,,30257.75,,,,Cancelled,8/17/2026 12:03,6.18403E+11,Day,
MNQU6,Buy,Take Profit,3,0,3,30221.5,,,,30221.5,Filled,8/17/2026 12:03,6.18403E+11,Day,
"""


class RootSymbolTests(unittest.TestCase):
    def test_strips_month_year_code(self):
        self.assertEqual(zj.root_symbol("MNQU6"), "MNQ")
        self.assertEqual(zj.root_symbol("MGCZ6"), "MGC")
        self.assertEqual(zj.root_symbol("ESH7"), "ES")

    def test_passthrough_when_no_code(self):
        self.assertEqual(zj.root_symbol("MNQ"), "MNQ")


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.orders = zj.parse_csv_text(SAMPLE_CSV)
        self.trades = zj.group_into_trades(self.orders)

    def test_three_trades(self):
        self.assertEqual(len(self.trades), 3)

    def test_rows(self):
        rows = [zj.compute_journal_row(t) for t in self.trades]
        rows.sort(key=lambda r: r["update_dt"])

        t1, t2, t3 = rows

        # Trade 1: MNQ Long, stopped out at actual fill 30220.00 -> loss
        self.assertEqual(t1["asset"], "MNQ")
        self.assertEqual(t1["direction"], "Long")
        self.assertAlmostEqual(t1["entry"], 30240.75)
        self.assertAlmostEqual(t1["exit"], 30220.00)   # actual fill, with decimals
        self.assertEqual(t1["size"], 3)
        self.assertAlmostEqual(t1["stop_loss"], 30220.75)
        self.assertAlmostEqual(t1["take_profit"], 30280.75)
        self.assertAlmostEqual(t1["pnl"], -124.50)
        self.assertEqual(t1["win_loss"], "Loss")

        # Trade 2: MGC Long, take profit -> win
        self.assertEqual(t2["asset"], "MGC")
        self.assertEqual(t2["direction"], "Long")
        self.assertAlmostEqual(t2["entry"], 4461.40)
        self.assertAlmostEqual(t2["exit"], 4473.40)
        self.assertEqual(t2["size"], 2)
        self.assertAlmostEqual(t2["stop_loss"], 4455.40)
        self.assertAlmostEqual(t2["take_profit"], 4473.40)
        self.assertAlmostEqual(t2["pnl"], 240.00)
        self.assertEqual(t2["win_loss"], "Win")

        # Trade 3: MNQ Short, take profit (SL leg came before TP leg) -> win
        self.assertEqual(t3["asset"], "MNQ")
        self.assertEqual(t3["direction"], "Short")
        self.assertAlmostEqual(t3["entry"], 30237.75)
        self.assertAlmostEqual(t3["exit"], 30221.50)
        self.assertEqual(t3["size"], 3)
        self.assertAlmostEqual(t3["stop_loss"], 30257.75)
        self.assertAlmostEqual(t3["take_profit"], 30221.50)
        self.assertAlmostEqual(t3["pnl"], 97.50)
        self.assertEqual(t3["win_loss"], "Win")

    def test_net_pnl(self):
        rows = [zj.compute_journal_row(t) for t in self.trades]
        self.assertAlmostEqual(round(sum(r["pnl"] for r in rows), 2), 213.00)


if __name__ == "__main__":
    unittest.main(verbosity=2)
