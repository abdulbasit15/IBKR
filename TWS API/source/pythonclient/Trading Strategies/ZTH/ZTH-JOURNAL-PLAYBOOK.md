# ZTH Trade Journal — Playbook (SOP)

A repeatable, machine-agnostic process for turning a **Tradovate order export**
into rows in **`ZTH Trade Tracker - AB.xlsx`**. Written so any human or AI
assistant can follow it on any machine — the logic lives in the deterministic
script `zth_journal.py`, not in a person's memory.

---

## TL;DR

```bash
# from this folder (Trading Strategies/ZTH/)

# 1. Preview what will be journaled (no changes):
python zth_journal.py "tradovate-orders-all-<timestamp>.csv" --dry-run

# 2. If it looks right, write it in (a timestamped backup is made automatically):
python zth_journal.py "tradovate-orders-all-<timestamp>.csv"
```

Requirements: Python 3.9+ and `openpyxl` (`pip install openpyxl`). Parsing/tests
need only the standard library; `openpyxl` is needed only to write the workbook.

---

## What counts as one "trade"

A ZTH trade is one **bracket order** = **3 Tradovate orders**:

| Leg | Tradovate `Type` | Role |
|-----|------------------|------|
| Entry | `Limit` (filled) | opens the position |
| Take Profit | `Take Profit` | exits at target (one of TP/SL fills, the other cancels) |
| Stop Loss | `Stop Loss` | exits at stop |

So **9 orders in the CSV = 3 trades** in the tracker.

## Conventions the script applies (agreed with the trader)

- **Entry price** = entry's `Avg Fill Price`.
- **Exit price** = the **filled** exit leg's `Avg Fill Price` — the *actual fill,
  with decimals* (e.g. a stop set at 30220.75 that fills at 30220.00 is recorded
  as **30220.00**).
- **Stop Loss (col I)** = the Stop Loss leg's `Stop Price` (the level you set).
- **Take Profit (col J)** = the Take Profit leg's `Limit Price` (the level you set).
- **Direction** = Buy entry → `Long`, Sell entry → `Short`.
- **Position Size** = entry's `Filled Qty`.
- **Asset Traded / Instrument Level** = the symbol root with the futures month+year
  code stripped (`MNQU6` → `MNQ`, `MGCZ6` → `MGC`).

## Column mapping (Trade Tracker sheet)

The script writes **only the input columns**. Everything else is a formula and is
never touched:

| Written (input) | Left alone (formula / manual) |
|-----------------|-------------------------------|
| B Date, C Time, D Asset Traded, E Direction, F Entry Price, G Exit Price, H Position Size, I Stop Loss, J Take Profit, S Instrument Level | A ZTH #, K RR Targeted, L RR Realized, M Win/Loss, N P&L Amount, O P&L %, P Cumulative P&L, Q Trade Setup, R Notes, T/U Screenshots |

- **Column A (ZTH #)** is left untouched — pre-number it yourself or fill later.
- **Trade Setup (Q)** and **Notes (R)** are manual — fill after import.
- RR, P&L, Win/Loss and Cumulative are the workbook's own formulas; they populate
  when you open the file in Excel.

## Safety behavior

- **Backup first, always.** Before any write, a copy
  `ZTH Trade Tracker - AB.backup-YYYYMMDD-HHMMSS.xlsx` is created.
- **Append, never overwrite.** New rows go to the first empty `Entry Price` row.
- **Dedupe.** A trade already present (same asset + date + time + entry + exit) is
  skipped, so re-running the same export is safe.
- **Warnings** are printed if the target row is past the last formula row, or if
  an asset is missing from the `Multipliers` sheet.

## Step-by-step

1. In Tradovate, export the day's orders to CSV (the `tradovate-orders-all-*.csv`
   file). Expected headers: `Symbol, Side, Type, Qty, Remaining Qty, Filled Qty,
   Limit Price, Stop Price, Take Profit, Stop Loss, Avg Fill Price, Status,
   Update Time, Order ID, Expiry, Expiry Time`.
2. Drop it into `Trading Strategies/ZTH/`.
3. Run the `--dry-run` command and eyeball the table + Net P&L.
4. Run without `--dry-run` to write. Note the backup path it prints.
5. Open the workbook in Excel so the formula columns recalc; confirm the P&L
   matches the preview. Fill in `Trade Setup` and `Notes`.

### Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--workbook PATH` | `ZTH Trade Tracker - AB.xlsx` next to the script | target workbook |
| `--sheet NAME` | `Trade Tracker - Eval` | target sheet |
| `--dry-run` | off | preview only, no changes |

## Verify / test the tool

```bash
python test_zth_journal.py     # 5 unit tests over the known 9-order sample
```

## Notes / limitations

- `openpyxl` preserves formulas, images and data validations, but can drop
  Excel-only extras (pivot tables, slicers, form controls). None were detected in
  this workbook, and the automatic backup covers you regardless.
- Manual/market exits and partial fills are handled by "first filled leg = exit";
  unusual multi-fill scenarios should be spot-checked in the preview.
- To add a new instrument, add it to the workbook's `Multipliers` sheet **and** to
  `DEFAULT_MULTIPLIERS` in `zth_journal.py` (keeps the preview P&L accurate).

## Files

| File | Purpose |
|------|---------|
| `zth_journal.py` | The deterministic parser/grouper/writer (source of truth) |
| `test_zth_journal.py` | Unit tests over the known sample |
| `ZTH-JOURNAL-PLAYBOOK.md` | This SOP |
| `.cursor/skills/zth-trade-journal/SKILL.md` | Cursor entry point (points here) |
