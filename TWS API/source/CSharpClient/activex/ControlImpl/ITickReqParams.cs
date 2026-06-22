/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System;
using System.Runtime.InteropServices;

namespace TWSLib
{
    [ComVisible(true), Guid("47EAFA96-4A30-40D4-9143-CCE72479FF3A")]
    public interface ITickReqParams
    {
        [DispId(1)]
        int reqId { get; }
        [DispId(2)]
        string minTick { get; }
        [DispId(3)]
        string bboExchange { get; }
        [DispId(4)]
        int snapshotPermissions { get; }
        [DispId(5)]
        object lastPricePrecision { get; }
        [DispId(6)]
        object lastSizePrecision { get; }
    }
}
