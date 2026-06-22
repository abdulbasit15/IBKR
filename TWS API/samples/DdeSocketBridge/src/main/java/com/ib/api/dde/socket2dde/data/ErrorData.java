/* Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

package com.ib.api.dde.socket2dde.data;

/** Class represents error data received from TWS */
public class ErrorData {
    private final int m_requesId;
    private final long m_errorTime;
    private final int m_errorCode;
    private final String m_errorMessage;
    private final String m_advancedOrderRejectJson;

    // gets
    public int requesId()        { return m_requesId; } 
    public long errorTime()      { return m_errorTime; }
    public int errorCode()       { return m_errorCode; }
    public String errorMessage() { return m_errorMessage; }
    public String advancedOrderRejectJson() { return m_advancedOrderRejectJson; }

    public ErrorData(int requesId, long errorTime, int errorCode, String errorMessage, String advancedOrderRejectJson) {
        m_requesId = requesId;
        m_errorTime = errorTime;
        m_errorCode = errorCode;
        m_errorMessage = errorMessage;
        m_advancedOrderRejectJson = advancedOrderRejectJson;
    }

    public String toString() {
        return m_requesId + ";" + m_errorTime + ";" + m_errorCode + ";" + m_errorMessage + ";" + m_advancedOrderRejectJson;
    }
}
