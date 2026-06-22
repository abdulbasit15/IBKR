/* Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace TWSLib
{
    [ComVisible(true), Guid("0E262E32-4ABC-46EE-B828-643D59C06C96")]
    public interface IOrderAllocationList
    {
        [DispId(-4)]
        object _NewEnum { [return: MarshalAs(UnmanagedType.IUnknown)] get; }
        [DispId(0)]
        object this[int index] { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
        [DispId(1)]
        int Count { get; }
        [DispId(2)]
        [return: MarshalAs(UnmanagedType.IDispatch)]
        object Add();
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public class ComOrderAllocationList : IOrderAllocationList
    {
        private ComList<ComOrderAllocation, IBApi.OrderAllocation> Oal;

        public ComOrderAllocationList() : this(null) { }

        public ComOrderAllocationList(ComList<ComOrderAllocation, IBApi.OrderAllocation> oal)
        {
            this.Oal = oal == null ? new ComList<ComOrderAllocation, IBApi.OrderAllocation>(new List<IBApi.OrderAllocation>()) : oal;
        }

        public object _NewEnum
        {
            get { return Oal.GetEnumerator(); }
        }

        public object this[int index]
        {
            get { return Oal[index]; }
        }

        public int Count
        {
            get { return Oal.Count; }
        }

        public object Add()
        {
            var rval = new ComOrderAllocation();

            Oal.Add(rval);

            return rval;
        }

        public static implicit operator List<IBApi.OrderAllocation>(ComOrderAllocationList from)
        {
            return from.Oal.ConvertTo();
        }
    }
}
