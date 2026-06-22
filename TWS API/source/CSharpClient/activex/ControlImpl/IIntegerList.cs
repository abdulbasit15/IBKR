/* Copyright (C) 2025 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace TWSLib
{
    [ComVisible(true), Guid("64685489-DCE4-45B1-9CA1-D170596F04C3")]
    public interface IIntegerList
    {
        [DispId(-4)]
        object _NewEnum { [return: MarshalAs(UnmanagedType.IUnknown)] get; }
        [DispId(0)]
        object this[int index] { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
        [DispId(1)]
        int Count { get; }
        [DispId(2)]
        [return: MarshalAs(UnmanagedType.IDispatch)]
        object Add(int value);
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public class ComIntegerList : IIntegerList
    {
        private List<int> Cil;

        public ComIntegerList() : this(new List<int>()) { }

        public ComIntegerList(List<int> cil)
        {
            this.Cil = cil;
        }

        public object _NewEnum
        {
            get { return Cil.GetEnumerator(); }
        }

        public object this[int index]
        {
            get { return Cil[index]; }
        }

        public int Count
        {
            get { return Cil.Count; }
        }

        public object Add(int value)
        {
            Cil.Add(value);
            return value;
        }

        public static implicit operator List<int>(ComIntegerList from)
        {
            return from.Cil;
        }
    }
}

