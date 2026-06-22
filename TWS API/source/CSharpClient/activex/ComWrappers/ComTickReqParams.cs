/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System.Runtime.InteropServices;

namespace TWSLib
{
    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public class ComTickReqParams : ITickReqParams
    {
        readonly int ReqId;
        readonly string MinTick;
        readonly string BboExchange;
        readonly int SnapshotPermissions;
        readonly object LastPricePrecision;
        readonly object LastSizePrecision;

        int TWSLib.ITickReqParams.reqId
        {
            get { return ReqId; }
        }

        string TWSLib.ITickReqParams.minTick
        {
            get { return MinTick; }
        }

        string TWSLib.ITickReqParams.bboExchange
        {
            get { return BboExchange; }
        }

        int TWSLib.ITickReqParams.snapshotPermissions
        {
            get { return SnapshotPermissions; }
        }

        object ITickReqParams.lastPricePrecision
        {
            get { return LastPricePrecision; }
        }

        object ITickReqParams.lastSizePrecision
        {
            get { return LastSizePrecision; }
        }

        public ComTickReqParams(IBApi.protobuf.TickReqParams tickReqParamsProto)
        {
            this.ReqId = tickReqParamsProto.ReqId;
            this.MinTick = tickReqParamsProto.MinTick;
            this.BboExchange = tickReqParamsProto.BboExchange;
            this.SnapshotPermissions = tickReqParamsProto.SnapshotPermissions;
            this.LastPricePrecision = tickReqParamsProto.LastPricePrecision;
            this.LastSizePrecision = tickReqParamsProto.LastSizePrecision;
        }
    }
}
