' Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.


Namespace Samples

    Public Class NewsSamplesProto

        Public Shared Function HistoricalNewsRequestWithEndTime(reqId As Integer) As IBApi.protobuf.HistoricalNewsRequest
            '! [historical_news_request_with_end_time]
            Dim historicalNewsRequestProto As New IBApi.protobuf.HistoricalNewsRequest()
            historicalNewsRequestProto.ReqId = reqId
            historicalNewsRequestProto.ConId = 8314
            historicalNewsRequestProto.ProviderCodes = "BRFUPDN+BRFG"
            historicalNewsRequestProto.EndDateTime = String.Format("{0:yyyy-MM-dd HH:mm:ss.0}", DateTime.Now.AddDays(-10))
            historicalNewsRequestProto.TotalResults = 10
            Return historicalNewsRequestProto
            '! [historical_news_request_with_end_time]
        End Function

        Public Shared Function HistoricalNewsRequestWithStartTime(reqId As Integer) As IBApi.protobuf.HistoricalNewsRequest
            '! [historical_news_request_with_start_time]
            Dim historicalNewsRequestProto As New IBApi.protobuf.HistoricalNewsRequest()
            historicalNewsRequestProto.ReqId = reqId
            historicalNewsRequestProto.ConId = 8314
            historicalNewsRequestProto.ProviderCodes = "BRFUPDN+BRFG"
            historicalNewsRequestProto.StartDateTime = String.Format("{0:yyyy-MM-dd HH:mm:ss.0}", DateTime.Now.AddDays(-10))
            historicalNewsRequestProto.TotalResults = 10
            Return historicalNewsRequestProto
            '! [historical_news_request_with_start_time]
        End Function

    End Class

End Namespace
