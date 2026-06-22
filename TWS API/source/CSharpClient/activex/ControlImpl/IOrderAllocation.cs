/* Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

namespace TWSLib
{
    [Guid("F87F8EF1-C1AD-40EB-BB8E-53B3DD8E6A24"), ComVisible(true)]
    public interface IOrderAllocation
    {
        [DispId(1)] string account { get; set; }
        [DispId(2)] object position { get; set; }
        [DispId(3)] object positionDesired { get; set; }
        [DispId(4)] object positionAfter { get; set; }
        [DispId(5)] object desiredAllocQty { get; set; }
        [DispId(6)] object allowedAllocQty { get; set; }
        [DispId(7)] bool isMonetary { get; set; }
    }
}
