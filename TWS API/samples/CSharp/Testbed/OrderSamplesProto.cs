/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */
using System;
using System.Collections.Generic;
using IBApi;

namespace Samples
{
    public class OrderSamplesProto
    {
        public static IBApi.protobuf.PlaceOrderRequest createPlaceOrderRequest(int orderId, IBApi.protobuf.Contract contractProto, IBApi.protobuf.Order orderProto)
        {
            // ! [place_order_request]
            IBApi.protobuf.PlaceOrderRequest placeOrderRequestProto = new IBApi.protobuf.PlaceOrderRequest();
            placeOrderRequestProto.OrderId = orderId;
            placeOrderRequestProto.Contract = contractProto;
            placeOrderRequestProto.Order = orderProto;
            // ! [place_order_request]
            return placeOrderRequestProto;
        }

        public static IBApi.protobuf.Order LimitOrder(String action, Decimal quantity, double limitPrice, bool transmit)
        {
            // ! [limit_order]
            IBApi.protobuf.Order orderProto = new IBApi.protobuf.Order();
            orderProto.Action = action;
            orderProto.OrderType = "LMT";
            orderProto.TotalQuantity = quantity.ToString();
            orderProto.LmtPrice = limitPrice;
            orderProto.Tif = "DAY";
            orderProto.Transmit = transmit;
            // ! [limit_order]
            return orderProto;
        }

        public static IBApi.protobuf.Order BetaHedgeOrder(int parentId, String action, String hedgeParam, int hedgeMaxSize, bool transmit)
        {
            // ! [beta_hedge_order]
            IBApi.protobuf.Order orderProto = new IBApi.protobuf.Order();
            orderProto.ParentId = parentId;
            orderProto.Action = action;
            orderProto.OrderType = "MKT";
            orderProto.Tif = "DAY";
            orderProto.HedgeType = "B";
            orderProto.HedgeParam = hedgeParam;
            orderProto.HedgeMaxSize = hedgeMaxSize;
            orderProto.Transmit = transmit;
            // ! [beta_hedge_order]
            return orderProto;
        }
    }
}
