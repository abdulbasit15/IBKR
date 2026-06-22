/* Copyright (C) 2025 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

package com.ib.api.dde.handlers;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.SortedMap;
import java.util.TreeMap;

import com.ib.api.dde.TwsService;
import com.ib.api.dde.dde2socket.requests.DdeRequest;
import com.ib.api.dde.dde2socket.requests.DdeRequestStatus;
import com.ib.api.dde.dde2socket.requests.DdeRequestType;
import com.ib.api.dde.dde2socket.requests.orders.AutoOpenOrdersRequest;
import com.ib.api.dde.dde2socket.requests.orders.CancelOrderRequest;
import com.ib.api.dde.dde2socket.requests.orders.CompletedOrdersRequest;
import com.ib.api.dde.dde2socket.requests.orders.OpenOrdersRequest;
import com.ib.api.dde.dde2socket.requests.orders.OrderStatusRequest;
import com.ib.api.dde.dde2socket.requests.orders.PlaceOrderRequest;
import com.ib.api.dde.dde2socket.requests.parser.RequestParser;
import com.ib.api.dde.handlers.base.BaseHandler;
import com.ib.api.dde.socket2dde.data.OpenOrderData;
import com.ib.api.dde.socket2dde.data.OrderData;
import com.ib.api.dde.socket2dde.data.OrderStatusData;
import com.ib.api.dde.socket2dde.notifications.DdeNotificationEvent;
import com.ib.api.dde.utils.OrderUtils;
import com.ib.api.dde.utils.Utils;
import com.ib.client.Contract;
import com.ib.client.Decimal;
import com.ib.client.EClientSocket;
import com.ib.client.Order;
import com.ib.client.OrderCancel;
import com.ib.client.OrderComboLeg;
import com.ib.client.OrderCondition;
import com.ib.client.OrderConditionType;
import com.ib.client.OrderType;
import com.ib.client.SoftDollarTier;

/** Class handles orders related requests and messages */
public class OrdersHandler extends BaseHandler {
    // parser
    private OpenOrdersRequestParser m_requestParser = new OpenOrdersRequestParser();

    // open orders
    private OpenOrdersRequest m_openOrdersRequest;
    boolean m_allOrders = false;
    private SortedMap<Integer, OpenOrderData> m_openOrderDataMap = Collections.synchronizedSortedMap(new TreeMap<Integer, OpenOrderData>()); // map orderId->OpenOrderData
    private SortedMap<Long, OpenOrderData> m_allOpenOrderDataMap = Collections.synchronizedSortedMap(new TreeMap<Long, OpenOrderData>()); // map permId->OpenOrderData (if orderId == 0)
    private DdeRequestStatus m_openOrdersSubscriptionStatus = DdeRequestStatus.UNKNOWN;

    // completed orders
    private CompletedOrdersRequest m_completedOrdersRequest;
    private List<OrderData> m_completedOrdersList = Collections.synchronizedList(new ArrayList<OrderData>()); // completed orders list
    private DdeRequestStatus m_completedOrdersRequestStatus = DdeRequestStatus.UNKNOWN;
    
    public OrdersHandler(EClientSocket clientSocket, TwsService twsService) {
        super(clientSocket, twsService);
    }

    /* *****************************************************************************************************
     *                                          Requests
    /* *****************************************************************************************************/
    /** Method requests open orders or all open orders and sets open order subscription status */
    public String handleOpenOrdersRequest(String requestStr, boolean allOrders) {
        m_allOrders = allOrders;
        m_openOrdersRequest = m_requestParser.parseOpenOrdersRequest(requestStr, allOrders);
        if (m_openOrdersSubscriptionStatus == DdeRequestStatus.UNKNOWN) {
            if (allOrders) {
                System.out.println("Handling all open orders request");
                clientSocket().reqAllOpenOrders();
            } else {
                System.out.println("Handling open orders request");
                clientSocket().reqOpenOrders();
            }
            m_openOrdersSubscriptionStatus = DdeRequestStatus.REQUESTED;
        }
        return m_openOrdersSubscriptionStatus.toString();
    }

    /** Method handles auto open orders request */
    public byte[] handleAutoOpenOrdersRequest(String requestStr) {
        AutoOpenOrdersRequest request =  m_requestParser.parseAutoOpenOrdersRequest(requestStr);
        System.out.println("Handling auto open orders request: autoBind=" + request.autoBind());
        clientSocket().reqAutoOpenOrders(request.autoBind());
        return null;
    }

    /** Method handles open orders array request */
    public byte[] handleOpenOrdersArrayRequest(String requestStr) {
        System.out.println("Handling open orders array request: id=" + m_openOrdersRequest.requestId() + " type=" + m_openOrdersRequest.ddeRequestType().topic());
        byte[] array = OrderUtils.openOrderDataListToByteArray(syncCopyOpenOrderDataValues(), null);
        m_openOrdersSubscriptionStatus = DdeRequestStatus.SUBSCRIBED;
        if (m_openOrdersRequest != null) {
            notifyDde(false, m_openOrdersRequest.ddeRequestString());
        }
        return array;
    }

    /** Method handles all open orders array request */
    public byte[] handleAllOpenOrdersArrayRequest(String requestStr) {
        System.out.println("Handling all open orders array request: id=" + m_openOrdersRequest.requestId() + " type=" + m_openOrdersRequest.ddeRequestType().topic());
        byte[] array = OrderUtils.openOrderDataListToByteArray(syncCopyOpenOrderDataValues(), syncCopyAllOpenOrderDataValues());
        m_openOrdersSubscriptionStatus = DdeRequestStatus.SUBSCRIBED;
        if (m_openOrdersRequest != null) {
            notifyDde(true, m_openOrdersRequest.ddeRequestString());
        }
        return array;
    }

    /** Method handles cancel open orders */
    public byte[] handleOpenOrdersCancel(String requestStr) {
        DdeRequest request = m_requestParser.parseRequest(requestStr, DdeRequestType.CANCEL_OPEN_ORDERS);
        System.out.println("Handling open orders cancel: id=" + request.requestId() + " type=" + request.ddeRequestType().topic());
        m_openOrdersSubscriptionStatus = DdeRequestStatus.UNKNOWN;
        return null;
    }

    /** Method handles order status (status, filled, remaining etc) */
    public String handleOrderStatusRequest(String requestStr) {
        OrderStatusRequest orderStatusRequest = m_requestParser.parseOrderStatusRequest(requestStr);
        System.out.println("Handling order status request: id=" + orderStatusRequest.requestId() + " field=" + orderStatusRequest.field());
        OpenOrderData openOrderData = m_openOrderDataMap.get(orderStatusRequest.requestId());
        if (openOrderData != null) {
            OrderStatusData orderStatus = openOrderData.orderStatus();
            return OrderUtils.getFieldValueFromOrderStatusRequest(orderStatusRequest, orderStatus);
        }
        else {
            return "";
        }
    }

    /** Method handles what-if request */
    public String handleWhatIfRequest(String requestStr) {
        OrderStatusRequest whatIfRequest = m_requestParser.parseOrderStatusRequest(requestStr);
        System.out.println("Handling what-if request: id=" + whatIfRequest.requestId() + " field=" + whatIfRequest.field());
        OpenOrderData openOrderData = m_openOrderDataMap.get(whatIfRequest.requestId());
        if (openOrderData != null) {
            return OrderUtils.getFieldValueFromWhatIfRequest(whatIfRequest, openOrderData);
        }
        else {
            return "";
        }
    }
    
    /** Method sends place order request to TWS */
    public byte[] handlePlaceOrderRequest(String requestStr, byte[] data, boolean whatIf) {
        PlaceOrderRequest request = m_requestParser.parsePlaceOrderRequest(requestStr, data);
        if (request != null) {
            request.order().whatIf(whatIf);
                    
            if (whatIf) {
                System.out.println("Sending what-if request: id=" + request.requestId() + " for contract=" + Utils.shortContractString(request.contract()) + " order=" + Utils.shortOrderString(request.order()));
            } else {
                System.out.println("Placing order: id=" + request.requestId() + " for contract=" + Utils.shortContractString(request.contract()) + " order=" + Utils.shortOrderString(request.order()));
            }
            twsService().incrementNextValidId();
            if (request.order().slOrderId() != Integer.MAX_VALUE) {
                twsService().incrementNextValidId();
            }
            if (request.order().ptOrderId() != Integer.MAX_VALUE) {
                twsService().incrementNextValidId();
            }
            OrderStatusData orderStatus = new OrderStatusData(request.requestId(), "Sent", Decimal.INVALID, 
                    request.order().totalQuantity(), 0, request.order().permId(), request.order().parentId(), 
                    0, request.order().clientId(), "", 0); 
            OpenOrderData openOrderData = new OpenOrderData(request.requestId(), request.contract(), request.order(), null, orderStatus, false);
    
            m_openOrderDataMap.put(request.requestId(), openOrderData);
            
            clientSocket().placeOrder(request.requestId(), request.contract(), request.order()); 
        }
        
        return null;
    }

    /** Method sends cancel order request to TWS */
    public byte[] handleCancelOrderRequest(String requestStr) {
        CancelOrderRequest request = m_requestParser.parseCancelOrderRequest(requestStr);
        System.out.println("Cancelling order: id=" + request.requestId() + " manualOrderCancelTime=" + request.orderCancel().manualOrderCancelTime());
        clientSocket().cancelOrder(request.requestId(), request.orderCancel()); 
        return null;
    }

    /** Method clears order */
    public byte[] handleClearOrderRequest(String requestStr) {
        DdeRequest request = m_requestParser.parseRequest(requestStr, DdeRequestType.CLEAR_ORDER);
        System.out.println("Clearing order: id=" + request.requestId());
        m_openOrderDataMap.remove(request.requestId());
        return null;
    }

    /** Method sends global cancel to TWS */
    public byte[] handleGlobalCancel(String requestStr) {
        CancelOrderRequest request = m_requestParser.parseCancelOrderRequest(requestStr);
        System.out.println("Handling global cancel.");
        clientSocket().reqGlobalCancel(request.orderCancel()); 
        return null;
    }
    
    /** Method requests completed orders and sets completed orders request status */
    public String handleCompletedOrdersRequest(String requestStr) {
        m_completedOrdersRequest = m_requestParser.parseCompletedOrdersRequest(requestStr);
        if (m_completedOrdersRequestStatus == DdeRequestStatus.UNKNOWN) {
            System.out.println("Handling completed orders request");
            clientSocket().reqCompletedOrders(m_completedOrdersRequest.apiOnly());
            m_completedOrdersRequestStatus = DdeRequestStatus.REQUESTED;
        }
        return m_completedOrdersRequestStatus.toString();
    }
    
    /** Method handles completed orders array request */
    public byte[] handleCompletedOrdersArrayRequest(String requestStr) {
        System.out.println("Handling completed orders array request: id=" + m_completedOrdersRequest.requestId() + " type=" + m_completedOrdersRequest.ddeRequestType().topic());
        byte[] array = OrderUtils.openOrderDataListToByteArray(syncCopyCompletedOrdersList(), null);
        m_completedOrdersRequestStatus = DdeRequestStatus.RECEIVED;
        if (m_completedOrdersRequest != null) {
            notifyDde(false, m_completedOrdersRequest.ddeRequestString());
        }
        return array;
    }
    
    /** Method handles cancel completed orders */
    public byte[] handleCompletedOrdersCancel() {
        m_completedOrdersRequestStatus = DdeRequestStatus.UNKNOWN;
        m_completedOrdersRequest = null;
        m_completedOrdersList.clear();
        
        return null;
    }
    
    /* *****************************************************************************************************
     *                                          Responses
    /* *****************************************************************************************************/
    /** Method updates order status for orderId */
    public void updateOrderStatus(OrderStatusData orderStatus) {
        if (orderStatus.orderId() == 0) {
            OpenOrderData openOrderData = m_allOpenOrderDataMap.get(orderStatus.permId());
            if (openOrderData != null) {
                openOrderData.orderStatus(orderStatus);
                openOrderData.isUpdated(true);
            } else {
                m_allOpenOrderDataMap.put(orderStatus.permId(), new OpenOrderData(orderStatus.orderId(), orderStatus, true));
            }
        } else {
            if (m_allOpenOrderDataMap.containsKey(orderStatus.permId())) {
                m_allOpenOrderDataMap.remove(orderStatus.permId());
            }
            OpenOrderData openOrderData = m_openOrderDataMap.get(orderStatus.orderId());
            if (openOrderData != null) {
                openOrderData.orderStatus(orderStatus);
                openOrderData.isUpdated(true);
            } else {
                m_openOrderDataMap.put(orderStatus.orderId(), new OpenOrderData(orderStatus.orderId(), orderStatus, true));
            }
        }

        if (m_openOrdersSubscriptionStatus == DdeRequestStatus.SUBSCRIBED) {
            m_openOrdersSubscriptionStatus = DdeRequestStatus.RECEIVED;
            if (m_openOrdersRequest != null) {
                notifyDde(m_allOrders, m_openOrdersRequest.ddeRequestString());
            }
        }

        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.STATUS.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.FILLED.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.REMAINING.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.AVG_FILL_PRICE.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.PERM_ID.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.PARENT_ID.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.LAST_FILL_PRICE.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.CLIENT_ID.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.WHY_HELD.topic());
        notifyDde(orderStatus.orderId(), DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.MKT_CAP_PRICE.topic());
    }

    /** Method saves open order data */
    public void updateOpenOrderData(OpenOrderData newOpenOrderData) {
        if (newOpenOrderData.orderId() == 0) {
            OpenOrderData openOrderData = m_allOpenOrderDataMap.get(newOpenOrderData.order().permId());
            if (openOrderData != null) {
                openOrderData.contract(newOpenOrderData.contract());
                openOrderData.order(newOpenOrderData.order());
                openOrderData.orderState(newOpenOrderData.orderState());
                openOrderData.isUpdated(newOpenOrderData.isUpdated());
            } else {
                m_allOpenOrderDataMap.put(newOpenOrderData.order().permId(), newOpenOrderData);
            }
        } else {
            if (m_allOpenOrderDataMap.containsKey(newOpenOrderData.order().permId())) {
                m_allOpenOrderDataMap.remove(newOpenOrderData.order().permId());
            }
            OpenOrderData openOrderData = m_openOrderDataMap.get(newOpenOrderData.orderId());
            if (openOrderData != null) {
                openOrderData.contract(newOpenOrderData.contract());
                openOrderData.order(newOpenOrderData.order());
                openOrderData.orderState(newOpenOrderData.orderState());
                openOrderData.isUpdated(newOpenOrderData.isUpdated());
            } else {
                m_openOrderDataMap.put(newOpenOrderData.orderId(), newOpenOrderData);
            }
        }
        if (newOpenOrderData.order().whatIf()) {
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_COMMISSION_AND_FEES.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_COMMISSION_AND_FEES_CURRENCY.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_CURRENT_EQUITY_WITH_LOAN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_CURRENT_INIT_MARGIN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_CURRENT_MAINT_MARGIN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_CHANGE_EQUITY_WITH_LOAN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_CHANGE_INIT_MARGIN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_CHANGE_MAINT_MARGIN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_POST_EQUITY_WITH_LOAN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_POST_INIT_MARGIN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_POST_MAINT_MARGIN.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_BOND_ACCRUED_INTEREST.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_MARGIN_CURRENCY.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_INIT_MARGIN_BEFORE_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_MAINT_MARGIN_BEFORE_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_EQUITY_WITH_LOAN_BEFORE_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_INIT_MARGIN_CHANGE_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_MAINT_MARGIN_CHANGE_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_EQUITY_WITH_LOAN_CHANGE_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_INIT_MARGIN_AFTER_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_MAINT_MARGIN_AFTER_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_EQUITY_WITH_LOAN_AFTER_OUTSIDE_RTH.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_SUGGESTED_SIZE.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_REJECT_REASON.topic());
            notifyDde(newOpenOrderData.orderId(), DdeRequestType.WHAT_IF_REQUEST.topic(), DdeRequestType.WHAT_IF_ORDER_ALLOCATIONS.topic());
        } else {
            if (m_openOrdersSubscriptionStatus == DdeRequestStatus.SUBSCRIBED) {
                m_openOrdersSubscriptionStatus = DdeRequestStatus.RECEIVED;
                if (m_openOrdersRequest != null) {
                    notifyDde(m_allOrders, m_openOrdersRequest.ddeRequestString());
                }
            }
        }
    }

    /** Method updates open orders subscription status after openOrderEnd callback is received */
    public void updateOpenOrderEnd() {
        if (m_openOrdersSubscriptionStatus == DdeRequestStatus.REQUESTED) {
            m_openOrdersSubscriptionStatus = DdeRequestStatus.RECEIVED;
            if (m_openOrdersRequest != null) {
                notifyDde(m_allOrders, m_openOrdersRequest.ddeRequestString());
            }
        }
    }

    /** Method saves completed order data */
    public void updateCompletedOrderData(OrderData completedOrderData) {
        m_completedOrdersList.add(completedOrderData);
    }

    /** Method updates completed orders request status after completedOrdersEnd callback is received */
    public void updateCompletedOrdersEnd() {
        if (m_completedOrdersRequestStatus == DdeRequestStatus.REQUESTED) {
            m_completedOrdersRequestStatus = DdeRequestStatus.RECEIVED;
            if (m_completedOrdersRequest != null) {
                notifyDde(m_completedOrdersRequest.ddeRequestString());
            }
        }
    }
    
    /** Method updates order status with error for orderId */
    public void updateOrderStatusError(int orderId, String errorMessage) {
        OpenOrderData openOrderData = m_openOrderDataMap.get(orderId);
        if (openOrderData != null) {
            openOrderData.orderStatus().errorMessage(errorMessage);
            notifyDde(orderId, DdeRequestType.ORDER_STATUS.topic(), DdeRequestType.ERROR.topic());
        }
    }

    /* *****************************************************************************************************
     *                                          Other methods
    /* *****************************************************************************************************/
    /** Method sends notification to DDE */
    private void notifyDde(boolean allOrders, String requestStr) {
        DdeNotificationEvent event = RequestParser.createDdeNotificationEvent(allOrders ? 
                DdeRequestType.REQ_ALL_OPEN_ORDERS.topic() : DdeRequestType.REQ_OPEN_ORDERS.topic(), requestStr);
        twsService().notifyDde(event);
    }

    private void notifyDde(String requestStr) {
        DdeNotificationEvent event = RequestParser.createDdeNotificationEvent(DdeRequestType.REQ_COMPLETED_ORDERS.topic(), requestStr);
        twsService().notifyDde(event);
    }
    
    private List<OrderData> syncCopyOpenOrderDataValues() {
        synchronized(m_openOrderDataMap) {
            ArrayList<OrderData> updatedOpenOrderDataList = new ArrayList<OrderData>();
            for (OpenOrderData openOrderData: m_openOrderDataMap.values()){
                if (openOrderData.isUpdated()) {
                    updatedOpenOrderDataList.add(openOrderData);
                    openOrderData.isUpdated(false);
                }
            }
            return updatedOpenOrderDataList;
        }
    }

    private List<OrderData> syncCopyAllOpenOrderDataValues() {
        synchronized(m_allOpenOrderDataMap) {
            ArrayList<OrderData> updatedAllOpenOrderDataList = new ArrayList<OrderData>();
            for (OpenOrderData openOrderData: m_allOpenOrderDataMap.values()){
                if (openOrderData.isUpdated()) {
                    updatedAllOpenOrderDataList.add(openOrderData);
                    openOrderData.isUpdated(false);
                }
            }
            return updatedAllOpenOrderDataList;
        }
    }

    private List<OrderData> syncCopyCompletedOrdersList() {
        synchronized(m_completedOrdersList) {
            return new ArrayList<OrderData>(m_completedOrdersList);
        }
    }
    
    /* *****************************************************************************************************
     *                                          Parsing
    /* *****************************************************************************************************/
    /** Class represents parser which parses DDE request strings to appropriate requests 
     * and TWS responses to DDE notifications */
    private class OpenOrdersRequestParser extends RequestParser {

        /** Method parser DDE request string to OpenOrdersRequest */
        private OpenOrdersRequest parseOpenOrdersRequest(String requestStr, boolean allOrders) {
            int requestId = -1;
            String[] messageTokens = requestStr.split(DDE_REQUEST_SEPARATOR_PARSE);
            requestId = parseRequestId(messageTokens[0]);
            return new OpenOrdersRequest(requestId, allOrders, requestStr);
        }

        /** Method parses DDE request string to AutoOpenOrdersRequest */
        private AutoOpenOrdersRequest parseAutoOpenOrdersRequest(String requestStr) {
            int requestId = -1;
            String[] messageTokens = requestStr.split(DDE_REQUEST_SEPARATOR_PARSE);
            requestId = parseRequestId(messageTokens[0]);
            boolean autoBind = messageTokens[1].equals("true");
            return new AutoOpenOrdersRequest(requestId, autoBind, requestStr);
        }

        /** Method parses DDE request string to PlaceOrderRequest */
        private PlaceOrderRequest parsePlaceOrderRequest(String requestStr, byte[] data) {
            PlaceOrderRequest request = null;
            int requestId = Integer.MAX_VALUE;
            if (data == null) {
                return null;
            }
            requestId = parseRequestId(requestStr);
            ArrayList<String> table  = Utils.convertArrayToTable(data);
            Contract contract = parseContract(table, true, true, true, true, false, false);
            Order order= parseOrder(table);
            if (contract != null && order != null) {
                request = new PlaceOrderRequest(requestId, contract, order, requestStr);
            }
            return request;
        }        
        
        /** Method parses DDE request string to CancelOrderRequest */
        public CancelOrderRequest parseCancelOrderRequest(String requestStr) {
            int requestId = -1;
            String[] messageTokens = requestStr.split(DDE_REQUEST_SEPARATOR_PARSE);
            if (messageTokens.length > 0) {
                requestId = parseRequestId(messageTokens[0]);
            }
            OrderCancel orderCancel = new OrderCancel();
            String messageParamsStr = "";
            if (messageTokens.length > 1) {
                messageParamsStr = messageTokens[1];
                String[] messageParams = messageParamsStr.split(PARAM_SEPARATOR);
                if (messageParams.length > 0) {
                    orderCancel.manualOrderCancelTime(messageParams[0]);
                }
                if (messageParams.length > 1) {
                    orderCancel.extOperator(messageParams[1]);
                }
                if (messageParams.length > 2) {
                    orderCancel.manualOrderIndicator(getIntFromString(messageParams[2]));
                }
            }
            return new CancelOrderRequest(requestId, orderCancel, requestStr);
        }

        /** Method parses DDE request string to OrderStatusRequest */
        private OrderStatusRequest parseOrderStatusRequest(String requestStr) {
            int requestId = Integer.MAX_VALUE;
            String orderStatusField = "";
            String[] requestTokens = requestStr.split(DDE_REQUEST_SEPARATOR_PARSE);
            if (requestTokens.length > 0) {
                requestId = parseRequestId(requestTokens[0]);
            }
            if (requestTokens.length > 1) {
                orderStatusField = requestTokens[1];
            }
            OrderStatusRequest request = new OrderStatusRequest(requestId, orderStatusField, requestStr);
            return request;
        }
        
        /** Method parser DDE request string to CompletedOrdersRequest */
        private CompletedOrdersRequest parseCompletedOrdersRequest(String requestStr) {
            int requestId = -1;
            boolean apiOnly = false;
            String[] requestTokens = requestStr.split(DDE_REQUEST_SEPARATOR_PARSE);
            if (requestTokens.length > 0) {
                requestId = parseRequestId(requestTokens[0]);
            }
            if (requestTokens.length > 1) {
                apiOnly = getBooleanFromString(requestTokens[1]);
            }
            return new CompletedOrdersRequest(requestId, apiOnly, requestStr);
        }
        
        /** Method parses order fields */
        private Order parseOrder(ArrayList<String> table) {
            Order order = new Order();
            if (table.size() < 158) {
                System.out.println("Cannot extract order fields");
                return null;
            }
            // base order fields
            if (Utils.isNotNull(table.get(16))) {
                order.action(table.get(16));
            }
            if (Utils.isNotNull(table.get(17))) {
                order.totalQuantity(Decimal.parse(table.get(17)));
            }
            if (Utils.isNotNull(table.get(18))) {
                order.orderType(table.get(18));
            }
            if (Utils.isNotNull(table.get(19))) {
                order.lmtPrice(getDoubleFromString(table.get(19)));
            }
            if (Utils.isNotNull(table.get(20))) {
                order.auxPrice(getDoubleFromString(table.get(20)));
            }
            
            // extended order attributes
            if (Utils.isNotNull(table.get(21))) {
                order.tif(table.get(21));
            }
            if (Utils.isNotNull(table.get(22))) {
                order.displaySize(getIntFromString(table.get(22)));
            }
            if (Utils.isNotNull(table.get(23))) {
                order.settlingFirm(table.get(23));
            }
            if (Utils.isNotNull(table.get(24))) {
                order.clearingAccount(table.get(24));
            }
            if (Utils.isNotNull(table.get(25))) {
                order.clearingIntent(table.get(25));
            }
            if (Utils.isNotNull(table.get(26))) {
                order.openClose(table.get(26));
            }
            if (Utils.isNotNull(table.get(27))) {
                order.origin(getIntFromString(table.get(27)));
            }
            if (Utils.isNotNull(table.get(28))) {
                order.shortSaleSlot(getIntFromString(table.get(28)));
            }
            if (Utils.isNotNull(table.get(29))) {
                order.designatedLocation(table.get(29));
            }
            if (Utils.isNotNull(table.get(30))) {
                order.exemptCode(getIntFromString(table.get(30)));
            }
            if (Utils.isNotNull(table.get(31))) {
                order.allOrNone(getBooleanFromString(table.get(31)));
            }
            if (Utils.isNotNull(table.get(32))) {
                order.blockOrder(getBooleanFromString(table.get(32)));
            }
            if (Utils.isNotNull(table.get(33))) {
                order.hidden(getBooleanFromString(table.get(33)));
            }
            if (Utils.isNotNull(table.get(34))) {
                order.outsideRth(getBooleanFromString(table.get(34)));
            }
            if (Utils.isNotNull(table.get(35))) {
                order.sweepToFill(getBooleanFromString(table.get(35)));
            }
            if (Utils.isNotNull(table.get(36))) {
                order.percentOffset(getDoubleFromString(table.get(36)));
            }
            if (Utils.isNotNull(table.get(37))) {
                order.trailingPercent(getDoubleFromString(table.get(37)));
            }
            if (Utils.isNotNull(table.get(38))) {
                order.trailStopPrice(getDoubleFromString(table.get(38)));
            }
            if (Utils.isNotNull(table.get(39))) {
                order.minQty(getIntFromString(table.get(39)));
            }
            if (Utils.isNotNull(table.get(40))) {
                order.goodAfterTime(table.get(40));
            }
            if (Utils.isNotNull(table.get(41))) {
                order.goodTillDate(table.get(41));
            }
            if (Utils.isNotNull(table.get(42))) {
                order.ocaGroup(table.get(42));
            }
            if (Utils.isNotNull(table.get(43))) {
                order.ocaType(getIntFromString(table.get(43)));
            }
            if (Utils.isNotNull(table.get(44))) {
                order.orderRef(table.get(44));
            }
            if (Utils.isNotNull(table.get(45))) {
                order.rule80A(table.get(45));
            }
            if (Utils.isNotNull(table.get(46))) {
                order.triggerMethod(getIntFromString(table.get(46)));
            }
            if (Utils.isNotNull(table.get(47))) {
                order.activeStartTime(table.get(47));
            }
            if (Utils.isNotNull(table.get(48))) {
                order.activeStopTime(table.get(48));
            }
            if (Utils.isNotNull(table.get(49))) {
                order.account(table.get(49));
            }
            if (Utils.isNotNull(table.get(50))) {
                order.faGroup(table.get(50));
            }
            if (Utils.isNotNull(table.get(51))) {
                order.faMethod(table.get(51));
            }
            if (Utils.isNotNull(table.get(52))) {
                order.faPercentage(table.get(52));
            }
            if (Utils.isNotNull(table.get(53))) {
                order.volatility(getDoubleFromString(table.get(53)));
            }
            if (Utils.isNotNull(table.get(54))) {
                order.volatilityType(getIntFromString(table.get(54)));
            }
            if (Utils.isNotNull(table.get(55))) {
                order.continuousUpdate(getIntFromString(table.get(55)));
            }
            if (Utils.isNotNull(table.get(56))) {
                order.referencePriceType(getIntFromString(table.get(56)));
            }
            if (Utils.isNotNull(table.get(57))) {
                order.deltaNeutralOrderType(table.get(57));
            }
            if (Utils.isNotNull(table.get(58))) {
                order.deltaNeutralAuxPrice(getDoubleFromString(table.get(58)));
            }
            if (Utils.isNotNull(table.get(59))) {
                order.deltaNeutralConId(getIntFromString(table.get(59)));
            }
            if (Utils.isNotNull(table.get(60))) {
                order.deltaNeutralOpenClose(table.get(60));
            }
            if (Utils.isNotNull(table.get(61))) {
                order.deltaNeutralShortSale(getBooleanFromString(table.get(61)));
            }
            if (Utils.isNotNull(table.get(62))) {
                order.deltaNeutralShortSaleSlot(getIntFromString(table.get(62)));
            }
            if (Utils.isNotNull(table.get(63))) {
                order.deltaNeutralDesignatedLocation(table.get(63));
            }
            if (Utils.isNotNull(table.get(64))) {
                order.deltaNeutralSettlingFirm(table.get(64));
            }
            if (Utils.isNotNull(table.get(65))) {
                order.deltaNeutralClearingAccount(table.get(65));
            }
            if (Utils.isNotNull(table.get(66))) {
                order.deltaNeutralClearingIntent(table.get(66));
            }
            if (Utils.isNotNull(table.get(67))) {
                order.scaleInitLevelSize(getIntFromString(table.get(67)));
            }
            if (Utils.isNotNull(table.get(68))) {
                order.scaleSubsLevelSize(getIntFromString(table.get(68)));
            }
            if (Utils.isNotNull(table.get(69))) {
                order.scalePriceIncrement(getDoubleFromString(table.get(69)));
            }
            if (Utils.isNotNull(table.get(70))) {
                order.scalePriceAdjustValue(getDoubleFromString(table.get(70)));
            }
            if (Utils.isNotNull(table.get(71))) {
                order.scalePriceAdjustInterval(getIntFromString(table.get(71)));
            }
            if (Utils.isNotNull(table.get(72))) {
                order.scaleProfitOffset(getDoubleFromString(table.get(72)));
            }
            if (Utils.isNotNull(table.get(73))) {
                order.scaleAutoReset(getBooleanFromString(table.get(73)));
            }
            if (Utils.isNotNull(table.get(74))) {
                order.scaleInitPosition(getIntFromString(table.get(74)));
            }
            if (Utils.isNotNull(table.get(75))) {
                order.scaleInitFillQty(getIntFromString(table.get(75)));
            }
            if (Utils.isNotNull(table.get(76))) {
                order.scaleRandomPercent(getBooleanFromString(table.get(76)));
            }
            if (Utils.isNotNull(table.get(77))) {
                order.scaleTable(table.get(77));
            }
            if (Utils.isNotNull(table.get(78))) {
                order.hedgeType(table.get(78));
            }
            if (Utils.isNotNull(table.get(79))) {
                order.hedgeParam(table.get(79));
            }
            if (Utils.isNotNull(table.get(80))) {
                order.hedgeMaxSize(getIntFromString(table.get(80)));
            }
            if (Utils.isNotNull(table.get(81))) {
                order.dontUseAutoPriceForHedge(getBooleanFromString(table.get(81)));
            }
            if (Utils.isNotNull(table.get(82))) {
                order.algoStrategy(table.get(82));
            }
            if (Utils.isNotNull(table.get(83))) {
                order.algoParams(parseTagValueStr(table.get(83)));
            }
            if (Utils.isNotNull(table.get(84))) {
                order.algoId(table.get(84));
            }
            if (Utils.isNotNull(table.get(85))) {
                order.smartComboRoutingParams(parseTagValueStr(table.get(85)));
            }
            if (Utils.isNotNull(table.get(86))) {
                order.orderComboLegs(parseOrderComboLegStr(table.get(86)));
            }
            if (Utils.isNotNull(table.get(87))) {
                order.transmit(getBooleanFromString(table.get(87)));
            }
            if (Utils.isNotNull(table.get(88))) {
                order.parentId(getIntFromString(table.get(88)));
            }
            if (Utils.isNotNull(table.get(89))) {
                order.overridePercentageConstraints(getBooleanFromString(table.get(89)));
            }
            if (Utils.isNotNull(table.get(90))) {
                order.discretionaryAmt(getDoubleFromString(table.get(90)));
            }
            if (Utils.isNotNull(table.get(91))) {
                order.optOutSmartRouting(getBooleanFromString(table.get(91)));
            }
            if (Utils.isNotNull(table.get(92))) {
                order.auctionStrategy(getIntFromString(table.get(92)));
            }
            if (Utils.isNotNull(table.get(93))) {
                order.startingPrice(getDoubleFromString(table.get(93)));
            }
            if (Utils.isNotNull(table.get(94))) {
                order.stockRefPrice(getDoubleFromString(table.get(94)));
            }
            if (Utils.isNotNull(table.get(95))) {
                order.delta(getDoubleFromString(table.get(95)));
            }
            if (Utils.isNotNull(table.get(96))) {
                order.stockRangeLower(getDoubleFromString(table.get(96)));
            }
            if (Utils.isNotNull(table.get(97))) {
                order.stockRangeUpper(getDoubleFromString(table.get(97)));
            }
            if (Utils.isNotNull(table.get(98))) {
                order.basisPoints(getDoubleFromString(table.get(98)));
            }
            if (Utils.isNotNull(table.get(99))) {
                order.basisPointsType(getIntFromString(table.get(99)));
            }
            if (Utils.isNotNull(table.get(100))) {
                order.notHeld(getBooleanFromString(table.get(100)));
            }
            if (Utils.isNotNull(table.get(101))) {
                order.orderMiscOptions(parseTagValueStr(table.get(101)));
            }
            if (Utils.isNotNull(table.get(102))) {
                order.solicited(getBooleanFromString(table.get(102)));
            }
            if (Utils.isNotNull(table.get(103))) {
                order.randomizeSize(getBooleanFromString(table.get(103)));
            }
            if (Utils.isNotNull(table.get(104))) {
                order.randomizePrice(getBooleanFromString(table.get(104)));
            }
            if (Utils.isNotNull(table.get(105))) {
                order.referenceContractId(getIntFromString(table.get(105)));
            }
            if (Utils.isNotNull(table.get(106))) {
                order.peggedChangeAmount(getDoubleFromString(table.get(106)));
            }
            if (Utils.isNotNull(table.get(107))) {
                order.isPeggedChangeAmountDecrease(getBooleanFromString(table.get(107)));
            }
            if (Utils.isNotNull(table.get(108))) {
                order.referenceChangeAmount(getDoubleFromString(table.get(108)));
            }
            if (Utils.isNotNull(table.get(109))) {
                order.referenceExchangeId(table.get(109));
            }
            if (Utils.isNotNull(table.get(110))) {
                order.adjustedOrderType(OrderType.get(table.get(110)));
            }
            if (Utils.isNotNull(table.get(111))) {
                order.triggerPrice(getDoubleFromString(table.get(111)));
            }
            if (Utils.isNotNull(table.get(112))) {
                order.adjustedStopPrice(getDoubleFromString(table.get(112)));
            }
            if (Utils.isNotNull(table.get(113))) {
                order.adjustedStopLimitPrice(getDoubleFromString(table.get(113)));
            }
            if (Utils.isNotNull(table.get(114))) {
                order.adjustedTrailingAmount(getDoubleFromString(table.get(114)));
            }
            if (Utils.isNotNull(table.get(115))) {
                order.adjustableTrailingUnit(getIntFromString(table.get(115)));
            }
            if (Utils.isNotNull(table.get(116))) {
                order.lmtPriceOffset(getDoubleFromString(table.get(116)));
            }
            if (Utils.isNotNull(table.get(117))) {
                order.conditions(parseOrderConditionsStr(table.get(117)));
            }
            if (Utils.isNotNull(table.get(118))) {
                order.conditionsIgnoreRth(getBooleanFromString(table.get(118)));
            }
            if (Utils.isNotNull(table.get(119))) {
                order.conditionsCancelOrder(getBooleanFromString(table.get(119)));
            }
            if (Utils.isNotNull(table.get(120))) {
                order.modelCode(table.get(120));
            }
            if (Utils.isNotNull(table.get(121))) {
                order.extOperator(table.get(121));
            }
            if (Utils.isNotNull(table.get(122))) {
                order.softDollarTier(parseSoftDollarTierStr(table.get(122)));
            }
            if (Utils.isNotNull(table.get(123))) {
                order.cashQty(getDoubleFromString(table.get(123)));
            }
            if (Utils.isNotNull(table.get(124))) {
                order.mifid2DecisionMaker(table.get(124));
            }
            if (Utils.isNotNull(table.get(125))) {
                order.mifid2DecisionAlgo(table.get(125));
            }
            if (Utils.isNotNull(table.get(126))) {
                order.mifid2ExecutionTrader(table.get(126));
            }
            if (Utils.isNotNull(table.get(127))) {
                order.mifid2ExecutionAlgo(table.get(127));
            }
            if (Utils.isNotNull(table.get(128))) {
                order.isOmsContainer(getBooleanFromString(table.get(128)));
            }
            if (Utils.isNotNull(table.get(129))) {
                order.discretionaryUpToLimitPrice(getBooleanFromString(table.get(129)));
            }
            if (Utils.isNotNull(table.get(130))) {
                order.usePriceMgmtAlgo(getBooleanFromString(table.get(130)));
            }
            if (Utils.isNotNull(table.get(131))) {
                order.duration(getIntFromString(table.get(131)));
            }
            if (Utils.isNotNull(table.get(132))) {
                order.postToAts(getIntFromString(table.get(132)));
            }
            if (Utils.isNotNull(table.get(133))) {
                order.autoCancelParent(getBooleanFromString(table.get(133)));
            }
            if (Utils.isNotNull(table.get(134))) {
                order.advancedErrorOverride(table.get(134));
            }
            if (Utils.isNotNull(table.get(135))) {
                order.manualOrderTime(table.get(135));
            }
            if (Utils.isNotNull(table.get(136))) {
                // manualOrderCancelTime - not used in placeOrder
            }
            if (Utils.isNotNull(table.get(137))) {
                order.minTradeQty(getIntFromString(table.get(137)));
            }
            if (Utils.isNotNull(table.get(138))) {
                order.minCompeteSize(getIntFromString(table.get(138)));
            }
            String competeAgainstBestOffset = table.get(139);
            if (Utils.isNotNull(competeAgainstBestOffset)) {
                order.competeAgainstBestOffset(competeAgainstBestOffset.equals(Utils.UP_TO_MID) ? Order.COMPETE_AGAINST_BEST_OFFSET_UP_TO_MID : getDoubleFromString(competeAgainstBestOffset));
            }
            if (Utils.isNotNull(table.get(140))) {
                order.midOffsetAtWhole(getDoubleFromString(table.get(140)));
            }
            if (Utils.isNotNull(table.get(141))) {
                order.midOffsetAtHalf(getDoubleFromString(table.get(141)));
            }
            if (Utils.isNotNull(table.get(142))) {
                order.customerAccount(table.get(142));
            }
            if (Utils.isNotNull(table.get(143))) {
                order.professionalCustomer(getBooleanFromString(table.get(143)));
            }
            if (Utils.isNotNull(table.get(144))) {
                order.includeOvernight(getBooleanFromString(table.get(144)));
            }
            if (Utils.isNotNull(table.get(145))) {
                order.manualOrderIndicator(getIntFromString(table.get(145)));
            }
            if (Utils.isNotNull(table.get(146))) {
                order.imbalanceOnly(getBooleanFromString(table.get(146)));
            }
            if (Utils.isNotNull(table.get(147))) {
                order.postOnly(getBooleanFromString(table.get(147)));
            }
            if (Utils.isNotNull(table.get(148))) {
                order.allowPreOpen(getBooleanFromString(table.get(148)));
            }
            if (Utils.isNotNull(table.get(149))) {
                order.ignoreOpenAuction(getBooleanFromString(table.get(149)));
            }
            if (Utils.isNotNull(table.get(150))) {
                order.deactivate(getBooleanFromString(table.get(150)));
            }
            if (Utils.isNotNull(table.get(151))) {
                order.seekPriceImprovement(getBooleanFromString(table.get(151)));
            }
            if (Utils.isNotNull(table.get(152))) {
                order.whatIfType(getIntFromString(table.get(152)));
            }
            if (Utils.isNotNull(table.get(153))) {
                order.routeMarketableToBbo(getBooleanFromString(table.get(153)));
            }
            if (Utils.isNotNull(table.get(154))) {
                order.slOrderId(getIntFromString(table.get(154)));
            }
            if (Utils.isNotNull(table.get(155))) {
                order.slOrderType(table.get(155));
            }
            if (Utils.isNotNull(table.get(156))) {
                order.ptOrderId(getIntFromString(table.get(156)));
            }
            if (Utils.isNotNull(table.get(157))) {
                order.ptOrderType(table.get(157));
            }
            return order;
        }

        /** Method parses order combo leg string in format: "price2;price2;" into List<OrderComboLeg> */
        private List<OrderComboLeg> parseOrderComboLegStr(String orderComboLegStr) {
            List<OrderComboLeg> orderComboLegList = new ArrayList<OrderComboLeg>();
            String[] splittedOrderComboLegStr = orderComboLegStr.split(SEMICOLON_SIGN);
            for (String priceStr : splittedOrderComboLegStr) {
                orderComboLegList.add(new OrderComboLeg(getDoubleFromString(priceStr)));
            }
            return orderComboLegList;
        }

        /** Method parses order conditions string in format: "type1_param11_param12_...;type2_param21_param22_...;" 
         * into List<OrderCondition> */
        private List<OrderCondition> parseOrderConditionsStr(String orderConditionsStr) {
            List<OrderCondition> orderConditionList = new ArrayList<OrderCondition>();
            if (orderConditionsStr == null || orderConditionsStr.isEmpty()) {
                return orderConditionList;
            }

            String[] splittedOrderConditionsStr = orderConditionsStr.replace(" and", " and~").replace(" or", " or~").split("~");
            for (int i = 0; i < splittedOrderConditionsStr.length; i++) {
                String orderConditionStr = splittedOrderConditionsStr[i].trim();
                Optional<OrderCondition> orderCondition = Arrays.stream(OrderConditionType.values())
                        .map(orderConditionType -> OrderCondition.create(orderConditionType))
                        .filter(condition -> condition.tryToParse(orderConditionStr)).findFirst();
                if (orderCondition.isPresent()) {
                    orderConditionList.add(orderCondition.get());
                }
            }
            
            return orderConditionList;
        }
        
        /** Method parses soft dollar tier string in format: "tag1=value1;tag2=valu2;" into List<TagValue> */
        private SoftDollarTier parseSoftDollarTierStr(String softDollarTierStr) {
            SoftDollarTier softDollarTier = new SoftDollarTier(EMPTY_STR, EMPTY_STR, EMPTY_STR);
            String[] splittedSoftDollarTierStr = softDollarTierStr.split(SEMICOLON_SIGN);
            if (splittedSoftDollarTierStr.length >= 3) {
                softDollarTier = new SoftDollarTier(splittedSoftDollarTierStr[0], splittedSoftDollarTierStr[1], splittedSoftDollarTierStr[2]);
            }
            return softDollarTier;
        }
        
    }
    
}
