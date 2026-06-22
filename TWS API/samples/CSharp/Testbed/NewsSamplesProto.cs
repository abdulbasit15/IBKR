/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using IBApi;

namespace Samples
{
    public class NewsSamplesProto
    {
        public static IBApi.protobuf.HistoricalNewsRequest HistoricalNewsRequestWithEndTime(int reqId)
        {
            //! [historical_news_request_with_end_time]
            IBApi.protobuf.HistoricalNewsRequest historicalNewsRequestProto = new IBApi.protobuf.HistoricalNewsRequest();
            historicalNewsRequestProto.ReqId = reqId;
            historicalNewsRequestProto.ConId = 8314;
            historicalNewsRequestProto.ProviderCodes = "BRFUPDN+BRFG";
            DateTime endDateTime = DateTime.Now.AddDays(-10);
            historicalNewsRequestProto.EndDateTime = endDateTime.ToString("yyyy-MM-dd HH:mm:ss.0");
            historicalNewsRequestProto.TotalResults = 10;
            return historicalNewsRequestProto;
            //! [historical_news_request_with_end_time]
        }

        public static IBApi.protobuf.HistoricalNewsRequest HistoricalNewsRequestWithStartTime(int reqId)
        {
            //! [historical_news_request_with_start_time]
            IBApi.protobuf.HistoricalNewsRequest historicalNewsRequestProto = new IBApi.protobuf.HistoricalNewsRequest();
            historicalNewsRequestProto.ReqId = reqId;
            historicalNewsRequestProto.ConId = 8314;
            historicalNewsRequestProto.ProviderCodes = "BRFUPDN+BRFG";
            DateTime startDateTime = DateTime.Now.AddDays(-10);
            historicalNewsRequestProto.StartDateTime = startDateTime.ToString("yyyy-MM-dd HH:mm:ss.0");
            historicalNewsRequestProto.TotalResults = 10;
            return historicalNewsRequestProto;
            //! [historical_news_request_with_start_time]
        }
    }
}
