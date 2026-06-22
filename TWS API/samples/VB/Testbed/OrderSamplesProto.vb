' Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

Imports IBApi

Namespace Samples

    Public Class OrderSamplesProto

        Public Shared Function CreatePlaceOrderRequest(orderId As Integer, contractProto As IBApi.protobuf.Contract, orderProto As IBApi.protobuf.Order) As IBApi.protobuf.PlaceOrderRequest
            '! [place_order_request]
            Dim placeOrderRequestProto As New IBApi.protobuf.PlaceOrderRequest()
            placeOrderRequestProto.OrderId = orderId
            placeOrderRequestProto.Contract = contractProto
            placeOrderRequestProto.Order = orderProto
            '! [place_order_request]
            Return placeOrderRequestProto
        End Function

        Public Shared Function LimitOrder(action As String, quantity As Decimal, price As Double, transmit As Boolean) As IBApi.protobuf.Order
            '! [limit_order]
            Dim orderProto As New IBApi.protobuf.Order()
            orderProto.Action = action
            orderProto.OrderType = "LMT"
            orderProto.TotalQuantity = quantity.ToString()
            orderProto.LmtPrice = price
            orderProto.Tif = "DAY"
            orderProto.Transmit = transmit
            '! [limit_order]
            Return orderProto
        End Function

        Public Shared Function BetaHedgeOrder(parentId As Integer, action As String, hedgeParam As String, hedgeMaxSize As Integer, transmit As Boolean) As IBApi.protobuf.Order
            '! [beta_hedge_order]
            Dim orderProto As New IBApi.protobuf.Order()
            orderProto.ParentId = parentId
            orderProto.Action = action
            orderProto.OrderType = "MKT"
            orderProto.Tif = "DAY"
            orderProto.HedgeType = "B"
            orderProto.HedgeParam = hedgeParam
            orderProto.HedgeMaxSize = hedgeMaxSize
            orderProto.Transmit = transmit
            '! [beta_hedge_order]
            Return orderProto
        End Function

    End Class

End Namespace
