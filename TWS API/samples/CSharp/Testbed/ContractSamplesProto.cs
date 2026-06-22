/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using IBApi;

namespace Samples
{
    public class ContractSamplesProto
    {
        public static IBApi.protobuf.Contract IBMStockAtSmart()
        {
            //! [IBM_stock_at_smart]
            IBApi.protobuf.Contract contractProto = new IBApi.protobuf.Contract();
            contractProto.Symbol = "IBM";
            contractProto.SecType = "STK";
            contractProto.Exchange = "SMART";
            contractProto.Currency = "USD";
            //! [IBM_stock_at_smart]
            return contractProto;
        }

        public static IBApi.protobuf.Contract MSFTStockAtSmart()
        {
            //! [MSFT_stock_at_smart]
            IBApi.protobuf.Contract contractProto = new IBApi.protobuf.Contract();
            contractProto.Symbol = "MSFT";
            contractProto.SecType = "STK";
            contractProto.Exchange = "SMART";
            contractProto.Currency = "USD";
            //! [MSFT_stock_at_smart]
            return contractProto;
        }
    }
}
