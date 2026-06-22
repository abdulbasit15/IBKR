/* Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using IBApi;
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace TWSLib
{
    [ComVisible(true), Guid("7B33AE1F-99B0-4BCB-A024-42335897A6AF")]
    public interface IOrderState
    {
		[DispId(1)] string status{ get; }
		[DispId(2)] string initMarginAfter{ get; }
		[DispId(3)] string maintMarginAfter{ get; }
		[DispId(4)] string equityWithLoanAfter{ get; }
		[DispId(5)] double commissionAndFees { get; }
		[DispId(6)] double minCommissionAndFees { get; }
		[DispId(7)] double maxCommissionAndFees { get; }
		[DispId(8)] string commissionAndFeesCurrency { get; }
		[DispId(9)] string warningText{ get; }
		[DispId(10)] string initMarginBefore { get; }
		[DispId(11)] string maintMarginBefore { get; }
		[DispId(12)] string equityWithLoanBefore { get; }
		[DispId(13)] string initMarginChange { get; }
		[DispId(14)] string maintMarginChange { get; }
		[DispId(15)] string equityWithLoanChange { get; }
        [DispId(16)] string completedTime { get; }
        [DispId(17)] string completedStatus { get; }
        [DispId(18)] string marginCurrency { get; }
        [DispId(19)] double initMarginBeforeOutsideRTH { get; }
        [DispId(20)] double maintMarginBeforeOutsideRTH { get; }
        [DispId(21)] double equityWithLoanBeforeOutsideRTH { get; }
        [DispId(22)] double initMarginChangeOutsideRTH { get; }
        [DispId(23)] double maintMarginChangeOutsideRTH { get; }
        [DispId(24)] double equityWithLoanChangeOutsideRTH { get; }
        [DispId(25)] double initMarginAfterOutsideRTH { get; }
        [DispId(26)] double maintMarginAfterOutsideRTH { get; }
        [DispId(27)] double equityWithLoanAfterOutsideRTH { get; }
        [DispId(28)] object suggestedSize { get; }
        [DispId(29)] string rejectReason { get; }
        [DispId(30)] object orderAllocations { [return: MarshalAs(UnmanagedType.IDispatch)] get; [param: MarshalAs(UnmanagedType.IDispatch)] set; }
    };
}
