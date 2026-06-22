/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Sockets;
using System.Text;
using System.Xml;
using Google.Protobuf;
using Google.Protobuf.Compiler;
using IBApi;

namespace Samples
{
    //! [ewrapperimpl]
    public class EWrapperImpl : EWrapper 
    {
    //! [ewrapperimpl]
        private int nextOrderId;
        //! [socket_declare]
        EClientSocket clientSocket;
        public readonly EReaderSignal Signal;
        //! [socket_declare]

        //! [socket_init]
        public EWrapperImpl()
        {
            Signal = new EReaderMonitorSignal();
            clientSocket = new EClientSocket(this, Signal);
        }
        //! [socket_init]

        public EClientSocket ClientSocket
        {
            get { return clientSocket; }
            set { clientSocket = value; }
        }

        public int NextOrderId
        {
            get { return nextOrderId; }
            set { nextOrderId = value; }
        }

        public string BboExchange { get; private set; }

        public virtual void error(Exception e)
        {
            switch (e)
            {
                case SocketException s:
                    Console.WriteLine(s.Message);
                    break;
                default:
                    Console.WriteLine("Exception thrown: " + e);
                    throw e;
            }
        }
        
        public virtual void error(string str)
        {
            Console.WriteLine("Error: "+str+"\n");
        }
        
        //! [error]
        public virtual void error(int id, long errorTime, int errorCode, string errorMsg, string advancedOrderRejectJson)
        {
            string errorTimeStr = errorTime > 0 ? Util.UnixMilliSecondsToString(errorTime, "yyyyMMdd-HH:mm:ss") : "";
            if (!Util.StringIsEmpty(advancedOrderRejectJson)) 
            {
                Console.WriteLine("Error. Id: " + id + ", Time: " + errorTimeStr + ", Code: " + errorCode + ", Msg: " + errorMsg + ", AdvancedOrderRejectJson: " + advancedOrderRejectJson + "\n");
            }
            else
            {
                Console.WriteLine("Error. Id: " + id + ", Time: " + errorTimeStr + ", Code: " + errorCode + ", Msg: " + errorMsg + "\n");
            }
        }
        //! [error]

        public virtual void connectionClosed()
        {
            Console.WriteLine("Connection closed.\n");
        }
        
        public virtual void currentTime(long time) 
        {
            string timeStr = Util.UnixSecondsToString(time, "MMM dd, yyyy HH:mm:ss");
            Console.WriteLine("Current Time " + time + " : " + timeStr + "\n");
        }

        //! [tickprice]
        public virtual void tickPrice(int tickerId, int field, double price, TickAttrib attribs) 
        {
            Console.WriteLine("Tick Price. Ticker Id:" + tickerId + ", Field: " + field + ", Price: " + Util.DoubleMaxString(price) + ", CanAutoExecute: " + attribs.CanAutoExecute + 
                ", PastLimit: " + attribs.PastLimit + ", PreOpen: " + attribs.PreOpen);
        }
        //! [tickprice]
        
        //! [ticksize]
        public virtual void tickSize(int tickerId, int field, decimal size)
        {
            Console.WriteLine("Tick Size. Ticker Id:" + tickerId + ", Field: " + field + ", Size: " + Util.DecimalMaxString(size));
        }
        //! [ticksize]
        
        //! [tickstring]
        public virtual void tickString(int tickerId, int tickType, string value)
        {
            Console.WriteLine("Tick string. Ticker Id:" + tickerId + ", Type: " + tickType + ", Value: " + value);
        }
        //! [tickstring]

        //! [tickgeneric]
        public virtual void tickGeneric(int tickerId, int field, double value)
        {
            Console.WriteLine("Tick Generic. Ticker Id:" + tickerId + ", Field: " + field + ", Value: " + Util.DoubleMaxString(value));
        }
        //! [tickgeneric]

        public virtual void tickEFP(int tickerId, int tickType, double basisPoints, string formattedBasisPoints, double impliedFuture, int holdDays, string futureLastTradeDate, double dividendImpact, double dividendsToLastTradeDate)
        {
            Console.WriteLine("TickEFP. " + tickerId + ", Type: " + tickType+", BasisPoints: " + Util.DoubleMaxString(basisPoints) +", FormattedBasisPoints: " + formattedBasisPoints + 
                ", ImpliedFuture: " + Util.DoubleMaxString(impliedFuture) +", HoldDays: " + Util.IntMaxString(holdDays) + ", FutureLastTradeDate: " + futureLastTradeDate + 
                ", DividendImpact: " + Util.DoubleMaxString(dividendImpact) + ", DividendsToLastTradeDate: " + Util.DoubleMaxString(dividendsToLastTradeDate));
        }
        
        //! [ticksnapshotend]
        public virtual void tickSnapshotEnd(int tickerId)
        {
            Console.WriteLine("TickSnapshotEnd: "+tickerId);
        }
        //! [ticksnapshotend]

        //! [nextvalidid]
        public virtual void nextValidId(int orderId) 
        {
            Console.WriteLine("Next Valid Id: "+orderId);
            NextOrderId = orderId;
        }
        //! [nextvalidid]

        //! [deltaneutralvalidation]
        public virtual void deltaNeutralValidation(int reqId, DeltaNeutralContract deltaNeutralContract)
        {
            Console.WriteLine("DeltaNeutralValidation. " + reqId + ", ConId: " + deltaNeutralContract.ConId + ", Delta: " + Util.DoubleMaxString(deltaNeutralContract.Delta) + ", Price: " + Util.DoubleMaxString(deltaNeutralContract.Price));
        }
        //! [deltaneutralvalidation]

        //! [managedaccounts]
        public virtual void managedAccounts(string accountsList) 
        {
            Console.WriteLine("Account list: "+accountsList);
        }
        //! [managedaccounts]

        //! [tickoptioncomputation]
        public virtual void tickOptionComputation(int tickerId, int field, int tickAttrib, double impliedVolatility, double delta, double optPrice, double pvDividend, double gamma, double vega, double theta, double undPrice)
        {
            Console.WriteLine("TickOptionComputation. TickerId: " + tickerId + ", field: " + field + ", TickAttrib: " + Util.IntMaxString(tickAttrib) + ", ImpliedVolatility: " + Util.DoubleMaxString(impliedVolatility) + 
                ", Delta: " + Util.DoubleMaxString(delta) + ", OptionPrice: " + Util.DoubleMaxString(optPrice) +", pvDividend: " + Util.DoubleMaxString(pvDividend) + 
                ", Gamma: " + Util.DoubleMaxString(gamma) + ", Vega: " + Util.DoubleMaxString(vega) + ", Theta: " + Util.DoubleMaxString(theta) + ", UnderlyingPrice: " + Util.DoubleMaxString(undPrice));
        }
        //! [tickoptioncomputation]

        //! [accountsummary]
        public virtual void accountSummary(int reqId, string account, string tag, string value, string currency)
        {
            Console.WriteLine("Acct Summary. ReqId: " + reqId + ", Acct: " + account + ", Tag: " + tag + ", Value: " + value + ", Currency: " + currency);
        }
        //! [accountsummary]

        //! [accountsummaryend]
        public virtual void accountSummaryEnd(int reqId)
        {
            Console.WriteLine("AccountSummaryEnd. Req Id: "+reqId+"\n");
        }
        //! [accountsummaryend]

        //! [updateaccountvalue]
        public virtual void updateAccountValue(string key, string value, string currency, string accountName)
        {
            Console.WriteLine("UpdateAccountValue. Key: " + key + ", Value: " + value + ", Currency: " + currency + ", AccountName: " + accountName);
        }
        //! [updateaccountvalue]

        //! [updateportfolio]
        public virtual void updatePortfolio(Contract contract, decimal position, double marketPrice, double marketValue, double averageCost, double unrealizedPNL, double realizedPNL, string accountName)
        {
            Console.WriteLine("UpdatePortfolio. " + contract.Symbol + ", " + contract.SecType + " @ " + contract.Exchange
                + ": Position: " + Util.DecimalMaxString(position) + ", MarketPrice: " + Util.DoubleMaxString(marketPrice) + ", MarketValue: " + Util.DoubleMaxString(marketValue) + 
                ", AverageCost: " + Util.DoubleMaxString(averageCost) + ", UnrealizedPNL: " + Util.DoubleMaxString(unrealizedPNL) + ", RealizedPNL: " + Util.DoubleMaxString(realizedPNL) + 
                ", AccountName: " + accountName);
        }
        //! [updateportfolio]

        //! [updateaccounttime]
        public virtual void updateAccountTime(string timestamp)
        {
            Console.WriteLine("UpdateAccountTime. Time: " + timestamp+"\n");
        }
        //! [updateaccounttime]

        //! [accountdownloadend]
        public virtual void accountDownloadEnd(string account)
        {
            Console.WriteLine("Account download finished: "+account+"\n");
        }
        //! [accountdownloadend]

        public virtual void orderStatus(int orderId, string status, decimal filled, decimal remaining, double avgFillPrice, long permId, int parentId, double lastFillPrice, int clientId, string whyHeld, double mktCapPrice) {}
        public virtual void openOrder(int orderId, Contract contract, Order order, OrderState orderState) {}
        public virtual void openOrderEnd() {}

        public void printSoftDollarTier(SoftDollarTier softDollarTier) 
        {
            Console.WriteLine("\tSoftDollarTier:{name=" + softDollarTier.Name + ", val=" + softDollarTier.Value + ", displayName=" + softDollarTier.DisplayName + "}");
        }

        //! [contractdetails]
        public virtual void contractDetails(int reqId, ContractDetails contractDetails)
        {
            Console.WriteLine("ContractDetails begin. ReqId: " + reqId);
            printContractMsg(contractDetails.Contract);
            printContractDetailsMsg(contractDetails);
            Console.WriteLine("ContractDetails end. ReqId: " + reqId);
        }
        //! [contractdetails]

        public void printContractMsg(Contract contract)
        {
            Console.WriteLine("\tConId: " + contract.ConId);
            Console.WriteLine("\tSymbol: " + contract.Symbol);
            Console.WriteLine("\tSecType: " + contract.SecType);
            Console.WriteLine("\tLastTradeDateOrContractMonth: " + contract.LastTradeDateOrContractMonth);
            Console.WriteLine("\tLastTradeDate: " + contract.LastTradeDate);
            Console.WriteLine("\tStrike: " + Util.DoubleMaxString(contract.Strike));
            Console.WriteLine("\tRight: " + contract.Right);
            Console.WriteLine("\tMultiplier: " + contract.Multiplier);
            Console.WriteLine("\tExchange: " + contract.Exchange);
            Console.WriteLine("\tPrimaryExchange: " + contract.PrimaryExch);
            Console.WriteLine("\tCurrency: " + contract.Currency);
            Console.WriteLine("\tLocalSymbol: " + contract.LocalSymbol);
            Console.WriteLine("\tTradingClass: " + contract.TradingClass);
        }

        public void printContractDetailsMsg(ContractDetails contractDetails)
        {
            Console.WriteLine("\tMarketName: " + contractDetails.MarketName);
            Console.WriteLine("\tMinTick: " + Util.DoubleMaxString(contractDetails.MinTick));
            Console.WriteLine("\tPriceMagnifier: " + Util.IntMaxString(contractDetails.PriceMagnifier));
            Console.WriteLine("\tOrderTypes: " + contractDetails.OrderTypes);
            Console.WriteLine("\tValidExchanges: " + contractDetails.ValidExchanges);
            Console.WriteLine("\tUnderConId: " + Util.IntMaxString(contractDetails.UnderConId));
            Console.WriteLine("\tLongName: " + contractDetails.LongName);
            Console.WriteLine("\tContractMonth: " + contractDetails.ContractMonth);
            Console.WriteLine("\tIndystry: " + contractDetails.Industry);
            Console.WriteLine("\tCategory: " + contractDetails.Category);
            Console.WriteLine("\tSubCategory: " + contractDetails.Subcategory);
            Console.WriteLine("\tTimeZoneId: " + contractDetails.TimeZoneId);
            Console.WriteLine("\tTradingHours: " + contractDetails.TradingHours);
            Console.WriteLine("\tLiquidHours: " + contractDetails.LiquidHours);
            Console.WriteLine("\tEvRule: " + contractDetails.EvRule);
            Console.WriteLine("\tEvMultiplier: " + Util.DoubleMaxString(contractDetails.EvMultiplier));
            Console.WriteLine("\tAggGroup: " + Util.IntMaxString(contractDetails.AggGroup));
            Console.WriteLine("\tUnderSymbol: " + contractDetails.UnderSymbol);
            Console.WriteLine("\tUnderSecType: " + contractDetails.UnderSecType);
            Console.WriteLine("\tMarketRuleIds: " + contractDetails.MarketRuleIds);
            Console.WriteLine("\tRealExpirationDate: " + contractDetails.RealExpirationDate);
            Console.WriteLine("\tLastTradeTime: " + contractDetails.LastTradeTime);
            Console.WriteLine("\tStock Type: " + contractDetails.StockType);
            Console.WriteLine("\tMinSize: " + Util.DecimalMaxString(contractDetails.MinSize));
            Console.WriteLine("\tSizeIncrement: " + Util.DecimalMaxString(contractDetails.SizeIncrement));
            Console.WriteLine("\tSuggestedSizeIncrement: " + Util.DecimalMaxString(contractDetails.SuggestedSizeIncrement));
            Console.WriteLine("\tMinAlgoSize: " + Util.DecimalMaxString(contractDetails.MinAlgoSize));
            Console.WriteLine("\tLastPricePrecision: " + Util.DecimalMaxString(contractDetails.LastPricePrecision));
            Console.WriteLine("\tLastSizePrecision: " + Util.DecimalMaxString(contractDetails.LastSizePrecision));
            Console.WriteLine("\tEventContract1: " + contractDetails.EventContract1);
            Console.WriteLine("\tEventContractDescription1: " + contractDetails.EventContractDescription1);
            Console.WriteLine("\tEventContractDescription2: " + contractDetails.EventContractDescription2);

            if (contractDetails.Contract.SecType == "FUND")
            {
                Console.WriteLine("\tFund Data: ");
                Console.WriteLine("\t\tFundName: " + contractDetails.FundName);
                Console.WriteLine("\t\tFundFamily: " + contractDetails.FundFamily);
                Console.WriteLine("\t\tFundType: " + contractDetails.FundType);
                Console.WriteLine("\t\tFundFrontLoad: " + contractDetails.FundFrontLoad);
                Console.WriteLine("\t\tFundBackLoad: " + contractDetails.FundBackLoad);
                Console.WriteLine("\t\tFundBackLoadTimeInterval: " + contractDetails.FundBackLoadTimeInterval);
                Console.WriteLine("\t\tFundManagementFee: " + contractDetails.FundManagementFee);
                Console.WriteLine("\t\tFundClosed: " + (contractDetails.FundClosed ? "yes" : "no"));
                Console.WriteLine("\t\tFundClosedForNewInvestors: " + (contractDetails.FundClosedForNewInvestors ? "yes" : "no"));
                Console.WriteLine("\t\tFundClosedForNewMoney: " + (contractDetails.FundClosedForNewMoney ? "yes" : "no"));
                Console.WriteLine("\t\tFundNotifyAmount: " + contractDetails.FundNotifyAmount);
                Console.WriteLine("\t\tFundMinimumInitialPurchase: " + contractDetails.FundMinimumInitialPurchase);
                Console.WriteLine("\t\tFundSubsequentMinimumPurchase: " + contractDetails.FundSubsequentMinimumPurchase);
                Console.WriteLine("\t\tFundBlueSkyStates: " + contractDetails.FundBlueSkyStates);
                Console.WriteLine("\t\tFundBlueSkyTerritories: " + contractDetails.FundBlueSkyTerritories);
                Console.WriteLine("\t\tFundDistributionPolicyIndicator: " + CFundDistributionPolicyIndicator.getFundDistributionPolicyIndicatorName(contractDetails.FundDistributionPolicyIndicator));
                Console.WriteLine("\t\tFundAssetType: " + CFundAssetType.getFundAssetTypeName(contractDetails.FundAssetType));
            }

            printContractDetailsSecIdList(contractDetails.SecIdList);
            printContractDetailsIneligibilityReasonList(contractDetails.IneligibilityReasonList);
        }

        public void printContractDetailsSecIdList(List<TagValue> secIdList)
        {
            if (secIdList != null && secIdList.Count > 0) {
                Console.Write("\tSecIdList: {");
                foreach (TagValue tagValue in secIdList)
                {
                    Console.Write(tagValue.Tag + "=" + tagValue.Value + ";");
                }
                Console.WriteLine("}");
            }
        }

        public void printContractDetailsIneligibilityReasonList(List<IneligibilityReason> ineligibilityReasonList)
        {
            if (ineligibilityReasonList != null && ineligibilityReasonList.Count > 0)
            {
                Console.Write("\tIneligibilityReasonList: {");
                foreach (IneligibilityReason ineligibilityReason in ineligibilityReasonList)
                {
                    Console.Write("[id: " + ineligibilityReason.Id + ", description: " + ineligibilityReason.Description + "];");
                }
                Console.WriteLine("}");
            }
        }

        public void printBondContractDetailsMsg(ContractDetails contractDetails)
        {
            Console.WriteLine("\tSymbol: " + contractDetails.Contract.Symbol);
            Console.WriteLine("\tSecType: " + contractDetails.Contract.SecType);
            Console.WriteLine("\tCusip: " + contractDetails.Cusip);
            Console.WriteLine("\tCoupon: " + Util.DoubleMaxString(contractDetails.Coupon));
            Console.WriteLine("\tMaturity: " + contractDetails.Maturity);
            Console.WriteLine("\tIssueDate: " + contractDetails.IssueDate);
            Console.WriteLine("\tRatings: " + contractDetails.Ratings);
            Console.WriteLine("\tBondType: " + contractDetails.BondType);
            Console.WriteLine("\tCouponType: " + contractDetails.CouponType);
            Console.WriteLine("\tConvertible: " + contractDetails.Convertible);
            Console.WriteLine("\tCallable: " + contractDetails.Callable);
            Console.WriteLine("\tPutable: " + contractDetails.Putable);
            Console.WriteLine("\tDescAppend: " + contractDetails.DescAppend);
            Console.WriteLine("\tExchange: " + contractDetails.Contract.Exchange);
            Console.WriteLine("\tCurrency: " + contractDetails.Contract.Currency);
            Console.WriteLine("\tMarketName: " + contractDetails.MarketName);
            Console.WriteLine("\tTradingClass: " + contractDetails.Contract.TradingClass);
            Console.WriteLine("\tConId: " + contractDetails.Contract.ConId);
            Console.WriteLine("\tMinTick: " + Util.DoubleMaxString(contractDetails.MinTick));
            Console.WriteLine("\tOrderTypes: " + contractDetails.OrderTypes);
            Console.WriteLine("\tValidExchanges: " + contractDetails.ValidExchanges);
            Console.WriteLine("\tNextOptionDate: " + contractDetails.NextOptionDate);
            Console.WriteLine("\tNextOptionType: " + contractDetails.NextOptionType);
            Console.WriteLine("\tNextOptionPartial: " + contractDetails.NextOptionPartial);
            Console.WriteLine("\tNotes: " + contractDetails.Notes);
            Console.WriteLine("\tLong Name: " + contractDetails.LongName);
            Console.WriteLine("\tTimeZoneId: " + contractDetails.TimeZoneId);
            Console.WriteLine("\tTradingHours: " + contractDetails.TradingHours);
            Console.WriteLine("\tLiquidHours: " + contractDetails.LiquidHours);
            Console.WriteLine("\tEvRule: " + contractDetails.EvRule);
            Console.WriteLine("\tEvMultiplier: " + Util.DoubleMaxString(contractDetails.EvMultiplier));
            Console.WriteLine("\tAggGroup: " + Util.IntMaxString(contractDetails.AggGroup));
            Console.WriteLine("\tMarketRuleIds: " + contractDetails.MarketRuleIds);
            Console.WriteLine("\tLastTradeTime: " + contractDetails.LastTradeTime);
            Console.WriteLine("\tMinSize: " + Util.DecimalMaxString(contractDetails.MinSize));
            Console.WriteLine("\tSizeIncrement: " + Util.DecimalMaxString(contractDetails.SizeIncrement));
            Console.WriteLine("\tSuggestedSizeIncrement: " + Util.DecimalMaxString(contractDetails.SuggestedSizeIncrement));
            printContractDetailsSecIdList(contractDetails.SecIdList);
        }


        //! [contractdetailsend]
        public virtual void contractDetailsEnd(int reqId)
        {
            Console.WriteLine("ContractDetailsEnd. "+reqId+"\n");
        }
        //! [contractdetailsend]

        //! [execdetails]
        public virtual void execDetails(int reqId, Contract contract, Execution execution)
        {
            Console.WriteLine("ExecDetails. ReqId:" + reqId + 
                ", Contract - ConId: " + Util.IntMaxString(contract.ConId) + ", Symbol: " + contract.Symbol + 
                ", LastTradeDateOrContractMonth: " + contract.LastTradeDateOrContractMonth + ", Strike: " + Util.DoubleMaxString(contract.Strike) + ", Right: " + contract.Right + 
                ", Multiplier: " + contract.Multiplier + ", Exchange: " + contract.Exchange + ", Currency: " + contract.Currency + ", LocalSymbol: " + contract.LocalSymbol + 
                ", TradingClass: " + contract.TradingClass + 
                ", Execution - OrderId: " + Util.IntMaxString(execution.OrderId) + ", ExecId: " + execution.ExecId + ", Time: " + execution.Time + ", AcctNumber: " + execution.AcctNumber + 
                ", Exchange: " + execution.Exchange + ", Side: " + execution.Side + ", Shares: " + Util.DecimalMaxString(execution.Shares) + 
                ", Price: " + Util.DoubleMaxString(execution.Price) + ", PermId: " + Util.LongMaxString(execution.PermId) + ", ClientId: " + Util.IntMaxString(execution.ClientId) +
                ", Liquidation: " + (execution.Liquidation == 1 ? "true" : "false") + ", CumQty: " + Util.DecimalMaxString(execution.CumQty) + ", AvgPrice: " + Util.DoubleMaxString(execution.AvgPrice) + 
                ", OrderRef: " + execution.OrderRef + ", EvRule: " + execution.EvRule + ", EvMultiplier: " + Util.DoubleMaxString(execution.EvMultiplier) +
                ", ModelCode: " + execution.ModelCode + ", LastLiquidity: " + execution.LastLiquidity + ", PendingPriceRevision: " + (execution.PendingPriceRevision ? "true" : "false") + 
                ", Submitter: " + execution.Submitter + ", OptExerciseOrLapseType: " + COptionExerciseType.getOptionExerciseTypeName(execution.OptExerciseOrLapseType));
        }
        //! [execdetails]

        //! [execdetailsend]
        public virtual void execDetailsEnd(int reqId)
        {
            Console.WriteLine("ExecDetailsEnd. ReqId:" + reqId);
        }
        //! [execdetailsend]

        //! [commissionandfeesreport]
        public virtual void commissionAndFeesReport(CommissionAndFeesReport commissionAndFeesReport)
        {
            Console.WriteLine("CommissionAndFeesReport. " + commissionAndFeesReport.ExecId + " - " + Util.DoubleMaxString(commissionAndFeesReport.CommissionAndFees) + " " + commissionAndFeesReport.Currency + " RPNL " + Util.DoubleMaxString(commissionAndFeesReport.RealizedPNL));
        }
        //! [commissionandfeesreport]

        //! [fundamentaldata]
        public virtual void fundamentalData(int reqId, string data)
        {
            Console.WriteLine("FundamentalData. " + reqId + "" + data+"\n");
        }
        //! [fundamentaldata]

        //! [historicaldata]
        public virtual void historicalData(int reqId, Bar bar)
        {
            Console.WriteLine("HistoricalData. " + reqId + " - Time: " + bar.Time + ", Open: " + Util.DoubleMaxString(bar.Open) + ", High: " + Util.DoubleMaxString(bar.High) + 
                ", Low: " + Util.DoubleMaxString(bar.Low) + ", Close: " + Util.DoubleMaxString(bar.Close) + ", Volume: " + Util.DecimalMaxString(bar.Volume) + 
                ", Count: " + Util.IntMaxString(bar.Count) + ", WAP: " + Util.DecimalMaxString(bar.WAP));
        }
        //! [historicaldata]

        //! [marketdatatype]
        public virtual void marketDataType(int reqId, int marketDataType)
        {
            Console.WriteLine("MarketDataType. "+reqId+", Type: "+marketDataType+"\n");
        }
        //! [marketdatatype]

        //! [updatemktdepth]
        public virtual void updateMktDepth(int tickerId, int position, int operation, int side, double price, decimal size)
        {
            Console.WriteLine("UpdateMarketDepth. " + tickerId + " - Position: " + position + ", Operation: " + operation + ", Side: " + side + ", Price: " + Util.DoubleMaxString(price) + ", Size: " + Util.DecimalMaxString(size));
        }
        //! [updatemktdepth]

        //! [updatemktdepthl2]
        public virtual void updateMktDepthL2(int tickerId, int position, string marketMaker, int operation, int side, double price, decimal size, bool isSmartDepth)
        {
            Console.WriteLine("UpdateMarketDepthL2. " + tickerId + " - Position: " + position + ", Operation: " + operation + ", Side: " + side + ", Price: " + Util.DoubleMaxString(price) + ", Size: " + Util.DecimalMaxString(size) + ", isSmartDepth: " + isSmartDepth);
        }
        //! [updatemktdepthl2]

        //! [updatenewsbulletin]
        public virtual void updateNewsBulletin(int msgId, int msgType, String message, String origExchange)
        {
            Console.WriteLine("News Bulletins. "+msgId+" - Type: "+msgType+", Message: "+message+", Exchange of Origin: "+origExchange+"\n");
        }
        //! [updatenewsbulletin]

        //! [position]
        public virtual void position(string account, Contract contract, decimal pos, double avgCost)
        {
            Console.WriteLine("Position. " + account + " - Symbol: " + contract.Symbol + ", SecType: " + contract.SecType + ", Currency: " + contract.Currency + 
                ", Position: " + Util.DecimalMaxString(pos) + ", Avg cost: " + Util.DoubleMaxString(avgCost));
        }
        //! [position]

        //! [positionend]
        public virtual void positionEnd()
        {
            Console.WriteLine("PositionEnd \n");
        }
        //! [positionend]

        //! [realtimebar]
        public virtual void realtimeBar(int reqId, long time, double open, double high, double low, double close, decimal volume, decimal WAP, int count)
        {
            Console.WriteLine("RealTimeBars. " + reqId + " - Time: " + Util.LongMaxString(time) + ", Open: " + Util.DoubleMaxString(open) + ", High: " + Util.DoubleMaxString(high) + 
                ", Low: " + Util.DoubleMaxString(low) + ", Close: " + Util.DoubleMaxString(close) + ", Volume: " + Util.DecimalMaxString(volume) + ", Count: " + Util.IntMaxString(count) + 
                ", WAP: " + Util.DecimalMaxString(WAP));
        }
        //! [realtimebar]

        //! [scannerparameters]
        public virtual void scannerParameters(string xml)
        {
            Console.WriteLine("ScannerParameters. "+xml+"\n");
        }
        //! [scannerparameters]

        //! [scannerdata]
        public virtual void scannerData(int reqId, int rank, ContractDetails contractDetails, string distance, string benchmark, string projection, string legsStr)
        {
            Console.WriteLine("ScannerData. " + reqId + " - Rank: " + rank + ", Symbol: " + contractDetails.Contract.Symbol + ", SecType: " + contractDetails.Contract.SecType + ", Currency: "+contractDetails.Contract.Currency
                + ", MarketName: " + contractDetails.MarketName + ", Distance: " + distance + ", Benchmark: " + benchmark + ", Projection: " + projection + ", Legs String: " + legsStr);
        }
        //! [scannerdata]

        //! [scannerdataend]
        public virtual void scannerDataEnd(int reqId)
        {
            Console.WriteLine("ScannerDataEnd. "+reqId);
        }
        //! [scannerdataend]

        //! [receivefa]
        public virtual void receiveFA(int faDataType, string faXmlData)
        {
            Console.WriteLine("Receing FA: "+faDataType+" - "+faXmlData);
        }
        //! [receivefa]

        public virtual void bondContractDetails(int requestId, ContractDetails contractDetails)
        {
            Console.WriteLine("BondContractDetails begin. ReqId: " + requestId);
            printBondContractDetailsMsg(contractDetails);
            Console.WriteLine("BondContractDetails end. ReqId: " + requestId);
        }

        //! [historicaldataend]
        public virtual void historicalDataEnd(int reqId, string startDate, string endDate)
        {
            Console.WriteLine("HistoricalDataEnd - "+reqId+" from "+startDate+" to "+endDate);
        }
        //! [historicaldataend]

        public virtual void verifyMessageAPI(string apiData)
        {
            Console.WriteLine("verifyMessageAPI: " + apiData);
        }
        public virtual void verifyCompleted(bool isSuccessful, string errorText)
        {
            Console.WriteLine("verifyCompleted. IsSuccessful: " + isSuccessful + " - Error: " + errorText);
        }
        public virtual void verifyAndAuthMessageAPI(string apiData, string xyzChallenge)
        {
            Console.WriteLine("verifyAndAuthMessageAPI: " + apiData + " " + xyzChallenge);
        }
        public virtual void verifyAndAuthCompleted(bool isSuccessful, string errorText)
        {
            Console.WriteLine("verifyAndAuthCompleted. IsSuccessful: " + isSuccessful + " - Error: " + errorText);
        }
        //! [displaygrouplist]
        public virtual void displayGroupList(int reqId, string groups)
        {
            Console.WriteLine("DisplayGroupList. Request: " + reqId + ", Groups" + groups);
        }
        //! [displaygrouplist]

        //! [displaygroupupdated]
        public virtual void displayGroupUpdated(int reqId, string contractInfo)
        {
            Console.WriteLine("displayGroupUpdated. Request: " + reqId + ", ContractInfo: " + contractInfo);
        }
        //! [displaygroupupdated]

        //! [positionmulti]
        public virtual void positionMulti(int reqId, string account, string modelCode, Contract contract, decimal pos, double avgCost)
        {
            Console.WriteLine("Position Multi. Request: " + reqId + ", Account: " + account + ", ModelCode: " + modelCode + ", Symbol: " + contract.Symbol + ", SecType: " + contract.SecType + 
                ", Currency: " + contract.Currency + ", Position: " + Util.DecimalMaxString(pos) + ", Avg cost: " + Util.DoubleMaxString(avgCost) + "\n");
        }
        //! [positionmulti]

        //! [positionmultiend]
        public virtual void positionMultiEnd(int reqId)
        {
            Console.WriteLine("Position Multi End. Request: " + reqId + "\n");
        }
        //! [positionmultiend]

        //! [accountupdatemulti]
        public virtual void accountUpdateMulti(int reqId, string account, string modelCode, string key, string value, string currency)
        {
            Console.WriteLine("Account Update Multi. Request: " + reqId + ", Account: " + account + ", ModelCode: " + modelCode + ", Key: " + key + ", Value: " + value + ", Currency: " + currency + "\n");
        }
        //! [accountupdatemulti]

        //! [accountupdatemultiend]
        public virtual void accountUpdateMultiEnd(int reqId)
        {
            Console.WriteLine("Account Update Multi End. Request: " + reqId + "\n");
        }
        //! [accountupdatemultiend]

        //! [securityDefinitionOptionParameter]
        public void securityDefinitionOptionParameter(int reqId, string exchange, int underlyingConId, string tradingClass, string multiplier, HashSet<string> expirations, HashSet<double> strikes)
        {
            Console.WriteLine("Security Definition Option Parameter. Request: {0}, Exchange: {1}, Undrelying contract id: {2}, Trading class: {3}, Multiplier: {4}, Expirations: {5}, Strikes: {6}",
                              reqId, exchange, Util.IntMaxString(underlyingConId), tradingClass, multiplier, string.Join(", ", expirations), string.Join(", ", strikes));
        }
        //! [securityDefinitionOptionParameter]

        //! [securityDefinitionOptionParameterEnd]
        public void securityDefinitionOptionParameterEnd(int reqId)
        {
            Console.WriteLine("Security Definition Option Parameter End. Request: " + reqId + "\n");
        }
        //! [securityDefinitionOptionParameterEnd]

        //! [connectack]
        public void connectAck()
        {
            if (ClientSocket.AsyncEConnect)
                ClientSocket.startApi();
        }
        //! [connectack]

        //! [softDollarTiers]
        public void softDollarTiers(int reqId, SoftDollarTier[] tiers)
        {
            Console.WriteLine("Soft Dollar Tiers:");

            foreach (var tier in tiers)
            {
                printSoftDollarTier(tier);
            }
        }
        //! [softDollarTiers]

        //! [familyCodes]
        public void familyCodes(FamilyCode[] familyCodes)
        {
            Console.WriteLine("Family Codes:");

            foreach (var familyCode in familyCodes)
            {
                Console.WriteLine("Account ID: {0}, Family Code Str: {1}", familyCode.AccountID, familyCode.FamilyCodeStr);
            }
        }
        //! [familyCodes]

        //! [symbolSamples]
        public void symbolSamples(int reqId, ContractDescription[] contractDescriptions) 
        {
            string derivSecTypes;
            Console.WriteLine("Symbol Samples. Request Id: {0}", reqId);

            foreach (var contractDescription in contractDescriptions)
            {
                derivSecTypes = "";
                foreach (var derivSecType in contractDescription.DerivativeSecTypes)
                {
                    derivSecTypes += derivSecType;
                    derivSecTypes += " ";
                }
                Console.WriteLine("Contract: conId - {0}, symbol - {1}, secType - {2}, primExchange - {3}, currency - {4}, derivativeSecTypes - {5}, description - {6}, issuerId - {7}", 
                    contractDescription.Contract.ConId, contractDescription.Contract.Symbol, contractDescription.Contract.SecType, 
                    contractDescription.Contract.PrimaryExch, contractDescription.Contract.Currency, derivSecTypes, contractDescription.Contract.Description, contractDescription.Contract.IssuerId);
            }
        }
        //! [symbolSamples]

        //! [mktDepthExchanges]
        public void mktDepthExchanges(DepthMktDataDescription[] depthMktDataDescriptions)
        {
            Console.WriteLine("Market Depth Exchanges:");

            foreach (var depthMktDataDescription in depthMktDataDescriptions)
            {
                Console.WriteLine("Depth Market Data Description: Exchange: {0}, Security Type: {1}, Listing Exch: {2}, Service Data Type: {3}, Agg Group: {4}", 
                    depthMktDataDescription.Exchange, depthMktDataDescription.SecType, 
                    depthMktDataDescription.ListingExch, depthMktDataDescription.ServiceDataType,
                    Util.IntMaxString(depthMktDataDescription.AggGroup));
            }
        }
        //! [mktDepthExchanges]

        //! [tickNews]
        public void tickNews(int tickerId, long timeStamp, string providerCode, string articleId, string headline, string extraData)
        {
            Console.WriteLine("Tick News. Ticker Id: {0}, Time Stamp: {1}, Provider Code: {2}, Article Id: {3}, headline: {4}, extraData: {5}", tickerId, Util.LongMaxString(timeStamp), providerCode, articleId, headline, extraData);
        }
        //! [tickNews]

        //! [smartcomponents]
        public void smartComponents(int reqId, Dictionary<int, KeyValuePair<string, char>> theMap)
        {
            StringBuilder sb = new StringBuilder();

            sb.AppendFormat("==== Smart Components Begin (total={0}) reqId = {1} ====\n", theMap.Count, reqId);

            foreach (var item in theMap)
            {
                sb.AppendFormat("bit number: {0}, exchange: {1}, exchange letter: {2}\n", item.Key, item.Value.Key, item.Value.Value);
            }

            sb.AppendFormat("==== Smart Components Begin (total={0}) reqId = {1} ====\n", theMap.Count, reqId);

            Console.WriteLine(sb);
        }
        //! [smartcomponents]

        //! [tickReqParams]
        public void tickReqParams(int tickerId, double minTick, string bboExchange, int snapshotPermissions) { }
        //! [tickReqParams]

        //! [newsProviders]
        public void newsProviders(NewsProvider[] newsProviders)
        {
            Console.WriteLine("News Providers:");

            foreach (var newsProvider in newsProviders)
            {
                Console.WriteLine("News provider: providerCode - {0}, providerName - {1}",
                    newsProvider.ProviderCode, newsProvider.ProviderName);
            }
        }
        //! [newsProviders]

        //! [newsArticle]
        public void newsArticle(int requestId, int articleType, string articleText)
        {
            Console.WriteLine("News Article. Request Id: {0}, ArticleType: {1}", requestId, articleType);
            if (articleType == 0) {
                Console.WriteLine("News Article Text: {0}", articleText);
            }
            else if (articleType == 1) {
                Console.WriteLine("News Article Text: article text is binary/pdf and cannot be displayed");
            }
        }
        //! [newsArticle]
        
        public void historicalNews(int requestId, string time, string providerCode, string articleId, string headline) {}
        public void historicalNewsEnd(int requestId, bool hasMore) {}

        //! [headTimestamp]
        public void headTimestamp(int reqId, string headTimestamp)
        {
            Console.WriteLine("Head time stamp. Request Id: {0}, Head time stamp: {1}", reqId, headTimestamp);
        }
        //! [headTimestamp]

        //! [histogramData]
        public void histogramData(int reqId, HistogramEntry[] data)
        {
            Console.WriteLine("Histogram data. Request Id: {0}, data size: {1}", reqId, data.Length);
            data.ToList().ForEach(i => Console.WriteLine("\tPrice: {0}, Size: {1}", Util.DoubleMaxString(i.Price), Util.DecimalMaxString(i.Size)));
        }
        //! [histogramData]

        //! [historicalDataUpdate]
        public void historicalDataUpdate(int reqId, Bar bar)
        {
            Console.WriteLine("HistoricalDataUpdate. " + reqId + " - Time: " + bar.Time + ", Open: " + Util.DoubleMaxString(bar.Open) + ", High: " + Util.DoubleMaxString(bar.High) + 
                ", Low: " + Util.DoubleMaxString(bar.Low) + ", Close: " + Util.DoubleMaxString(bar.Close) + ", Volume: " + Util.DecimalMaxString(bar.Volume) + 
                ", Count: " + Util.IntMaxString(bar.Count) + ", WAP: " + Util.DecimalMaxString(bar.WAP));
        }
        //! [historicalDataUpdate]

        //! [rerouteMktDataReq]
        public void rerouteMktDataReq(int reqId, int conId, string exchange)
        {
            Console.WriteLine("Re-route market data request. Req Id: {0}, ConId: {1}, Exchange: {2}", reqId, conId, exchange);
        }
        //! [rerouteMktDataReq]

        //! [rerouteMktDepthReq]
        public void rerouteMktDepthReq(int reqId, int conId, string exchange)
        {
            Console.WriteLine("Re-route market depth request. Req Id: {0}, ConId: {1}, Exchange: {2}", reqId, conId, exchange);
        }
        //! [rerouteMktDepthReq]

        //! [marketRule]
        public void marketRule(int marketRuleId, PriceIncrement[] priceIncrements) 
        {
            Console.WriteLine("Market Rule Id: " + marketRuleId);
            foreach (var priceIncrement in priceIncrements) 
            {
                Console.WriteLine("Low Edge: {0}, Increment: {1}", Util.DoubleMaxString(priceIncrement.LowEdge), Util.DoubleMaxString(priceIncrement.Increment));
            }
        }
        //! [marketRule]

		//! [pnl]
        public void pnl(int reqId, double dailyPnL, double unrealizedPnL, double realizedPnL)
        {
            Console.WriteLine("PnL. Request Id: {0}, Daily PnL: {1}, Unrealized PnL: {2}, Realized PnL: {3}", reqId, Util.DoubleMaxString(dailyPnL), Util.DoubleMaxString(unrealizedPnL), Util.DoubleMaxString(realizedPnL));
        }
		//! [pnl]

		//! [pnlsingle]
        public void pnlSingle(int reqId, decimal pos, double dailyPnL, double unrealizedPnL, double realizedPnL, double value)
        {
            Console.WriteLine("PnL Single. Request Id: {0}, Pos {1}, Daily PnL {2}, Unrealized PnL {3}, Realized PnL: {4}, Value: {5}", reqId, Util.DecimalMaxString(pos), Util.DoubleMaxString(dailyPnL), Util.DoubleMaxString(unrealizedPnL),
                Util.DoubleMaxString(realizedPnL), Util.DoubleMaxString(value));
        }
		//! [pnlsingle]

		//! [historicalticks]
        public void historicalTicks(int reqId, HistoricalTick[] ticks, bool done)
        {
            foreach (var tick in ticks)
            {
                Console.WriteLine("Historical Tick. Request Id: {0}, Time: {1}, Price: {2}, Size: {3}", reqId, Util.UnixSecondsToString(tick.Time, "yyyyMMdd-HH:mm:ss"), Util.DoubleMaxString(tick.Price), Util.DecimalMaxString(tick.Size));
            }
        }
		//! [historicalticks]

		//! [historicalticksbidask]
        public void historicalTicksBidAsk(int reqId, HistoricalTickBidAsk[] ticks, bool done)
        {
            foreach (var tick in ticks)
            {
                Console.WriteLine("Historical Tick Bid/Ask. Request Id: {0}, Time: {1}, Price Bid: {2}, Price Ask: {3}, Size Bid: {4}, Size Ask: {5}, Bid/Ask Tick Attribs: {6} ",
                    reqId, Util.UnixSecondsToString(tick.Time, "yyyyMMdd-HH:mm:ss"), Util.DoubleMaxString(tick.PriceBid), Util.DoubleMaxString(tick.PriceAsk), 
                    Util.DecimalMaxString(tick.SizeBid), Util.DecimalMaxString(tick.SizeAsk), tick.TickAttribBidAsk);
            }
        }
		//! [historicalticksbidask]

		//! [historicaltickslast]
        public void historicalTicksLast(int reqId, HistoricalTickLast[] ticks, bool done)
        {
            foreach (var tick in ticks)
            {
                Console.WriteLine("Historical Tick Last. Request Id: {0}, Time: {1}, Price: {2}, Size: {3}, Exchange: {4}, Special Conditions: {5}, Last Tick Attribs: {6} ",
                    reqId, Util.UnixSecondsToString(tick.Time, "yyyyMMdd-HH:mm:ss"), Util.DoubleMaxString(tick.Price), Util.DecimalMaxString(tick.Size), tick.Exchange, tick.SpecialConditions, tick.TickAttribLast);
            }
        }
		//! [historicaltickslast]

        //! [tickbytickalllast]
        public void tickByTickAllLast(int reqId, int tickType, long time, double price, decimal size, TickAttribLast tickAttribLast, string exchange, string specialConditions)
        {
            Console.WriteLine("Tick-By-Tick. Request Id: {0}, TickType: {1}, Time: {2}, Price: {3}, Size: {4}, Exchange: {5}, Special Conditions: {6}, PastLimit: {7}, Unreported: {8}",
                reqId, tickType == 1 ? "Last" : "AllLast", Util.UnixSecondsToString(time, "yyyyMMdd-HH:mm:ss"), Util.DoubleMaxString(price), Util.DecimalMaxString(size), exchange, specialConditions, tickAttribLast.PastLimit, tickAttribLast.Unreported);
        }
        //! [tickbytickalllast]

        //! [tickbytickbidask]
        public void tickByTickBidAsk(int reqId, long time, double bidPrice, double askPrice, decimal bidSize, decimal askSize, TickAttribBidAsk tickAttribBidAsk)
        {
            Console.WriteLine("Tick-By-Tick. Request Id: {0}, TickType: BidAsk, Time: {1}, BidPrice: {2}, AskPrice: {3}, BidSize: {4}, AskSize: {5}, BidPastLow: {6}, AskPastHigh: {7}",
                reqId, Util.UnixSecondsToString(time, "yyyyMMdd-HH:mm:ss"), Util.DoubleMaxString(bidPrice), Util.DoubleMaxString(askPrice), Util.DecimalMaxString(bidSize), Util.DecimalMaxString(askSize), tickAttribBidAsk.BidPastLow, tickAttribBidAsk.AskPastHigh);
        }
        //! [tickbytickbidask]

        //! [tickbytickmidpoint]
        public void tickByTickMidPoint(int reqId, long time, double midPoint)
        {
            Console.WriteLine("Tick-By-Tick. Request Id: {0}, TickType: MidPoint, Time: {1}, MidPoint: {2}",
                reqId, Util.UnixSecondsToString(time, "yyyyMMdd-HH:mm:ss"), Util.DoubleMaxString(midPoint));
        }
        //! [tickbytickmidpoint]

        //! [orderbound]
        public void orderBound(long permId, int clientId, int orderId)
        {
            Console.WriteLine("Order bound. PermId: {0}, ClientId: {1}, OrderId: {2}", Util.LongMaxString(permId), Util.IntMaxString(clientId), Util.IntMaxString(orderId));
        }
        //! [orderbound]

        public virtual void completedOrder(Contract contract, Order order, OrderState orderState) {}
        public virtual void completedOrdersEnd() {}

        //! [replacefaend]
        public virtual void replaceFAEnd(int reqId, string text)
        {
            Console.WriteLine("Replace FA End. ReqId: " + reqId + ", Text: " + text + "\n");
        }
		//! [replacefaend]

		//! [wshMetaData]
        public void wshMetaData(int reqId, string dataJson)
        {
            Console.WriteLine($"WSH Meta Data. Request Id: {reqId}, Data JSON: {dataJson}\n");
        }
		//! [wshMetaData]

		//! [wshEventData]
        public void wshEventData(int reqId, string dataJson)
        {
            Console.WriteLine($"WSH Event Data. Request Id: {reqId}, Data JSON: {dataJson}\n");
        }
        //! [wshEventData]

        //! [historicalSchedule]
        public void historicalSchedule(int reqId, string startDateTime, string endDateTime, string timeZone, HistoricalSession[] sessions)
        {
            Console.WriteLine($"Historical Schedule. ReqId: {reqId}, Start: {startDateTime}, End: {endDateTime}, Time Zone: {timeZone}");

            foreach (var session in sessions)
            {
                Console.WriteLine($"\tSession. Start: {session.StartDateTime}, End: {session.EndDateTime}, Ref Date: {session.RefDate}");
            }
        }
        //! [historicalSchedule]

        //! [userInfo]
        public void userInfo(int reqId, string whiteBrandingId)
        {
            Console.WriteLine($"User Info. ReqId: {reqId}, WhiteBrandingId: {whiteBrandingId}");
        }
        //! [userInfo]

        //! [currentTimeInMillis]
        public virtual void currentTimeInMillis(long timeInMillis)
        {
            string timeInMillisStr = Util.UnixMilliSecondsToString(timeInMillis, "MMM dd, yyyy HH:mm:ss.FFF");
            Console.WriteLine("Current Time In Millis " + timeInMillis + " : " + timeInMillisStr + "\n");
        }
        //! [currentTimeInMillis]

        /**
         * Protobuf
         */
        public virtual void orderStatusProtoBuf(IBApi.protobuf.OrderStatus orderStatusProto) {
            Util.printProtoSingleLine("Order Status: ", orderStatusProto);
        }
        public virtual void openOrderProtoBuf(IBApi.protobuf.OpenOrder openOrderProto) {
            Util.printProtoSingleLine("Open Order: ", openOrderProto);
        }
        public virtual void openOrdersEndProtoBuf(IBApi.protobuf.OpenOrdersEnd openOrdersEndProto) {
            Util.printProtoSingleLine("Open Orders End: ", openOrdersEndProto);
        }
        public virtual void errorProtoBuf(IBApi.protobuf.ErrorMessage errorMessageProto) { }
        public virtual void execDetailsProtoBuf(IBApi.protobuf.ExecutionDetails executionDetailsProto) { }
        public virtual void execDetailsEndProtoBuf(IBApi.protobuf.ExecutionDetailsEnd executionDetailsEndProto) { }
        public virtual void completedOrderProtoBuf(IBApi.protobuf.CompletedOrder completedOrderProto) {
            Util.printProtoSingleLine("Completed Order: ", completedOrderProto);
        }
        public virtual void completedOrdersEndProtoBuf(IBApi.protobuf.CompletedOrdersEnd completedOrdersEndProto) {
            Util.printProtoSingleLine("Completed Orders End: ", completedOrdersEndProto);
        }
        public virtual void orderBoundProtoBuf(IBApi.protobuf.OrderBound orderBoundProto) { }
        public virtual void contractDataProtoBuf(IBApi.protobuf.ContractData contractDataProto) { }
        public virtual void bondContractDataProtoBuf(IBApi.protobuf.ContractData contractDataProto) { }
        public virtual void contractDataEndProtoBuf(IBApi.protobuf.ContractDataEnd contractDataEndProto) { }
        public virtual void tickPriceProtoBuf(IBApi.protobuf.TickPrice tickPriceProto) { }
        public virtual void tickSizeProtoBuf(IBApi.protobuf.TickSize tickSizeProto) { }
        public virtual void tickOptionComputationProtoBuf(IBApi.protobuf.TickOptionComputation tickOptionComputationProto) { }
        public virtual void tickGenericProtoBuf(IBApi.protobuf.TickGeneric tickGenericProto) { }
        public virtual void tickStringProtoBuf(IBApi.protobuf.TickString tickStringProto) { }
        public virtual void tickSnapshotEndProtoBuf(IBApi.protobuf.TickSnapshotEnd tickSnapshotEndProto) { }
        public virtual void updateMarketDepthProtoBuf(IBApi.protobuf.MarketDepth marketDepthProto) { }
        public virtual void updateMarketDepthL2ProtoBuf(IBApi.protobuf.MarketDepthL2 marketDepthL2Proto) { }
        public virtual void marketDataTypeProtoBuf(IBApi.protobuf.MarketDataType marketDataTypeProto) { }
        public virtual void tickReqParamsProtoBuf(IBApi.protobuf.TickReqParams tickReqParamsProto) {
            StringBuilder sb = new StringBuilder();
            sb.Append("Tick Req Params. ");
            if (tickReqParamsProto.HasReqId) sb.Append("Ticker Id: ").Append(tickReqParamsProto.ReqId).Append(", ");
            if (tickReqParamsProto.HasMinTick) sb.Append("MinTick: ").Append(tickReqParamsProto.MinTick).Append(", ");
            if (tickReqParamsProto.HasBboExchange)
            {
                sb.Append("BboExchange: ").Append(tickReqParamsProto.BboExchange).Append(", ");
                BboExchange = tickReqParamsProto.BboExchange;
            }
            if (tickReqParamsProto.HasSnapshotPermissions) sb.Append("SnapshotPermissions: ").Append(tickReqParamsProto.SnapshotPermissions).Append(", ");
            if (tickReqParamsProto.HasLastPricePrecision) sb.Append("LastPricePrecision: ").Append(tickReqParamsProto.LastPricePrecision).Append(", ");
            if (tickReqParamsProto.HasLastSizePrecision) sb.Append("LastSizePrecision: ").Append(tickReqParamsProto.LastSizePrecision);
            Console.WriteLine(sb.ToString());
        }
        public virtual void updateAccountValueProtoBuf(IBApi.protobuf.AccountValue accountValueProto) { }
        public virtual void updatePortfolioProtoBuf(IBApi.protobuf.PortfolioValue portfolioValueProto) { }
        public virtual void updateAccountTimeProtoBuf(IBApi.protobuf.AccountUpdateTime accountUpdateTimeProto) { }
        public virtual void accountDataEndProtoBuf(IBApi.protobuf.AccountDataEnd accountDataEndProto) { }
        public virtual void managedAccountsProtoBuf(IBApi.protobuf.ManagedAccounts managedAccountsProto) { }
        public virtual void positionProtoBuf(IBApi.protobuf.Position positionProto) { }
        public virtual void positionEndProtoBuf(IBApi.protobuf.PositionEnd positionEndProto) { }
        public virtual void accountSummaryProtoBuf(IBApi.protobuf.AccountSummary accountSummaryProto) { }
        public virtual void accountSummaryEndProtoBuf(IBApi.protobuf.AccountSummaryEnd accountSummaryEndProto) { }
        public virtual void positionMultiProtoBuf(IBApi.protobuf.PositionMulti positionMultiProto) { }
        public virtual void positionMultiEndProtoBuf(IBApi.protobuf.PositionMultiEnd positionMultiEndProto) { }
        public virtual void accountUpdateMultiProtoBuf(IBApi.protobuf.AccountUpdateMulti accountUpdateMultiProto) { }
        public virtual void accountUpdateMultiEndProtoBuf(IBApi.protobuf.AccountUpdateMultiEnd accountUpdateMultiEndProto) { }
        public virtual void historicalDataProtoBuf(IBApi.protobuf.HistoricalData historicalDataProto) { }
        public virtual void historicalDataUpdateProtoBuf(IBApi.protobuf.HistoricalDataUpdate historicalDataUpdateProto) { }
        public virtual void historicalDataEndProtoBuf(IBApi.protobuf.HistoricalDataEnd historicalDataEndProto) { }
        public virtual void realTimeBarTickProtoBuf(IBApi.protobuf.RealTimeBarTick realTimeBarTickProto) { }
        public virtual void headTimestampProtoBuf(IBApi.protobuf.HeadTimestamp headTimestampProto) { }
        public virtual void histogramDataProtoBuf(IBApi.protobuf.HistogramData histogramDataProto) { }
        public virtual void historicalTicksProtoBuf(IBApi.protobuf.HistoricalTicks historicalTicksProto) { }
        public virtual void historicalTicksBidAskProtoBuf(IBApi.protobuf.HistoricalTicksBidAsk historicalTicksBidAskProto) { }
        public virtual void historicalTicksLastProtoBuf(IBApi.protobuf.HistoricalTicksLast historicalTicksLastProto) { }
        public virtual void tickByTickDataProtoBuf(IBApi.protobuf.TickByTickData tickByTickDataProto) { }
        public virtual void updateNewsBulletinProtoBuf(IBApi.protobuf.NewsBulletin newsBulletinProto) { }
        public virtual void newsArticleProtoBuf(IBApi.protobuf.NewsArticle newsArticleProto) { }
        public virtual void newsProvidersProtoBuf(IBApi.protobuf.NewsProviders newsProvidersProto) { }
        public virtual void historicalNewsProtoBuf(IBApi.protobuf.HistoricalNews historicalNewsProto) {
            Util.printProtoSingleLine("Historical News: ", historicalNewsProto);
        }
        public virtual void historicalNewsEndProtoBuf(IBApi.protobuf.HistoricalNewsEnd historicalNewsEndProto) {
            Util.printProtoSingleLine("Historical News End: ", historicalNewsEndProto);
        }
        public virtual void wshMetaDataProtoBuf(IBApi.protobuf.WshMetaData wshMetaDataProto) { }
        public virtual void wshEventDataProtoBuf(IBApi.protobuf.WshEventData wshEventDataProto) { }
        public virtual void tickNewsProtoBuf(IBApi.protobuf.TickNews tickNewsProto) { }
        public virtual void scannerParametersProtoBuf(IBApi.protobuf.ScannerParameters scannerParametersProto) { }
        public virtual void scannerDataProtoBuf(IBApi.protobuf.ScannerData scannerDataProto) { }
        public virtual void fundamentalsDataProtoBuf(IBApi.protobuf.FundamentalsData fundamentalsDataProto) { }
        public virtual void pnlProtoBuf(IBApi.protobuf.PnL pnlProto) { }
        public virtual void pnlSingleProtoBuf(IBApi.protobuf.PnLSingle pnlSingleProto) { }
        public virtual void receiveFAProtoBuf(IBApi.protobuf.ReceiveFA receiveFAProto) { }
        public virtual void replaceFAEndProtoBuf(IBApi.protobuf.ReplaceFAEnd replaceFAEndProto) { }
        public virtual void commissionAndFeesReportProtoBuf(IBApi.protobuf.CommissionAndFeesReport commissionAndFeesReportProto) { }
        public virtual void historicalScheduleProtoBuf(IBApi.protobuf.HistoricalSchedule historicalScheduleProto) { }
        public virtual void rerouteMarketDataRequestProtoBuf(IBApi.protobuf.RerouteMarketDataRequest rerouteMarketDataRequestProto) { }
        public virtual void rerouteMarketDepthRequestProtoBuf(IBApi.protobuf.RerouteMarketDepthRequest rerouteMarketDepthRequestProto) { }
        public virtual void secDefOptParameterProtoBuf(IBApi.protobuf.SecDefOptParameter secDefOptParameterProto) { }
        public virtual void secDefOptParameterEndProtoBuf(IBApi.protobuf.SecDefOptParameterEnd secDefOptParameterEndProto) { }
        public virtual void softDollarTiersProtoBuf(IBApi.protobuf.SoftDollarTiers softDollarTiersProto) { }
        public virtual void familyCodesProtoBuf(IBApi.protobuf.FamilyCodes familyCodesProto) { }
        public virtual void symbolSamplesProtoBuf(IBApi.protobuf.SymbolSamples symbolSamplesProto) { }
        public virtual void smartComponentsProtoBuf(IBApi.protobuf.SmartComponents smartComponentsProto) { }
        public virtual void marketRuleProtoBuf(IBApi.protobuf.MarketRule marketRuleProto) { }
        public virtual void userInfoProtoBuf(IBApi.protobuf.UserInfo userInfoProto) { }
        public virtual void nextValidIdProtoBuf(IBApi.protobuf.NextValidId nextValidIdProto) { }
        public virtual void currentTimeProtoBuf(IBApi.protobuf.CurrentTime currentTimeProto) { }
        public virtual void currentTimeInMillisProtoBuf(IBApi.protobuf.CurrentTimeInMillis currentTimeInMillisProto) { }
        public virtual void verifyMessageApiProtoBuf(IBApi.protobuf.VerifyMessageApi verifyMessageApiProto) { }
        public virtual void verifyCompletedProtoBuf(IBApi.protobuf.VerifyCompleted verifyCompletedProto) { }
        public virtual void displayGroupListProtoBuf(IBApi.protobuf.DisplayGroupList displayGroupListProto) { }
        public virtual void displayGroupUpdatedProtoBuf(IBApi.protobuf.DisplayGroupUpdated displayGroupUpdatedProto) { }
        public virtual void marketDepthExchangesProtoBuf(IBApi.protobuf.MarketDepthExchanges marketDepthExchangesProto) { }
        public virtual void configResponseProtoBuf(IBApi.protobuf.ConfigResponse configResponseProto)
        {
            Console.WriteLine("==== Config Response Begin ====");
            var formatter = new JsonFormatter(JsonFormatter.Settings.Default.WithIndentation());
            Console.WriteLine(formatter.Format(configResponseProto));
            Console.WriteLine("==== Config Response End ====");
        }

        public virtual void updateConfigResponseProtoBuf(IBApi.protobuf.UpdateConfigResponse updateConfigResponseProto)
        {
            Console.WriteLine("==== Update Config Response Begin ====");
            var formatter = new JsonFormatter(JsonFormatter.Settings.Default.WithIndentation());
            Console.WriteLine(formatter.Format(updateConfigResponseProto));
            Console.WriteLine("==== Update Config Response End ====");
        }
    }
}
