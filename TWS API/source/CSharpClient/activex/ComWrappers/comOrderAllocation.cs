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
     * @class OrderAllocation
     * @brief order allocation
     * @sa OrderState
     */
    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public class ComOrderAllocation : ComWrapper<OrderAllocation>, IOrderAllocation
    {
        public string Account
        {
            get { return data != null ? data.Account : default(string); }
            set { if (data != null) data.Account = value; }
        }

        public object Position
        {
            get { return data != null ? data.Position : default(object); }
            set { if (data != null) data.Position = Util.GetDecimal(value); }
        }

        public object PositionDesired
        {
            get { return data != null ? data.PositionDesired : default(object); }
            set { if (data != null) data.PositionDesired = Util.GetDecimal(value); }
        }

        public object PositionAfter
        {
            get { return data != null ? data.PositionAfter : default(object); }
            set { if (data != null) data.PositionAfter = Util.GetDecimal(value); }
        }

        public object DesiredAllocQty
        {
            get { return data != null ? data.DesiredAllocQty : default(object); }
            set { if (data != null) data.DesiredAllocQty = Util.GetDecimal(value); }
        }

        public object AllowedAllocQty
        {
            get { return data != null ? data.AllowedAllocQty : default(object); }
            set { if (data != null) data.AllowedAllocQty = Util.GetDecimal(value); }
        }

        public bool IsMonetary
        {
            get { return data != null ? data.IsMonetary : default(bool); }
            set { if (data != null) data.IsMonetary = value; }
        }

        public override bool Equals(Object other)
        {
            if (this == other)
            {
                return true;
            }
            else if (other == null)
            {
                return false;
            }

            OrderAllocation theOther = (OrderAllocation)other;

            if (String.Compare(Account, theOther.Account, true) != 0)
            {
                return false;
            }

            return true;
        }

        string IOrderAllocation.account { get { return this.Account; } set { this.Account = value; } }
        object IOrderAllocation.position { get { return this.Position; } set { this.Position = value; } }
        object IOrderAllocation.positionDesired { get { return this.PositionDesired; } set { this.PositionDesired = value; } }
        object IOrderAllocation.positionAfter { get { return this.PositionAfter; } set { this.PositionAfter = value; } }
        object IOrderAllocation.desiredAllocQty { get { return this.DesiredAllocQty; } set { this.DesiredAllocQty = value; } }
        object IOrderAllocation.allowedAllocQty { get { return this.AllowedAllocQty; } set { this.AllowedAllocQty = value; } }
        bool IOrderAllocation.isMonetary { get { return this.IsMonetary; } set { this.IsMonetary = value; } }

        public static explicit operator OrderAllocation(ComOrderAllocation coa)
        {
            return coa.ConvertTo();
        }

        public static explicit operator ComOrderAllocation(OrderAllocation oca)
        {
            return new ComOrderAllocation().ConvertFrom(oca) as ComOrderAllocation;
        }
    }
}
