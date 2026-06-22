/* Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace TWSLib
{
    [ComVisible(true), Guid("CE9A0E06-FA06-4702-8981-099E953D60F3")]
    public interface ICommissionAndFeesReport
    {
        [DispId(1)]
        string execId { get; }
        [DispId(2)]
        double commissionAndFees { get; }
        [DispId(3)]
        string currency { get; }
        [DispId(4)]
        double realizedPNL { get; }
        [DispId(5)]
        double yield { get; }
        [DispId(6)]
        int yieldRedemptionDate { get; }
    }
}
