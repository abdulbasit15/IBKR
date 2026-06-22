' Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

Imports IBApi

Namespace Samples

    Public Class ContractSamplesProto

        Public Shared Function IBMStockAtSmart() As IBApi.protobuf.Contract
            '! [IBM_stock_at_smart]
            Dim contractProto As New IBApi.protobuf.Contract()
            contractProto.Symbol = "IBM"
            contractProto.SecType = "STK"
            contractProto.Exchange = "SMART"
            contractProto.Currency = "USD"
            '! [IBM_stock_at_smart]
            Return contractProto
        End Function

        Public Shared Function MSFTStockAtSmart() As IBApi.protobuf.Contract
            '! [MSFT_stock_at_smart]
            Dim contractProto As New IBApi.protobuf.Contract()
            contractProto.Symbol = "MSFT"
            contractProto.SecType = "STK"
            contractProto.Exchange = "SMART"
            contractProto.Currency = "USD"
            '! [MSFT_stock_at_smart]
            Return contractProto
        End Function

    End Class

End Namespace
