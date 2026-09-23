// ============================================================================
// TradeCopier.cs
// ----------------------------------------------------------------------------
// NinjaTrader 8 Strategy that mirrors trades placed on a single "master"
// account (e.g. APEX3192580000068) onto every other connected account.
//
// The TP / SL bracket is defined by an ATM STRATEGY you attach to each master
// entry. This copier does NOT create the master bracket; it reads whatever
// TP/SL the ATM places on the master, measures the tick distance from that
// entry, and reproduces an equivalent OCO bracket on every slave account
// (using each slave's own fill price).
//
// SCALING IN IS SUPPORTED. Each master ENTRY (with its own ATM bracket) is
// tracked as its own "sub-group": if you go Short 2 (ATM #1) and then add
// Short 3 (ATM #2), the slaves become Short 5 carrying TWO independent OCO
// brackets that each mirror the matching master ATM. Modifying either master
// bracket syncs only that sub-group's slave orders.
//
// HOW IT WORKS
//  - Enable this strategy on ONE chart. Set its "Account" to your MASTER.
//  - Place master entries WITH AN ATM attached so the ATM creates the bracket.
//  - On each master entry fill (open OR add), the strategy:
//      1. Sends a market order of the same size/direction to every non-excluded
//         connected account, tagged with a unique group id.
//      2. Reads that entry's ATM Target (limit) + Stop (stop) and records the
//         tick distance from that entry.
//  - When each copy fills on a slave, an OCO bracket is attached for that
//    sub-group at the same tick distances off the slave's own fill price.
//  - Dragging/editing a master ATM TP or SL syncs the matching sub-group's
//    slave orders (safe cancel -> confirm -> resubmit; never stacks stops).
//  - When the master position for an instrument goes FULLY flat, behavior
//    depends on "Flatten Slaves When Master Flat" (see below).
//
// INSTALLATION
//  1. Tools -> Edit NinjaScript -> Strategy -> New... (or copy this file into
//     Documents\NinjaTrader 8\bin\Custom\Strategies)
//  2. Paste, press F5 (Compile).
//  3. Open a chart of a LIQUID instrument (so the safety watchdog heartbeat
//     ticks), right-click -> Strategies... -> "TradeCopier".
//  4. Dialog:
//       - Account            = APEX3192580000068   (your master)
//       - Excluded Accounts  = Sim101   (comma-separated names to skip)
//       - Enable Copying     = true
//       - Flatten Slaves When Master Flat = true (close all slaves when the
//         master position fully closes; false = let each slave bracket run)
//  5. Enable it, and place entries with an ATM attached.
//
// SCOPE / LIMITATIONS (read before relying on this live)
//  - Each master entry must carry an ATM (or a manually placed exit limit +
//    exit stop). The copier mirrors whatever exit orders it finds; it does not
//    invent a bracket. It assumes each ATM has ONE target + ONE stop for its
//    entry quantity (no scaling targets / auto-breakeven steps inside one ATM).
//  - Quantity copied = master fill quantity (1:1) per entry.
//  - When the MASTER is FULLY flat on an instrument (all its sub-positions
//    closed), behavior depends on "Flatten Slaves When Master Flat":
//      * ON  (default): every slave is flattened SAFELY (cancel bracket first,
//        then market-close only the position that actually remains -- never a
//        naked position and never an over-sell into an opposite position). A
//        ~15s watchdog re-confirms flat.
//      * OFF: each slave keeps its own OCO brackets and self-manages exits; the
//        watchdog re-attaches protection if a bracket goes missing.
//  - Intra-trade partial exits (one ATM TP/SL hitting while others remain) are
//    handled by each sub-group's own mirrored OCO on the slave.
//  - A one-order REVERSAL (a single fill that flips long<->short) is treated as
//    a full close of the existing sub-groups; the new opposite side is NOT
//    auto-opened. Go flat, then enter the other direction.
//  - RUN ONLY ONE ENABLED INSTANCE. This copies to EVERY non-excluded account,
//    so a second instance duplicates every entry/bracket. A guard makes extra
//    instances refuse to copy and log "DISABLED (duplicate)".
//  - This submits/modifies REAL orders on every non-excluded connected account.
//    Test thoroughly in Sim first -- especially scale-in and exits.
//  - Confirm copy/correlated trading is permitted under your Apex agreement.
//  - If an account connects AFTER this strategy is enabled, disable/re-enable
//    to pick it up.
// ============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class TradeCopier : Strategy
    {
        // Order-name prefixes for our OWN generated slave orders. Copy/bracket
        // orders embed the sub-group id: "<prefix><gid>-<slaveName>". The flatten
        // order is aggregate (whole position) so it carries no gid.
        private const string EntryPrefix  = "GrpCopyEntry-";
        private const string TargetPrefix = "GrpCopyTP-";
        private const string StopPrefix   = "GrpCopySL-";
        private const string FlatPrefix   = "GrpFlat-";

        // Process-wide singleton guard. This strategy copies to EVERY non-excluded
        // account, so more than one enabled instance duplicates every entry and
        // bracket on the slaves. Only the first enabled instance copies.
        private static readonly object activeInstanceLock = new object();
        private static TradeCopier activeInstance;
        private bool isActiveCopier;

        private readonly HashSet<string> processedExecutionIds = new HashSet<string>();
        private readonly object syncLock  = new object();
        private readonly object groupLock = new object();

        private readonly List<Account> subscribedAccounts = new List<Account>();

        // All open sub-groups, keyed by unique group id. Multiple sub-groups may
        // exist for the same instrument (one per master entry / ATM bracket).
        private readonly Dictionary<string, TradeGroup> tradeGroups = new Dictionary<string, TradeGroup>();
        private int nextGroupSeq;

        // Slave positions still being guarded after their master sub-position
        // closed (until confirmed flat / protected).
        private readonly List<OrphanWatch> orphanWatch = new List<OrphanWatch>();

        private DateTime lastWatchdogUtc = DateTime.MinValue;

        private class SlaveBracket
        {
            public double EntryPrice;
            public int Quantity;
            public bool Filled;
            public bool BracketSubmitted;
            public Order TargetOrder;
            public Order StopOrder;

            // Last submitted bracket prices (used by the watchdog to re-attach).
            public double LastTargetPrice;
            public double LastStopPrice;
            public int LastTpTicks;
            public int LastSlTicks;

            // Deferred-rebuild state (cancel -> confirm -> resubmit).
            public bool RebuildPending;
            public double PendingTargetPrice;
            public double PendingStopPrice;
            public int PendingTpTicks;
            public int PendingSlTicks;
        }

        // One master entry + its own ATM bracket + its slave copies.
        private class TradeGroup
        {
            public string GroupId;
            public Instrument Instrument;
            public MarketPosition Direction;
            public double MasterEntryPrice;
            public int Quantity;

            public Order MasterTargetOrder;
            public Order MasterStopOrder;
            public double MasterTargetPrice;   // 0 = not yet known
            public double MasterStopPrice;     // 0 = not yet known

            public readonly Dictionary<Account, SlaveBracket> Slaves = new Dictionary<Account, SlaveBracket>();
        }

        // A slave position we keep guarding after its master sub-position closed.
        private class OrphanWatch
        {
            public Account Slave;
            public Instrument Instrument;
            public MarketPosition Direction;
            public double EntryPrice;
            public int Quantity;
            public double TargetPrice;
            public double StopPrice;
            public int TpTicks;
            public int SlTicks;
            public bool Flatten;
        }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                     = "Mirrors master-account entries and each entry's ATM TP/SL bracket onto every other connected account. Supports scaling in.";
                Name                            = "TradeCopier";
                Calculate                       = Calculate.OnBarClose;
                EntriesPerDirection             = 1;
                EntryHandling                   = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy    = false;
                ExitOnSessionCloseSeconds       = 30;
                IsFillLimitOnTouch              = false;
                MaximumBarsLookBack             = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution             = OrderFillResolution.Standard;
                Slippage                        = 0;
                StartBehavior                   = StartBehavior.WaitUntilFlat;
                TimeInForce                     = TimeInForce.Gtc;
                TraceOrders                     = false;
                RealtimeErrorHandling           = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling              = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade             = 0;
                IsUnmanaged                     = true;
                IsInstantiatedOnEachOptimizationIteration = true;

                ExcludedAccountNames        = "Sim101";
                EnableCopying               = true;
                FlattenSlavesWhenMasterFlat = true;
            }
            else if (State == State.Configure)
            {
                // 1-minute heartbeat series drives the protection watchdog.
                AddDataSeries(BarsPeriodType.Minute, 1);
            }
            else if (State == State.DataLoaded)
            {
                if (Account == null)
                {
                    Print("[TradeCopier] ERROR: No Account assigned. Set 'Account' to your master account (e.g. APEX3192580000068).");
                    return;
                }

                lock (activeInstanceLock)
                {
                    if (activeInstance != null && activeInstance != this)
                    {
                        isActiveCopier = false;
                        string otherMaster = activeInstance.Account != null ? activeInstance.Account.Name : "unknown";
                        Print($"[TradeCopier] DISABLED (duplicate): another instance is already active (master {otherMaster}). Only ONE instance may run. This instance (master {Account.Name}) will NOT copy. Disable the extras, then disable & re-enable the one to keep.");
                        return;
                    }

                    activeInstance = this;
                    isActiveCopier = true;
                }

                SubscribeAllAccounts();
                Print($"[TradeCopier] Active. Master account = {Account.Name}. Watching {subscribedAccounts.Count} account(s). Each master entry's ATM bracket is mirrored to slaves (scale-in supported).");
            }
            else if (State == State.Terminated)
            {
                lock (activeInstanceLock)
                {
                    if (activeInstance == this)
                        activeInstance = null;
                }
                isActiveCopier = false;
                UnsubscribeAllAccounts();
            }
        }

        // ------------------------------------------------------------------
        // HEARTBEAT / PROTECTION WATCHDOG
        // ------------------------------------------------------------------

        protected override void OnBarUpdate()
        {
            if (State != State.Realtime || !EnableCopying || !isActiveCopier)
                return;

            DateTime now = DateTime.UtcNow;
            if ((now - lastWatchdogUtc).TotalSeconds < 15)
                return;
            lastWatchdogUtc = now;

            RunProtectionWatchdog();
        }

        // Ensures no tracked slave is ever left holding more open contracts than
        // it has working protective stops for (catches orphans from a failed
        // rebuild, a connection drop, or a partial gap), and drives pending
        // flatten/protect watch entries.
        private void RunProtectionWatchdog()
        {
            lock (groupLock)
            {
                // Aggregate protection check per (instrument, slave) across sub-groups.
                foreach (string instrFull in tradeGroups.Values.Select(g => g.Instrument.FullName).Distinct().ToList())
                {
                    List<TradeGroup> groups = tradeGroups.Values.Where(g => g.Instrument.FullName == instrFull).ToList();
                    if (groups.Count == 0)
                        continue;

                    Instrument instr = groups[0].Instrument;
                    foreach (Account slave in groups.SelectMany(g => g.Slaves.Keys).Distinct().ToList())
                        EnsureAggregateProtected(instr, slave, groups);
                }

                // Post-close watch entries.
                for (int i = orphanWatch.Count - 1; i >= 0; i--)
                {
                    OrphanWatch ow = orphanWatch[i];
                    bool done = ow.Flatten
                        ? EnsureSlaveFlat(ow.Slave, ow.Instrument)
                        : EnsureSlaveProtected(ow.Slave, ow.Instrument, ow.Direction, ow.TargetPrice, ow.StopPrice, ow.TpTicks, ow.SlTicks, null);
                    if (done)
                        orphanWatch.RemoveAt(i);
                }
            }
        }

        // If a slave holds more contracts than it has working stops for, re-attach
        // the missing sub-group brackets (up to the uncovered quantity only, so we
        // never over-protect and cause an opposite position on a fill).
        private void EnsureAggregateProtected(Instrument instr, Account slave, List<TradeGroup> groups)
        {
            MarketPosition mp;
            int posQty;
            GetSlavePosition(slave, instr, out mp, out posQty);
            if (mp == MarketPosition.Flat || posQty <= 0)
                return;

            int protectedQty = SumWorkingQty(slave, instr, StopPrefix);
            int gap = posQty - protectedQty;
            if (gap <= 0)
                return;

            foreach (TradeGroup g in groups)
            {
                if (gap <= 0)
                    break;

                SlaveBracket sb;
                if (!g.Slaves.TryGetValue(slave, out sb) || !sb.Filled || sb.RebuildPending)
                    continue;
                if (mp != g.Direction)
                    continue;
                if (HasWorkingGidOrder(slave, instr, g.GroupId, StopPrefix))
                    continue; // this sub-group is already protected

                if (HasWorkingGidOrder(slave, instr, g.GroupId, TargetPrefix))
                {
                    Print($"[TradeCopier] WATCHDOG: {slave.Name} sub-group {g.GroupId} has a target but no stop on {instr.FullName}; leaving for MANUAL review.");
                    continue;
                }
                if (sb.LastStopPrice <= 0 || sb.LastTargetPrice <= 0)
                    continue;

                int qty = Math.Min(sb.Quantity, gap);
                if (qty <= 0)
                    continue;

                SubmitSlaveOco(g, slave, sb, qty, sb.LastTargetPrice, sb.LastStopPrice, sb.LastTpTicks, sb.LastSlTicks, "watchdog re-attach");
                gap -= qty;
            }
        }

        // ------------------------------------------------------------------
        // ACCOUNT SUBSCRIPTIONS
        // ------------------------------------------------------------------

        private void SubscribeAllAccounts()
        {
            UnsubscribeAllAccounts();
            foreach (Account acct in Account.All)
            {
                acct.ExecutionUpdate += OnAnyAccountExecutionUpdate;
                acct.OrderUpdate     += OnAnyAccountOrderUpdate;
                subscribedAccounts.Add(acct);
            }
        }

        private void UnsubscribeAllAccounts()
        {
            foreach (Account acct in subscribedAccounts)
            {
                try
                {
                    acct.ExecutionUpdate -= OnAnyAccountExecutionUpdate;
                    acct.OrderUpdate     -= OnAnyAccountOrderUpdate;
                }
                catch { }
            }
            subscribedAccounts.Clear();
        }

        private HashSet<string> GetExcludedNames()
        {
            HashSet<string> result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            string[] parts = (ExcludedAccountNames ?? string.Empty).Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (string part in parts)
            {
                string trimmed = part.Trim();
                if (trimmed.Length > 0)
                    result.Add(trimmed);
            }
            return result;
        }

        private List<Account> GetSlaveAccounts()
        {
            HashSet<string> excluded = GetExcludedNames();
            return Account.All
                .Where(a => a != Account)
                .Where(a => !excluded.Contains(a.Name))
                .Where(a => a.ConnectionStatus == ConnectionStatus.Connected)
                .ToList();
        }

        private static bool IsBuySide(OrderAction a)  { return a == OrderAction.Buy  || a == OrderAction.BuyToCover; }
        private static bool IsSellSide(OrderAction a) { return a == OrderAction.Sell || a == OrderAction.SellShort;  }

        // ------------------------------------------------------------------
        // ORDER-NAME HELPERS (embed / parse the sub-group id)
        // ------------------------------------------------------------------

        private static string MakeName(string prefix, string gid, string slaveName)
        {
            return prefix + gid + "-" + slaveName;
        }

        private static bool IsOurName(string name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            return name.StartsWith(EntryPrefix,  StringComparison.OrdinalIgnoreCase)
                || name.StartsWith(TargetPrefix, StringComparison.OrdinalIgnoreCase)
                || name.StartsWith(StopPrefix,   StringComparison.OrdinalIgnoreCase)
                || name.StartsWith(FlatPrefix,   StringComparison.OrdinalIgnoreCase);
        }

        // Returns the gid embedded in one of our gid-tagged order names, else null.
        private static string ParseGid(string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
            string[] prefixes = { EntryPrefix, TargetPrefix, StopPrefix };
            foreach (string p in prefixes)
            {
                if (name.StartsWith(p, StringComparison.OrdinalIgnoreCase))
                {
                    string rest = name.Substring(p.Length);
                    int dash = rest.IndexOf('-');
                    if (dash > 0)
                        return rest.Substring(0, dash);
                }
            }
            return null;
        }

        // ------------------------------------------------------------------
        // EXECUTION HANDLING
        // ------------------------------------------------------------------

        private void OnAnyAccountExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            if (!EnableCopying || !isActiveCopier)
                return;

            Account account     = sender as Account;
            Execution execution = e?.Execution;
            if (account == null || execution?.Order == null)
                return;
            if (execution.Order.OrderState != OrderState.Filled)
                return;

            string executionKey = execution.ExecutionId ?? (execution.Order.Id + "-" + execution.Time.Ticks);
            lock (syncLock)
            {
                if (processedExecutionIds.Contains(executionKey))
                    return;
                processedExecutionIds.Add(executionKey);
            }

            string orderName = execution.Order.Name ?? string.Empty;

            try
            {
                if (account == Account)
                    HandleMasterFill(execution);
                else if (orderName.StartsWith(EntryPrefix, StringComparison.OrdinalIgnoreCase))
                    HandleSlaveEntryFilled(account, execution);
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier] ERROR handling execution on {account.Name}: {ex.Message}");
            }
        }

        private void HandleMasterFill(Execution execution)
        {
            Instrument instrument = execution.Instrument;
            Order order           = execution.Order;
            if (instrument == null || order == null)
                return;

            lock (groupLock)
            {
                // 1. Is this fill one of a sub-group's own ATM exit legs? -> that
                //    sub-position is closing.
                bool exitIsTarget;
                TradeGroup exitG = FindGroupByLeg(order, out exitIsTarget);
                if (exitG != null)
                {
                    HandleSubGroupClosed(exitG);
                    return;
                }

                // 2. Determine the instrument's current direction from open sub-groups.
                List<TradeGroup> groups = tradeGroups.Values.Where(g => g.Instrument.FullName == instrument.FullName).ToList();
                MarketPosition dir = groups.Count > 0 ? groups[0].Direction : MarketPosition.Flat;
                bool buySide  = IsBuySide(order.OrderAction);

                if (dir == MarketPosition.Flat)
                {
                    HandleMasterEntryFilled(execution, buySide ? MarketPosition.Long : MarketPosition.Short);
                    return;
                }

                bool sameSide = (dir == MarketPosition.Long && buySide) || (dir == MarketPosition.Short && !buySide);
                if (sameSide)
                {
                    HandleMasterEntryFilled(execution, dir); // scale-in -> new sub-group
                }
                else
                {
                    // Opposite side but not matched to a tracked ATM leg by
                    // reference. Try to attribute the cover to a single sub-group by
                    // quantity; otherwise treat it as a full manual flatten and close
                    // every sub-group for this instrument.
                    TradeGroup byQty = groups.FirstOrDefault(g => g.Quantity == order.Filled);
                    if (byQty != null)
                    {
                        Print($"[TradeCopier] Master cover {order.Filled} on {instrument.FullName} matched sub-group {byQty.GroupId} by quantity.");
                        HandleSubGroupClosed(byQty);
                    }
                    else
                    {
                        Print($"[TradeCopier] Master manual exit on {instrument.FullName}. Closing all {groups.Count} sub-group(s).");
                        foreach (TradeGroup g in groups)
                            HandleSubGroupClosed(g);
                    }
                }
            }
        }

        // Creates a new sub-group for a master entry (open or add) and copies it.
        // Must hold groupLock.
        private void HandleMasterEntryFilled(Execution execution, MarketPosition direction)
        {
            Instrument instrument = execution.Instrument;
            int qty               = execution.Order.Filled;
            double entryPrice     = execution.Order.AverageFillPrice > 0 ? execution.Order.AverageFillPrice : execution.Price;
            if (instrument == null || qty <= 0)
                return;

            string gid = (++nextGroupSeq).ToString();
            var group = new TradeGroup
            {
                GroupId          = gid,
                Instrument       = instrument,
                Direction        = direction,
                MasterEntryPrice = entryPrice,
                Quantity         = qty
            };
            tradeGroups[gid] = group;

            Print($"[TradeCopier] Master fill (grp {gid}): {direction} {qty} {instrument.FullName} @ {entryPrice}. Mirroring this entry's ATM bracket.");

            DiscoverMasterBracket(group);

            OrderAction entryAction = direction == MarketPosition.Long ? OrderAction.Buy : OrderAction.SellShort;
            List<Account> slaves = GetSlaveAccounts();
            Print($"[TradeCopier] Copying grp {gid} to {slaves.Count} account(s).");

            foreach (Account slave in slaves)
            {
                try
                {
                    Order entryOrder = slave.CreateOrder(
                        instrument, entryAction, OrderType.Market, OrderEntry.Manual,
                        TimeInForce.Day, qty, 0, 0, string.Empty,
                        MakeName(EntryPrefix, gid, slave.Name), DateTime.MaxValue, null);
                    slave.Submit(new[] { entryOrder });
                    Print($"[TradeCopier]   -> Sent {direction} {qty} {instrument.FullName} to {slave.Name} (grp {gid})");
                }
                catch (Exception ex)
                {
                    Print($"[TradeCopier]   -> ERROR sending grp {gid} to {slave.Name}: {ex.Message}");
                }
            }
        }

        // A sub-group's master position has closed (its ATM exit filled, or a
        // manual exit). Remove it; if it was the LAST sub-group for the instrument
        // (master now fully flat), flatten/watch the slaves' aggregate position.
        // Must hold groupLock.
        private void HandleSubGroupClosed(TradeGroup group)
        {
            if (!tradeGroups.ContainsKey(group.GroupId))
                return;

            Instrument instrument = group.Instrument;
            tradeGroups.Remove(group.GroupId);

            bool masterFlat = !tradeGroups.Values.Any(g => g.Instrument.FullName == instrument.FullName);
            Print($"[TradeCopier] Master sub-group {group.GroupId} closed on {instrument.FullName}." + (masterFlat ? " Master now flat." : " Other sub-groups remain."));

            if (!masterFlat)
                return; // remaining sub-groups' slave OCOs self-manage their exits

            foreach (var kvp in group.Slaves)
            {
                Account slave   = kvp.Key;
                SlaveBracket sb = kvp.Value;
                if (!sb.Filled)
                    continue;
                sb.RebuildPending = false;

                Account s = slave;
                Instrument ins = instrument;
                MarketPosition dir = group.Direction;

                if (FlattenSlavesWhenMasterFlat)
                {
                    // Register the watch BEFORE cancelling (a synchronous cancel
                    // callback must be able to find it, or the bracket is cancelled
                    // with no follow-up close -> naked position).
                    orphanWatch.RemoveAll(o => o.Flatten && o.Slave == s && o.Instrument != null && o.Instrument.FullName == ins.FullName);
                    orphanWatch.Add(new OrphanWatch { Slave = slave, Instrument = instrument, Direction = dir, Quantity = sb.Quantity, Flatten = true });

                    if (EnsureSlaveFlat(slave, instrument))
                        orphanWatch.RemoveAll(o => o.Flatten && o.Slave == s && o.Instrument != null && o.Instrument.FullName == ins.FullName);
                }
                else
                {
                    orphanWatch.Add(new OrphanWatch
                    {
                        Slave       = slave,
                        Instrument  = instrument,
                        Direction   = dir,
                        EntryPrice  = sb.EntryPrice,
                        Quantity    = sb.Quantity,
                        TargetPrice = sb.LastTargetPrice,
                        StopPrice   = sb.LastStopPrice,
                        TpTicks     = sb.LastTpTicks,
                        SlTicks     = sb.LastSlTicks,
                        Flatten     = false
                    });
                }
            }
        }

        private void HandleSlaveEntryFilled(Account slave, Execution execution)
        {
            Instrument instrument = execution.Instrument;
            int qty               = execution.Order.Filled;
            double avgFillPrice   = execution.Order.AverageFillPrice > 0 ? execution.Order.AverageFillPrice : execution.Price;
            if (instrument == null || qty <= 0)
                return;

            string gid = ParseGid(execution.Order.Name);
            if (gid == null)
                return;

            lock (groupLock)
            {
                TradeGroup group;
                if (!tradeGroups.TryGetValue(gid, out group))
                    return;

                SlaveBracket sb;
                if (!group.Slaves.TryGetValue(slave, out sb))
                {
                    sb = new SlaveBracket();
                    group.Slaves[slave] = sb;
                }
                sb.EntryPrice = avgFillPrice;
                sb.Quantity   = qty;
                sb.Filled     = true;

                TrySubmitSlaveBracket(group, slave, sb);
            }
        }

        // ------------------------------------------------------------------
        // MASTER ATM BRACKET DISCOVERY + SLAVE BRACKET CREATION
        // ------------------------------------------------------------------

        private bool IsLegClaimed(Order o)
        {
            foreach (TradeGroup g in tradeGroups.Values)
                if (g.MasterTargetOrder == o || g.MasterStopOrder == o)
                    return true;
            return false;
        }

        private TradeGroup FindGroupByLeg(Order o, out bool isTarget)
        {
            isTarget = false;
            if (o == null)
                return null;
            foreach (TradeGroup g in tradeGroups.Values)
            {
                if (g.MasterTargetOrder == o) { isTarget = true;  return g; }
                if (g.MasterStopOrder   == o) { isTarget = false; return g; }
            }
            return null;
        }

        // Claims this sub-group's ATM exit orders from the master's live orders:
        // the exit-side working Limit (TP) + Stop (SL) that are NOT already claimed
        // by another sub-group, preferring a quantity match.
        private void DiscoverMasterBracket(TradeGroup group)
        {
            try
            {
                for (int pass = 0; pass < 2; pass++)
                {
                    bool requireQtyMatch = pass == 0;
                    foreach (Order o in Account.Orders)
                    {
                        if (o?.Instrument == null || o.Instrument.FullName != group.Instrument.FullName)
                            continue;
                        if (o.OrderState != OrderState.Working && o.OrderState != OrderState.Accepted)
                            continue;
                        if (IsOurName(o.Name))
                            continue;

                        bool isExitLeg = group.Direction == MarketPosition.Long ? IsSellSide(o.OrderAction) : IsBuySide(o.OrderAction);
                        if (!isExitLeg)
                            continue;
                        if (IsLegClaimed(o))
                            continue;
                        if (requireQtyMatch && o.Quantity != group.Quantity)
                            continue;

                        if (o.OrderType == OrderType.Limit && group.MasterTargetPrice <= 0)
                        {
                            group.MasterTargetOrder = o;
                            group.MasterTargetPrice = o.LimitPrice;
                        }
                        else if ((o.OrderType == OrderType.StopMarket || o.OrderType == OrderType.StopLimit) && group.MasterStopPrice <= 0)
                        {
                            group.MasterStopOrder = o;
                            group.MasterStopPrice = o.StopPrice;
                        }
                    }

                    if (group.MasterTargetPrice > 0 && group.MasterStopPrice > 0)
                        break;
                }
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier] ERROR scanning master orders: {ex.Message}");
            }
        }

        private bool ComputeSlaveBracketPrices(TradeGroup group, SlaveBracket sb,
            out double targetPrice, out double stopPrice, out int tpTicks, out int slTicks)
        {
            targetPrice = stopPrice = 0;
            tpTicks = slTicks = 0;
            if (group.MasterTargetPrice <= 0 || group.MasterStopPrice <= 0)
                return false;

            double tick = group.Instrument.MasterInstrument.TickSize;
            tpTicks = (int)Math.Round(Math.Abs(group.MasterTargetPrice - group.MasterEntryPrice) / tick);
            slTicks = (int)Math.Round(Math.Abs(group.MasterStopPrice - group.MasterEntryPrice) / tick);
            if (tpTicks <= 0 || slTicks <= 0)
                return false;

            targetPrice = group.Direction == MarketPosition.Long ? sb.EntryPrice + tpTicks * tick : sb.EntryPrice - tpTicks * tick;
            stopPrice   = group.Direction == MarketPosition.Long ? sb.EntryPrice - slTicks * tick : sb.EntryPrice + slTicks * tick;
            targetPrice = group.Instrument.MasterInstrument.RoundToTickSize(targetPrice);
            stopPrice   = group.Instrument.MasterInstrument.RoundToTickSize(stopPrice);
            return true;
        }

        // Submits a fresh OCO bracket for one sub-group on one slave. Must hold groupLock.
        private void SubmitSlaveOco(TradeGroup group, Account slave, SlaveBracket sb, int qty,
            double targetPrice, double stopPrice, int tpTicks, int slTicks, string verb)
        {
            OrderAction exitAction = group.Direction == MarketPosition.Long ? OrderAction.Sell : OrderAction.BuyToCover;
            string ocoId = Guid.NewGuid().ToString("N");

            try
            {
                Order targetOrder = slave.CreateOrder(
                    group.Instrument, exitAction, OrderType.Limit, OrderEntry.Manual,
                    TimeInForce.Gtc, qty, targetPrice, 0, ocoId,
                    MakeName(TargetPrefix, group.GroupId, slave.Name), DateTime.MaxValue, null);

                Order stopOrder = slave.CreateOrder(
                    group.Instrument, exitAction, OrderType.StopMarket, OrderEntry.Manual,
                    TimeInForce.Gtc, qty, 0, stopPrice, ocoId,
                    MakeName(StopPrefix, group.GroupId, slave.Name), DateTime.MaxValue, null);

                slave.Submit(new[] { targetOrder, stopOrder });

                sb.TargetOrder      = targetOrder;
                sb.StopOrder        = stopOrder;
                sb.BracketSubmitted = true;
                sb.LastTargetPrice  = targetPrice;
                sb.LastStopPrice    = stopPrice;
                sb.LastTpTicks      = tpTicks;
                sb.LastSlTicks      = slTicks;

                Print($"[TradeCopier]   -> {slave.Name} grp {group.GroupId} bracket {verb}: {qty} @ TP {targetPrice} ({tpTicks}t) / SL {stopPrice} ({slTicks}t)");
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier]   -> ERROR ({verb}) bracket on {slave.Name} grp {group.GroupId}: {ex.Message}");
            }
        }

        // Must hold groupLock.
        private void TrySubmitSlaveBracket(TradeGroup group, Account slave, SlaveBracket sb)
        {
            if (sb.BracketSubmitted || !sb.Filled)
                return;
            if (group.MasterTargetPrice <= 0 || group.MasterStopPrice <= 0)
                DiscoverMasterBracket(group);

            double targetPrice, stopPrice;
            int tpTicks, slTicks;
            if (!ComputeSlaveBracketPrices(group, sb, out targetPrice, out stopPrice, out tpTicks, out slTicks))
                return;

            SubmitSlaveOco(group, slave, sb, sb.Quantity, targetPrice, stopPrice, tpTicks, slTicks, "set");
        }

        // SAFE modification: cancel the current bracket now, resubmit only once
        // both legs are confirmed cancelled (from OnSlaveOrderUpdate). Must hold groupLock.
        private void RequestSlaveRebuild(TradeGroup group, Account slave, SlaveBracket sb)
        {
            if (!sb.Filled || !sb.BracketSubmitted)
                return;

            double targetPrice, stopPrice;
            int tpTicks, slTicks;
            if (!ComputeSlaveBracketPrices(group, sb, out targetPrice, out stopPrice, out tpTicks, out slTicks))
                return;

            sb.PendingTargetPrice = targetPrice;
            sb.PendingStopPrice   = stopPrice;
            sb.PendingTpTicks     = tpTicks;
            sb.PendingSlTicks     = slTicks;
            sb.RebuildPending     = true;

            try
            {
                if (!IsInactiveOrder(sb.TargetOrder)) slave.Cancel(new[] { sb.TargetOrder });
                if (!IsInactiveOrder(sb.StopOrder))   slave.Cancel(new[] { sb.StopOrder });
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier]   -> ERROR cancelling old {slave.Name} grp {group.GroupId} bracket: {ex.Message}");
            }

            Print($"[TradeCopier]   -> {slave.Name} grp {group.GroupId} update queued: TP {targetPrice} ({tpTicks}t) / SL {stopPrice} ({slTicks}t) (waiting for old bracket to cancel)");
        }

        private static bool IsInactiveOrder(Order o)
        {
            return o == null
                || o.OrderState == OrderState.Cancelled
                || o.OrderState == OrderState.Rejected
                || o.OrderState == OrderState.Filled
                || o.OrderState == OrderState.PartFilled;
        }

        // ------------------------------------------------------------------
        // SLAVE ORDER UPDATES (rebuild completion, flatten completion, errors)
        // ------------------------------------------------------------------

        private void OnSlaveOrderUpdate(Account slave, Order order, OrderEventArgs e)
        {
            string nm = order.Name ?? string.Empty;
            if (!IsOurName(nm))
                return;

            if (order.OrderState == OrderState.Rejected || e.Error != ErrorCode.NoError)
                Print($"[TradeCopier]   -> PROBLEM on {slave.Name}: {order.Name} state={order.OrderState} error={e.Error} comment='{e.Comment}'");

            if (order.Instrument == null)
                return;

            lock (groupLock)
            {
                // Drive any pending aggregate flatten for this slave/instrument first
                // (the sub-group may already be gone once the master is flat).
                DriveFlattenForSlave(slave, order.Instrument);

                string gid = ParseGid(nm);
                if (gid == null)
                    return;

                TradeGroup group;
                if (!tradeGroups.TryGetValue(gid, out group))
                    return;

                SlaveBracket sb;
                if (!group.Slaves.TryGetValue(slave, out sb) || !sb.RebuildPending)
                    return;

                if (!IsInactiveOrder(sb.TargetOrder) || !IsInactiveOrder(sb.StopOrder))
                    return;

                sb.RebuildPending = false;

                bool anyFilled = (sb.TargetOrder != null && (sb.TargetOrder.OrderState == OrderState.Filled || sb.TargetOrder.OrderState == OrderState.PartFilled))
                              || (sb.StopOrder   != null && (sb.StopOrder.OrderState   == OrderState.Filled || sb.StopOrder.OrderState   == OrderState.PartFilled));
                if (anyFilled)
                {
                    Print($"[TradeCopier]   -> {slave.Name} grp {gid} old bracket filled during update; not replacing.");
                    return;
                }

                SubmitSlaveOco(group, slave, sb, sb.Quantity,
                    sb.PendingTargetPrice, sb.PendingStopPrice, sb.PendingTpTicks, sb.PendingSlTicks, "rebuilt");
            }
        }

        // ------------------------------------------------------------------
        // POSITION / ORDER INSPECTION HELPERS
        // ------------------------------------------------------------------

        private void GetSlavePosition(Account slave, Instrument instr, out MarketPosition mp, out int qty)
        {
            mp = MarketPosition.Flat;
            qty = 0;
            try
            {
                foreach (Position p in slave.Positions)
                {
                    if (p?.Instrument == null || p.Instrument.FullName != instr.FullName)
                        continue;
                    mp  = p.MarketPosition;
                    qty = (int)Math.Abs(p.Quantity);
                    return;
                }
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier] WATCHDOG: ERROR reading positions on {slave.Name}: {ex.Message}");
            }
        }

        private bool HasWorkingOurOrder(Account slave, Instrument instr, string prefix)
        {
            try
            {
                foreach (Order o in slave.Orders)
                {
                    if (o?.Instrument == null || o.Instrument.FullName != instr.FullName)
                        continue;
                    if (o.OrderState != OrderState.Working && o.OrderState != OrderState.Accepted)
                        continue;
                    if ((o.Name ?? string.Empty).StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
            }
            catch { }
            return false;
        }

        private bool HasWorkingGidOrder(Account slave, Instrument instr, string gid, string prefix)
        {
            string tag = prefix + gid + "-";
            try
            {
                foreach (Order o in slave.Orders)
                {
                    if (o?.Instrument == null || o.Instrument.FullName != instr.FullName)
                        continue;
                    if (o.OrderState != OrderState.Working && o.OrderState != OrderState.Accepted)
                        continue;
                    if ((o.Name ?? string.Empty).StartsWith(tag, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
            }
            catch { }
            return false;
        }

        private int SumWorkingQty(Account slave, Instrument instr, string prefix)
        {
            int sum = 0;
            try
            {
                foreach (Order o in slave.Orders)
                {
                    if (o?.Instrument == null || o.Instrument.FullName != instr.FullName)
                        continue;
                    if (o.OrderState != OrderState.Working && o.OrderState != OrderState.Accepted)
                        continue;
                    if ((o.Name ?? string.Empty).StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        sum += o.Quantity;
                }
            }
            catch { }
            return sum;
        }

        // ------------------------------------------------------------------
        // FLATTEN (safe: cancel bracket first, then market-close the remainder)
        // ------------------------------------------------------------------

        private void CancelOurBracketOrders(Account slave, Instrument instr)
        {
            try
            {
                List<Order> toCancel = new List<Order>();
                foreach (Order o in slave.Orders)
                {
                    if (o?.Instrument == null || o.Instrument.FullName != instr.FullName)
                        continue;
                    if (o.OrderState != OrderState.Working && o.OrderState != OrderState.Accepted)
                        continue;
                    string nm = o.Name ?? string.Empty;
                    if (nm.StartsWith(EntryPrefix,  StringComparison.OrdinalIgnoreCase) ||
                        nm.StartsWith(TargetPrefix, StringComparison.OrdinalIgnoreCase) ||
                        nm.StartsWith(StopPrefix,   StringComparison.OrdinalIgnoreCase))
                        toCancel.Add(o);
                }
                if (toCancel.Count > 0)
                    slave.Cancel(toCancel);
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier]   -> ERROR cancelling {slave.Name} orders: {ex.Message}");
            }
        }

        // Returns true once the slave is confirmed FLAT for this instrument.
        // Never market-closes while a bracket order of ours is still live (that
        // could double the exit into an opposite position).
        private bool EnsureSlaveFlat(Account slave, Instrument instr)
        {
            MarketPosition mp;
            int qty;
            GetSlavePosition(slave, instr, out mp, out qty);
            if (mp == MarketPosition.Flat || qty <= 0)
                return true;

            if (HasWorkingOurOrder(slave, instr, FlatPrefix))
                return false; // a close is already working

            if (HasWorkingOurOrder(slave, instr, StopPrefix) || HasWorkingOurOrder(slave, instr, TargetPrefix))
            {
                CancelOurBracketOrders(slave, instr);
                return false; // close once the bracket is confirmed gone
            }

            OrderAction closeAction = mp == MarketPosition.Long ? OrderAction.Sell : OrderAction.BuyToCover;
            try
            {
                Order close = slave.CreateOrder(
                    instr, closeAction, OrderType.Market, OrderEntry.Manual,
                    TimeInForce.Day, qty, 0, 0, string.Empty,
                    FlatPrefix + slave.Name, DateTime.MaxValue, null);
                slave.Submit(new[] { close });
                Print($"[TradeCopier]   -> Flattened {slave.Name}: {closeAction} {qty} {instr.FullName} (market).");
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier]   -> ERROR flattening {slave.Name}: {ex.Message}");
            }
            return false;
        }

        private void DriveFlattenForSlave(Account slave, Instrument instr)
        {
            for (int i = orphanWatch.Count - 1; i >= 0; i--)
            {
                OrphanWatch ow = orphanWatch[i];
                if (!ow.Flatten || ow.Slave != slave || ow.Instrument == null || instr == null)
                    continue;
                if (ow.Instrument.FullName != instr.FullName)
                    continue;
                if (EnsureSlaveFlat(ow.Slave, ow.Instrument))
                    orphanWatch.RemoveAt(i);
            }
        }

        // Re-attaches a full-position protective bracket if a watched (protect-mode)
        // slave has an open position with no working orders of ours. Returns true
        // once flat.
        private bool EnsureSlaveProtected(Account slave, Instrument instr, MarketPosition dir,
            double targetPrice, double stopPrice, int tpTicks, int slTicks, SlaveBracket sb)
        {
            MarketPosition mp;
            int qty;
            GetSlavePosition(slave, instr, out mp, out qty);
            if (mp == MarketPosition.Flat || qty <= 0)
                return true;
            if (mp != dir)
                return false;
            if (HasWorkingOurOrder(slave, instr, StopPrefix))
                return false;
            if (HasWorkingOurOrder(slave, instr, TargetPrefix))
            {
                Print($"[TradeCopier] WATCHDOG: {slave.Name} has a target but NO stop on {instr.FullName}; leaving for MANUAL review.");
                return false;
            }
            if (stopPrice <= 0 || targetPrice <= 0)
            {
                Print($"[TradeCopier] WATCHDOG: {slave.Name} has an UNPROTECTED {mp} {qty} {instr.FullName} but no known bracket prices -- MANUAL attention needed.");
                return false;
            }

            OrderAction exitAction = dir == MarketPosition.Long ? OrderAction.Sell : OrderAction.BuyToCover;
            string ocoId = Guid.NewGuid().ToString("N");
            try
            {
                Order targetOrder = slave.CreateOrder(instr, exitAction, OrderType.Limit, OrderEntry.Manual,
                    TimeInForce.Gtc, qty, targetPrice, 0, ocoId, TargetPrefix + "X-" + slave.Name, DateTime.MaxValue, null);
                Order stopOrder = slave.CreateOrder(instr, exitAction, OrderType.StopMarket, OrderEntry.Manual,
                    TimeInForce.Gtc, qty, 0, stopPrice, ocoId, StopPrefix + "X-" + slave.Name, DateTime.MaxValue, null);
                slave.Submit(new[] { targetOrder, stopOrder });
                Print($"[TradeCopier] WATCHDOG: RE-ATTACHED protective bracket on {slave.Name}: {mp} {qty} {instr.FullName} TP {targetPrice} / SL {stopPrice}");
            }
            catch (Exception ex)
            {
                Print($"[TradeCopier] WATCHDOG: ERROR re-attaching on {slave.Name}: {ex.Message}");
            }
            return false;
        }

        // ------------------------------------------------------------------
        // MASTER ATM ORDER UPDATES (discovery, modification, cancellation)
        // ------------------------------------------------------------------

        private void OnAnyAccountOrderUpdate(object sender, OrderEventArgs e)
        {
            if (!EnableCopying || !isActiveCopier)
                return;

            Account account = sender as Account;
            Order order     = e?.Order;
            if (account == null || order == null)
                return;

            if (account != Account)
            {
                OnSlaveOrderUpdate(account, order, e);
                return;
            }

            if (order.Instrument == null)
                return;
            if (IsOurName(order.Name)) // should never be on the master
                return;

            bool isTargetType = order.OrderType == OrderType.Limit;
            bool isStopType   = order.OrderType == OrderType.StopMarket || order.OrderType == OrderType.StopLimit;
            if (!isTargetType && !isStopType)
                return;

            lock (groupLock)
            {
                bool isTarget;
                TradeGroup group = FindGroupByLeg(order, out isTarget);

                if (group == null)
                {
                    // An unclaimed exit order: assign it to a sub-group for this
                    // instrument that still needs the matching leg.
                    group = AssignUnclaimedLeg(order, isTargetType, out isTarget);
                    if (group == null)
                        return;
                }

                double tick = group.Instrument.MasterInstrument.TickSize;

                if (order.OrderState == OrderState.Cancelled || order.OrderState == OrderState.Rejected)
                {
                    if (isTarget && group.MasterTargetOrder == order) { group.MasterTargetOrder = null; group.MasterTargetPrice = 0; }
                    else if (!isTarget && group.MasterStopOrder == order) { group.MasterStopOrder = null; group.MasterStopPrice = 0; }
                    return;
                }

                if (order.OrderState != OrderState.Working && order.OrderState != OrderState.Accepted)
                    return;

                double newPrice    = isTarget ? order.LimitPrice : order.StopPrice;
                double storedPrice = isTarget ? group.MasterTargetPrice : group.MasterStopPrice;
                if (newPrice <= 0)
                    return;

                if (isTarget) group.MasterTargetOrder = order;
                else          group.MasterStopOrder   = order;

                bool isNewOrChanged = storedPrice <= 0 || Math.Abs(newPrice - storedPrice) >= tick / 2.0;
                if (!isNewOrChanged)
                    return;

                if (isTarget) group.MasterTargetPrice = newPrice;
                else          group.MasterStopPrice   = newPrice;

                int newTicks = (int)Math.Round(Math.Abs(newPrice - group.MasterEntryPrice) / tick);
                if (newTicks <= 0)
                    return;

                Print($"[TradeCopier] Master grp {group.GroupId} {(isTarget ? "TP" : "SL")} now {newTicks} ticks ({newPrice}). Syncing {group.Slaves.Count} slave(s).");

                foreach (var kvp in group.Slaves)
                {
                    Account slave   = kvp.Key;
                    SlaveBracket sb = kvp.Value;
                    if (!sb.BracketSubmitted)
                        TrySubmitSlaveBracket(group, slave, sb);
                    else
                        RequestSlaveRebuild(group, slave, sb);
                }
            }
        }

        // Assigns a newly-seen unclaimed master exit order to a sub-group of the
        // same instrument that still lacks the matching leg (prefers qty match).
        private TradeGroup AssignUnclaimedLeg(Order order, bool isTargetType, out bool isTarget)
        {
            isTarget = isTargetType;
            List<TradeGroup> groups = tradeGroups.Values.Where(g => g.Instrument.FullName == order.Instrument.FullName).ToList();
            if (groups.Count == 0)
                return null;

            // exit-side sanity: only assign legs that match the group's exit side.
            for (int pass = 0; pass < 2; pass++)
            {
                bool requireQty = pass == 0;
                foreach (TradeGroup g in groups)
                {
                    bool isExitLeg = g.Direction == MarketPosition.Long ? IsSellSide(order.OrderAction) : IsBuySide(order.OrderAction);
                    if (!isExitLeg)
                        continue;
                    if (requireQty && order.Quantity != g.Quantity)
                        continue;
                    if (isTargetType && g.MasterTargetPrice <= 0 && !IsLegClaimed(order))
                        return g;
                    if (!isTargetType && g.MasterStopPrice <= 0 && !IsLegClaimed(order))
                        return g;
                }
            }
            return null;
        }

        #region Properties
        [NinjaScriptProperty]
        [Display(Name = "Excluded Accounts (comma separated)", Order = 1, GroupName = "1. Group Copier Settings")]
        public string ExcludedAccountNames { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Copying", Order = 2, GroupName = "1. Group Copier Settings")]
        public bool EnableCopying { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Flatten Slaves When Master Flat", Order = 3, GroupName = "1. Group Copier Settings")]
        public bool FlattenSlavesWhenMasterFlat { get; set; }
        #endregion
    }
}
