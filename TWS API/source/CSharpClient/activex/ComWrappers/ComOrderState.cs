/* Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using IBApi;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

namespace TWSLib
{
    /**
     * @class OrderState
     * @brief Provides an active order's current state
     * @sa Order
     */
    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public class ComOrderState : ComWrapper<OrderState>, IOrderState
    {
        /**
         * @brief The order's current status
         */
        public string Status
        {
            get { return data !=null ? data.Status : default(string); }
            set { if (data != null) data.Status = value; }
        }

        /**
         * @brief The account's current initial margin.
         */
        public string InitMarginBefore
        {
            get { return data !=null ? data.InitMarginBefore : default(string); }
            set { if (data != null) data.InitMarginBefore = value; }
        }

        /**
        * @brief The account's current maintenance margin
        */
        public string MaintMarginBefore
        {
            get { return data !=null ? data.MaintMarginBefore : default(string); }
            set { if (data != null) data.MaintMarginBefore = value; }
        }

        /**
        * @brief The account's current equity with loan
        */
        public string EquityWithLoanBefore
        {
            get { return data !=null ? data.EquityWithLoanBefore : default(string); }
            set { if (data != null) data.EquityWithLoanBefore = value; }
        }

        /**
         * @brief The change of the account's initial margin.
         */
        public string InitMarginChange
        {
            get { return data != null ? data.InitMarginChange : default(string); }
            set { if (data != null) data.InitMarginChange = value; }
        }

        /**
        * @brief The change of the account's maintenance margin
        */
        public string MaintMarginChange
        {
            get { return data != null ? data.MaintMarginChange : default(string); }
            set { if (data != null) data.MaintMarginChange = value; }
        }

        /**
        * @brief The change of the account's equity with loan
        */
        public string EquityWithLoanChange
        {
            get { return data != null ? data.EquityWithLoanChange : default(string); }
            set { if (data != null) data.EquityWithLoanChange = value; }
        }

        /**
         * @brief The order's impact on the account's initial margin.
         */
        public string InitMarginAfter
        {
            get { return data != null ? data.InitMarginAfter : default(string); }
            set { if (data != null) data.InitMarginAfter = value; }
        }

        /**
        * @brief The order's impact on the account's maintenance margin
        */
        public string MaintMarginAfter
        {
            get { return data != null ? data.MaintMarginAfter : default(string); }
            set { if (data != null) data.MaintMarginAfter = value; }
        }

        /**
        * @brief Shows the impact the order would have on the account's equity with loan
        */
        public string EquityWithLoanAfter
        {
            get { return data != null ? data.EquityWithLoanAfter : default(string); }
            set { if (data != null) data.EquityWithLoanAfter = value; }
        }

        /**
          * @brief The order's generated commission and fees.
          */
        public double CommissionAndFees
        {
            get { return data !=null ? data.CommissionAndFees : default(double); }
            set { if (data != null) data.CommissionAndFees = value; }
        }

        /**
        * @brief The execution's minimum commission and fees.
        */
        public double MinCommissionAndFees
        {
            get { return data !=null ? data.MinCommissionAndFees : default(double); }
            set { if (data != null) data.MinCommissionAndFees = value; }
        }

        /**
        * @brief The executions maximum commission and fees.
        */
        public double MaxCommissionAndFees
        {
            get { return data !=null ? data.MaxCommissionAndFees : default(double); }
            set { if (data != null) data.MaxCommissionAndFees = value; }
        }

        /**
         * @brief The generated commission and fees currency
         * @sa CommissionAndFeesReport
         */
        public string CommissionAndFeesCurrency
        {
            get { return data !=null ? data.CommissionAndFeesCurrency : default(string); }
            set { if (data != null) data.CommissionAndFeesCurrency = value; }
        }

        /**
         * @brief If the order is warranted, a descriptive message will be provided.
         */
        public string WarningText
        {
            get { return data !=null ? data.WarningText : default(string); }
            set { if (data != null) data.WarningText = value; }
        }

        /**
         * @brief Completed time for completed order.
         */
        public string CompletedTime
        {
            get { return data != null ? data.CompletedTime : default(string); }
            set { if (data != null) data.CompletedTime = value; }
        }

        /**
         * @brief Completed status for completed order.
         */
        public string CompletedStatus
        {
            get { return data != null ? data.CompletedStatus : default(string); }
            set { if (data != null) data.CompletedStatus = value; }
        }

        /**
         * @brief Margin currency
         */
        public string MarginCurrency
        {
            get { return data != null ? data.MarginCurrency : default(string); }
            set { if (data != null) data.MarginCurrency = value; }
        }

        /**
         * @brief The account's current initial margin outside RTH
         */
        public double InitMarginBeforeOutsideRTH
        {
            get { return data != null ? data.InitMarginBeforeOutsideRTH : default(double); }
            set { if (data != null) data.InitMarginBeforeOutsideRTH = value; }
        }

        /**
        * @brief The account's current maintenance margin outside RTH
        */
        public double MaintMarginBeforeOutsideRTH
        {
            get { return data != null ? data.MaintMarginBeforeOutsideRTH : default(double); }
            set { if (data != null) data.MaintMarginBeforeOutsideRTH = value; }
        }

        /**
        * @brief The account's current equity with loan outside RTH
        */
        public double EquityWithLoanBeforeOutsideRTH
        {
            get { return data != null ? data.EquityWithLoanBeforeOutsideRTH : default(double); }
            set { if (data != null) data.EquityWithLoanBeforeOutsideRTH = value; }
        }

        /**
         * @brief The change of the account's initial margin outside RTH
         */
        public double InitMarginChangeOutsideRTH
        {
            get { return data != null ? data.InitMarginChangeOutsideRTH : default(double); }
            set { if (data != null) data.InitMarginChangeOutsideRTH = value; }
        }

        /**
        * @brief The change of the account's maintenance margin outside RTH
        */
        public double MaintMarginChangeOutsideRTH
        {
            get { return data != null ? data.MaintMarginChangeOutsideRTH : default(double); }
            set { if (data != null) data.MaintMarginChangeOutsideRTH = value; }
        }

        /**
        * @brief The change of the account's equity with loan outside RTH
        */
        public double EquityWithLoanChangeOutsideRTH
        {
            get { return data != null ? data.EquityWithLoanChangeOutsideRTH : default(double); }
            set { if (data != null) data.EquityWithLoanChangeOutsideRTH = value; }
        }

        /**
         * @brief The order's impact on the account's initial margin outside RTH
         */
        public double InitMarginAfterOutsideRTH
        {
            get { return data != null ? data.InitMarginAfterOutsideRTH : default(double); }
            set { if (data != null) data.InitMarginAfterOutsideRTH = value; }
        }

        /**
        * @brief The order's impact on the account's maintenance margin outside RTH
        */
        public double MaintMarginAfterOutsideRTH
        {
            get { return data != null ? data.MaintMarginAfterOutsideRTH : default(double); }
            set { if (data != null) data.MaintMarginAfterOutsideRTH = value; }
        }

        /**
        * @brief Shows the impact the order would have on the account's equity with loan outside RTH
        */
        public double EquityWithLoanAfterOutsideRTH
        {
            get { return data != null ? data.EquityWithLoanAfterOutsideRTH : default(double); }
            set { if (data != null) data.EquityWithLoanAfterOutsideRTH = value; }
        }

        /**
        * @brief Suggested size
        */
        public object SuggestedSize
        {
            get { return data != null ? data.SuggestedSize : default(object); }
            set { if (data != null) data.SuggestedSize = Util.GetDecimal(value); }
        }

        /**
        * @brief Reject reason
        */
        public string RejectReason
        {
            get { return data != null ? data.RejectReason : default(string); }
            set { if (data != null) data.RejectReason = value; }
        }

        object TWSLib.IOrderState.orderAllocations
        {
            get
            {
                return data.OrderAllocations != null ? new TWSLib.ComOrderAllocationList(new ComList<ComOrderAllocation, OrderAllocation>(data.OrderAllocations)) : null;
            }

            set
            {
                data.OrderAllocations = value != null ? (value as TWSLib.ComOrderAllocationList) : null;
            }
        }

        public override bool Equals(Object other)
        {

            if (this == other)
                return true;

            if (other == null)
                return false;

            OrderState state = (OrderState)other;

            if (CommissionAndFees != state.CommissionAndFees ||
                MinCommissionAndFees != state.MinCommissionAndFees ||
                MaxCommissionAndFees != state.MaxCommissionAndFees)
            {
                return false;
            }

            if (Util.StringCompare(Status, state.Status) != 0 ||
                Util.StringCompare(InitMarginBefore, state.InitMarginBefore) != 0 ||
                Util.StringCompare(MaintMarginBefore, state.MaintMarginBefore) != 0 ||
                Util.StringCompare(EquityWithLoanBefore, state.EquityWithLoanBefore) != 0 ||
                Util.StringCompare(InitMarginChange, state.InitMarginChange) != 0 ||
                Util.StringCompare(MaintMarginChange, state.MaintMarginChange) != 0 ||
                Util.StringCompare(EquityWithLoanChange, state.EquityWithLoanChange) != 0 ||
                Util.StringCompare(InitMarginAfter, state.InitMarginAfter) != 0 ||
                Util.StringCompare(MaintMarginAfter, state.MaintMarginAfter) != 0 ||
                Util.StringCompare(EquityWithLoanAfter, state.EquityWithLoanAfter) != 0 ||
                Util.StringCompare(CommissionAndFeesCurrency, state.CommissionAndFeesCurrency) != 0 ||
                Util.StringCompare(CompletedTime, state.CompletedTime) != 0 ||
                Util.StringCompare(CompletedStatus, state.CompletedStatus) != 0)
            {
                return false;
            }

            return true;
        }

        string TWSLib.IOrderState.status
        {
            get { return Status; }
        }

        string TWSLib.IOrderState.initMarginBefore
        {
            get { return InitMarginBefore; }
        }

        string TWSLib.IOrderState.maintMarginBefore
        {
            get { return MaintMarginBefore; }
        }

        string TWSLib.IOrderState.equityWithLoanBefore
        {
            get { return EquityWithLoanBefore; }
        }

        string TWSLib.IOrderState.initMarginChange
        {
            get { return InitMarginChange; }
        }

        string TWSLib.IOrderState.maintMarginChange
        {
            get { return MaintMarginChange; }
        }

        string TWSLib.IOrderState.equityWithLoanChange
        {
            get { return EquityWithLoanChange; }
        }

        string TWSLib.IOrderState.initMarginAfter
        {
            get { return InitMarginAfter; }
        }

        string TWSLib.IOrderState.maintMarginAfter
        {
            get { return MaintMarginAfter; }
        }

        string TWSLib.IOrderState.equityWithLoanAfter
        {
            get { return EquityWithLoanAfter; }
        }

        double TWSLib.IOrderState.commissionAndFees
        {
            get { return CommissionAndFees; }
        }

        double TWSLib.IOrderState.minCommissionAndFees
        {
            get { return MinCommissionAndFees; }
        }

        double TWSLib.IOrderState.maxCommissionAndFees
        {
            get { return MaxCommissionAndFees; }
        }

        string TWSLib.IOrderState.commissionAndFeesCurrency
        {
            get { return CommissionAndFeesCurrency; }
        }

        string TWSLib.IOrderState.marginCurrency
        {
            get { return MarginCurrency; }
        }

        double TWSLib.IOrderState.initMarginBeforeOutsideRTH
        {
            get { return InitMarginBeforeOutsideRTH; }
        }

        double TWSLib.IOrderState.maintMarginBeforeOutsideRTH
        {
            get { return MaintMarginBeforeOutsideRTH; }
        }

        double TWSLib.IOrderState.equityWithLoanBeforeOutsideRTH
        {
            get { return EquityWithLoanBeforeOutsideRTH; }
        }

        double TWSLib.IOrderState.initMarginChangeOutsideRTH
        {
            get { return InitMarginChangeOutsideRTH; }
        }

        double TWSLib.IOrderState.maintMarginChangeOutsideRTH
        {
            get { return MaintMarginChangeOutsideRTH; }
        }

        double TWSLib.IOrderState.equityWithLoanChangeOutsideRTH
        {
            get { return EquityWithLoanChangeOutsideRTH; }
        }

        double TWSLib.IOrderState.initMarginAfterOutsideRTH
        {
            get { return InitMarginAfterOutsideRTH; }
        }

        double TWSLib.IOrderState.maintMarginAfterOutsideRTH
        {
            get { return MaintMarginAfterOutsideRTH; }
        }

        double TWSLib.IOrderState.equityWithLoanAfterOutsideRTH
        {
            get { return EquityWithLoanAfterOutsideRTH; }
        }

        object TWSLib.IOrderState.suggestedSize
        {
            get { return SuggestedSize; }
        }

        string TWSLib.IOrderState.rejectReason
        {
            get { return RejectReason; }
        }

        string TWSLib.IOrderState.warningText
        {
            get { return WarningText; }
        }

        string TWSLib.IOrderState.completedTime
        {
            get { return CompletedTime; }
        }

        string TWSLib.IOrderState.completedStatus
        {
            get { return CompletedStatus; }
        }

        public static explicit operator OrderState(ComOrderState cos)
        {
            return cos.ConvertTo();
        }

        public static explicit operator ComOrderState(OrderState os)
        {
            return new ComOrderState().ConvertFrom(os) as ComOrderState;
        }
    }
}
