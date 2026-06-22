' Copyright (C) 2025 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

Imports IBApi
Imports System.Collections.Generic

Friend Class ApiEventSource
    Implements IBApi.EWrapper

    Private m_Api As EClient
    Private m_form As Form

    Sub New(form As Form)
        m_form = form
    End Sub

    Friend WriteOnly Property ApiClient As EClient
        Set(value As EClient)
            m_Api = value
        End Set
    End Property

    Sub InvokeIfRequired(action As Action)
        If m_form.IsDisposed Then Exit Sub

        If m_form.InvokeRequired Then
            m_form.Invoke(action)
        Else
            action()
        End If
    End Sub

#Region "IBApi.EWrapper"

    Private Sub EWrapper_PnL(reqId As Integer, dailyPnL As Double, unrealizedPnL As Double, realizedPnL As Double) Implements EWrapper.pnl
        InvokeIfRequired(Sub()
                             RaiseEvent PnL(Me, New PnLEventArgs With {
                                 .requestId = reqId,
                                 .dailyPnL = dailyPnL,
                                 .unrealizedPnL = unrealizedPnL,
                                 .realizedPnL = realizedPnL
                                         })
                         End Sub)
    End Sub

    Private Sub EWrapper_PnLSingle(reqId As Integer, pos As Decimal, dailyPnL As Double, unrealizedPnL As Double, realizedPnL As Double, value As Double) Implements EWrapper.pnlSingle
        InvokeIfRequired(Sub()
                             RaiseEvent PnLSingle(Me, New PnLSingleEventArgs With {
                                 .requestId = reqId,
                                 .pos = pos,
                                 .dailyPnL = dailyPnL,
                                 .value = value,
                                 .unrealizedPnL = unrealizedPnL,
                                 .realizedPnL = realizedPnL
                                        })
                         End Sub)
    End Sub

    Private Sub EWrapper_histogramdata(requestId As Integer, data As HistogramEntry()) Implements EWrapper.histogramData
        InvokeIfRequired(Sub()
                             RaiseEvent HistogramData(Me, New HistogramDataEventArgs With {
                                 .requestId = requestId,
                                 .data = data
                                         })
                         End Sub)
    End Sub

    Private Sub EWrapper_headTimestamp(requestId As Integer, timeStamp As String) Implements IBApi.EWrapper.headTimestamp
        InvokeIfRequired(Sub()
                             RaiseEvent HeadTimestamp(Me, New HeadTimestampEventArgs With {
                                 .requestId = requestId,
                                 .timeStamp = timeStamp
                                         })
                         End Sub)
    End Sub

    Private Sub EWrapper_AccountDownloadEnd(account As String) Implements IBApi.EWrapper.accountDownloadEnd
        InvokeIfRequired(Sub()
                             RaiseEvent AccountDownloadEnd(Me, New AccountDownloadEndEventArgs With {
                                 .account = account
                                         })
                         End Sub)
    End Sub

    Private Sub EWrapper_AccountSummary(reqId As Integer, account As String, tag As String, value As String, currency As String) Implements IBApi.EWrapper.accountSummary
        InvokeIfRequired(Sub()
                             RaiseEvent AccountSummary(Me, New AccountSummaryEventArgs With {
                                                                      .reqId = reqId,
                                                                      .account = account,
                                                                      .tag = tag,
                                                                      .value = value,
                                                                      .currency = currency
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_AccountSummaryEnd(reqId As Integer) Implements IBApi.EWrapper.accountSummaryEnd
        InvokeIfRequired(Sub()
                             RaiseEvent AccountSummaryEnd(Me, New AccountSummaryEndEventArgs With {
                                                                     .reqId = reqId
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_CommissionAndFeesReport(commissionAndFeesReport As IBApi.CommissionAndFeesReport) Implements IBApi.EWrapper.commissionAndFeesReport
        InvokeIfRequired(Sub()
                             RaiseEvent CommissionAndFeesReport(Me, New CommissionAndFeesReportEventArgs With {
                                                                     .commissionAndFeesReport = commissionAndFeesReport
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ConnectionClosed() Implements IBApi.EWrapper.connectionClosed
        InvokeIfRequired(Sub()
                             RaiseEvent ConnectionClosed(Me, EventArgs.Empty)
                         End Sub)
    End Sub

    Private Sub EWrapper_ContractDetails(reqId As Integer, contractDetails As IBApi.ContractDetails) Implements IBApi.EWrapper.contractDetails
        InvokeIfRequired(Sub()
                             RaiseEvent ContractDetails(Me, New ContractDetailsEventArgs With {
                                                                     .reqId = reqId,
                                                                      .contractDetails = contractDetails
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ContractDetailsEnd(reqId As Integer) Implements IBApi.EWrapper.contractDetailsEnd
        InvokeIfRequired(Sub()
                             RaiseEvent ContractDetailsEnd(Me, New ContractDetailsEndEventArgs With {
                                                                     .reqId = reqId
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_CurrentTime(time As Long) Implements IBApi.EWrapper.currentTime
        InvokeIfRequired(Sub()
                             RaiseEvent CurrentTime(Me, New CurrentTimeEventArgs With {
                                                                     .time = time
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_DeltaNeutralValidation(reqId As Integer, deltaNeutralContract As IBApi.DeltaNeutralContract) Implements IBApi.EWrapper.deltaNeutralValidation
        InvokeIfRequired(Sub()
                             RaiseEvent DeltaNeutralValidation(Me, New DeltaNeutralValidationEventArgs With {
                                                                      .reqId = reqId,
                                                                      .deltaNeutralContract = deltaNeutralContract
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_DisplayGroupList(reqId As Integer, groups As String) Implements IBApi.EWrapper.displayGroupList
        InvokeIfRequired(Sub()
                             RaiseEvent DisplayGroupList(Me, New DisplayGroupListEventArgs With {
                                                                      .reqId = reqId,
                                                                      .groups = groups
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_DisplayGroupUpdated(reqId As Integer, contractInfo As String) Implements IBApi.EWrapper.displayGroupUpdated
        InvokeIfRequired(Sub()
                             RaiseEvent DisplayGroupUpdated(Me, New DisplayGroupUpdatedEventArgs With {
                                                                      .reqId = reqId,
                                                                      .contractInfo = contractInfo
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_Error(id As Integer, errorTime As Long, errorCode As Integer, errorMsg As String, advancedOrderRejectJson As String) Implements IBApi.EWrapper.error
        InvokeIfRequired(Sub()
                             RaiseEvent ErrMsg(Me, New ErrMsgEventArgs With {.id = id, .errorTime = errorTime, .errorCode = errorCode, .errorMsg = errorMsg, .advancedOrderRejectJson = advancedOrderRejectJson})
                         End Sub)
    End Sub

    Private Sub EWrapper_Error(str As String) Implements IBApi.EWrapper.error
        InvokeIfRequired(Sub()
                             RaiseEvent ErrMsg(Me, New ErrMsgEventArgs With {.id = -1, .errorTime = Util.CurrentTimeMillis(), .errorCode = -1, .errorMsg = str})
                         End Sub)
    End Sub

    Private Sub EWrapper_Error(e As Exception) Implements IBApi.EWrapper.error
        InvokeIfRequired(Sub()
                             RaiseEvent ErrMsg(Me, New ErrMsgEventArgs With {.id = -1, .errorTime = Util.CurrentTimeMillis(), .errorCode = -1, .errorMsg = e.Message})
                         End Sub)
    End Sub

    Private Sub EWrapper_ExecDetails(reqId As Integer, contract As IBApi.Contract, execution As IBApi.Execution) Implements IBApi.EWrapper.execDetails
        InvokeIfRequired(Sub()
                             RaiseEvent ExecDetails(Me, New ExecDetailsEventArgs With {
                                                                     .reqId = reqId,
                                                                      .contract = contract,
                                                                      .execution = execution
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ExecDetailsEnd(reqId As Integer) Implements IBApi.EWrapper.execDetailsEnd
        InvokeIfRequired(Sub()
                             RaiseEvent ExecDetailsEnd(Me, New ExecDetailsEndEventArgs With {
                                                                     .reqId = reqId
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_FundamentalData(reqId As Integer, data As String) Implements IBApi.EWrapper.fundamentalData
        InvokeIfRequired(Sub()
                             RaiseEvent FundamentalData(Me, New FundamentalDataEventArgs With {
                                                                     .reqId = reqId,
                                                                      .data = data
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_HistoricalData(reqId As Integer, bar As Bar) Implements IBApi.EWrapper.historicalData, EWrapper.historicalDataUpdate
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalData(Me, New HistoricalDataEventArgs With {
                                                                                                 .reqId = reqId,
                                                                                                 .[date] = bar.Time,
                                                                                                 .open = bar.Open,
                                                                                                 .high = bar.High,
                                                                                                 .low = bar.Low,
                                                                                                 .close = bar.Close,
                                                                                                 .volume = bar.Volume,
                                                                                                 .count = bar.Count,
                                                                                                 .WAP = bar.WAP
                                                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_HistoricalDataEnd(reqId As Integer, start As String, [end] As String) Implements IBApi.EWrapper.historicalDataEnd
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalDataEnd(Me, New HistoricalDataEndEventArgs With {
                                                                                                    .reqId = reqId,
                                                                                                    .start = start,
                                                                                                    .[end] = [end]
                                                                                                    })
                         End Sub)
    End Sub

    Private Sub EWrapper_ManagedAccounts(accountsList As String) Implements IBApi.EWrapper.managedAccounts
        InvokeIfRequired(Sub()
                             RaiseEvent ManagedAccounts(Me, New ManagedAccountsEventArgs With {
                                                                     .accountsList = accountsList
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_MarketDataType(reqId As Integer, marketDataType As Integer) Implements IBApi.EWrapper.marketDataType
        InvokeIfRequired(Sub()
                             RaiseEvent MarketDataType(Me, New MarketDataTypeEventArgs With {
                                                                     .reqId = reqId,
                                                                      .marketDataType = marketDataType
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_NextValidId(orderId As Integer) Implements IBApi.EWrapper.nextValidId
        InvokeIfRequired(Sub()
                             RaiseEvent NextValidId(Me, New NextValidIdEventArgs With {.Id = orderId})
                         End Sub)
    End Sub

    Private Sub EWrapper_OpenOrder(orderId As Integer, contract As IBApi.Contract, order As IBApi.Order, orderState As IBApi.OrderState) Implements IBApi.EWrapper.openOrder
        InvokeIfRequired(Sub()
                             RaiseEvent OpenOrder(Me, New OpenOrderEventArgs With {
                                                                     .orderId = orderId,
                                                                      .contract = contract,
                                                                      .order = order,
                                                                      .orderState = orderState
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_OpenOrderEnd() Implements IBApi.EWrapper.openOrderEnd
        InvokeIfRequired(Sub()
                             RaiseEvent OpenOrderEnd(Me, EventArgs.Empty)
                         End Sub)
    End Sub

    Private Sub EWrapper_OrderStatus(orderId As Integer, status As String, filled As Decimal, remaining As Decimal, avgFillPrice As Double, permId As Long, parentId As Integer, lastFillPrice As Double, clientId As Integer, whyHeld As String, mktCapPrice As Double) Implements IBApi.EWrapper.orderStatus
        InvokeIfRequired(Sub()
                             RaiseEvent OrderStatus(Me, New OrderStatusEventArgs With {
                                                                     .orderId = orderId,
                                                                      .status = status,
                                                                      .filled = filled,
                                                                      .remaining = remaining,
                                                                      .avgFillPrice = avgFillPrice,
                                                                      .permId = permId,
                                                                      .parentId = parentId,
                                                                      .lastFillPrice = lastFillPrice,
                                                                      .clientId = clientId,
                                                                      .whyHeld = whyHeld,
                                                                      .mktCapPrice = mktCapPrice
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_Position(account As String, contract As IBApi.Contract, pos As Decimal, avgCost As Double) Implements IBApi.EWrapper.position
        InvokeIfRequired(Sub()
                             RaiseEvent Position(Me, New PositionEventArgs With {
                                                                     .account = account,
                                                                      .contract = contract,
                                                                      .pos = pos,
                                                                      .avgCost = avgCost
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_PositionEnd() Implements IBApi.EWrapper.positionEnd
        InvokeIfRequired(Sub()
                             RaiseEvent PositionEnd(Me, EventArgs.Empty)
                         End Sub)
    End Sub

    Private Sub EWrapper_RealtimeBar(reqId As Integer, time As Long, open As Double, high As Double, low As Double, close As Double, volume As Decimal, WAP As Decimal, count As Integer) Implements IBApi.EWrapper.realtimeBar
        InvokeIfRequired(Sub()
                             RaiseEvent RealtimeBar(Me, New RealtimeBarEventArgs With {
                                                                     .reqId = reqId,
                                                                      .time = time,
                                                                      .open = open,
                                                                      .high = high,
                                                                      .low = low,
                                                                      .close = close,
                                                                      .volume = volume,
                                                                      .WAP = WAP,
                                                                      .count = count
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ReceiveFA(faDataType As Integer, faXmlData As String) Implements IBApi.EWrapper.receiveFA
        InvokeIfRequired(Sub()
                             RaiseEvent ReceiveFA(Me, New ReceiveFAEventArgs With {
                                                                     .faDataType = faDataType,
                                                                      .faXmlData = faXmlData
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ScannerData(reqId As Integer, rank As Integer, contractDetails As IBApi.ContractDetails, distance As String, benchmark As String, projection As String, legsStr As String) Implements IBApi.EWrapper.scannerData
        InvokeIfRequired(Sub()
                             RaiseEvent ScannerData(Me, New ScannerDataEventArgs With {
                                                                     .reqId = reqId,
                                                                      .rank = rank,
                                                                      .contractDetails = contractDetails,
                                                                      .distance = distance,
                                                                      .benchmark = benchmark,
                                                                      .projection = projection,
                                                                      .legsStr = legsStr
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ScannerDataEnd(reqId As Integer) Implements IBApi.EWrapper.scannerDataEnd
        InvokeIfRequired(Sub()
                             RaiseEvent ScannerDataEnd(Me, New ScannerDataEndEventArgs With {
                                                                     .reqId = reqId
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ScannerParameters(xml As String) Implements IBApi.EWrapper.scannerParameters
        InvokeIfRequired(Sub()
                             RaiseEvent ScannerParameters(Me, New ScannerParametersEventArgs With {
                                                                     .xml = xml
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_TickEFP(tickerId As Integer, tickType As Integer, basisPoints As Double, formattedBasisPoints As String, impliedFuture As Double, holdDays As Integer, futureLastTradeDate As String, dividendImpact As Double, dividendsToLastTradeDate As Double) Implements IBApi.EWrapper.tickEFP
        InvokeIfRequired(Sub()
                             RaiseEvent TickEFP(Me, New TickEFPEventArgs With {
                                                                                          .tickerId = tickerId,
                                                                                          .field = tickType,
                                                                                          .basisPoints = basisPoints,
                                                                                          .formattedBasisPoints = formattedBasisPoints,
                                                                                          .impliedFuture = impliedFuture,
                                                                                          .holdDays = holdDays,
                                                                                          .futureLastTradeDate = futureLastTradeDate,
                                                                                          .dividendImpact = dividendImpact,
                                                                                          .dividendsToLastTradeDate = dividendsToLastTradeDate
                                                                                      })
                         End Sub)
    End Sub

    Private Sub EWrapper_TickGeneric(tickerId As Integer, field As Integer, value As Double) Implements IBApi.EWrapper.tickGeneric
        InvokeIfRequired(Sub()
                             RaiseEvent TickGeneric(Me, New TickGenericEventArgs With {.id = tickerId, .tickType = field, .value = value})
                         End Sub)
    End Sub

    Private Sub EWrapper_TickOptionComputation(tickerId As Integer, field As Integer, tickAttrib As Integer, impliedVolatility As Double, delta As Double, optPrice As Double, pvDividend As Double, gamma As Double, vega As Double, theta As Double, undPrice As Double) Implements IBApi.EWrapper.tickOptionComputation
        InvokeIfRequired(Sub()
                             RaiseEvent TickOptionComputation(Me, New TickOptionComputationEventArgs With {
                                                                                                        .tickerId = tickerId,
                                                                                                        .tickType = field,
                                                                                                        .tickAttrib = tickAttrib,
                                                                                                        .impliedVolatility = impliedVolatility,
                                                                                                        .delta = delta,
                                                                                                        .optPrice = optPrice,
                                                                                                        .pvDividend = pvDividend,
                                                                                                        .gamma = gamma,
                                                                                                        .vega = vega,
                                                                                                        .theta = theta,
                                                                                                        .undPrice = undPrice
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_TickPrice(tickerId As Integer, field As Integer, price As Double, attribs As TickAttrib) Implements IBApi.EWrapper.tickPrice
        InvokeIfRequired(Sub()
                             RaiseEvent TickPrice(Me, New TickPriceEventArgs With {.id = tickerId, .price = price, .tickType = field, .attribs = attribs})
                         End Sub)
    End Sub

    Private Sub EWrapper_TickSize(tickerId As Integer, field As Integer, size As Decimal) Implements IBApi.EWrapper.tickSize
        InvokeIfRequired(Sub()
                             RaiseEvent TickSize(Me, New TickSizeEventArgs With {.id = tickerId, .size = size, .tickType = field})
                         End Sub)
    End Sub

    Private Sub EWrapper_TickSnapshotEnd(tickerId As Integer) Implements IBApi.EWrapper.tickSnapshotEnd
        InvokeIfRequired(Sub()
                             RaiseEvent TickSnapshotEnd(Me, New TickSnapshotEndEventArgs With {
                                                                     .tickerId = tickerId
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_TickString(tickerId As Integer, field As Integer, value As String) Implements IBApi.EWrapper.tickString
        InvokeIfRequired(Sub()
                             RaiseEvent TickString(Me, New TickStringEventArgs With {.id = tickerId, .tickType = field, .value = value})
                         End Sub)
    End Sub

    Private Sub EWrapper_UpdateAccountTime(timestamp As String) Implements IBApi.EWrapper.updateAccountTime
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateAccountTime(Me, New UpdateAccountTimeEventArgs With {
                                                                     .timestamp = timestamp
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_UpdateAccountValue(key As String, value As String, currency As String, accountName As String) Implements IBApi.EWrapper.updateAccountValue
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateAccountValue(Me, New UpdateAccountValueEventArgs With {
                                                                     .key = key,
                                                                      .value = value,
                                                                      .currency = currency,
                                                                      .accountName = accountName
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_UpdateMktDepth(tickerId As Integer, position As Integer, operation As Integer, side As Integer, price As Double, size As Decimal) Implements IBApi.EWrapper.updateMktDepth
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateMktDepth(Me, New UpdateMktDepthEventArgs With {
                                                                                                 .tickerId = tickerId,
                                                                                                 .position = position,
                                                                                                 .operation = operation,
                                                                                                 .side = side,
                                                                                                 .price = price,
                                                                                                 .size = size
                                                                                             })
                         End Sub)
    End Sub

    Private Sub EWrapper_UpdateMktDepthL2(tickerId As Integer, position As Integer, marketMaker As String, operation As Integer, side As Integer, price As Double, size As Decimal, isSmartDepth As Boolean) Implements IBApi.EWrapper.updateMktDepthL2
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateMktDepthL2(Me, New UpdateMktDepthL2EventArgs With {
                                                                                                   .tickerId = tickerId,
                                                                                                   .position = position,
                                                                                                   .marketMaker = marketMaker,
                                                                                                   .operation = operation,
                                                                                                   .side = side,
                                                                                                   .price = price,
                                                                                                   .size = size,
                                                                                                   .isSmartDepth = isSmartDepth
                                                                                               })
                         End Sub)
    End Sub

    Private Sub EWrapper_UpdateNewsBulletin(msgId As Integer, msgType As Integer, message As String, origExchange As String) Implements IBApi.EWrapper.updateNewsBulletin
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateNewsBulletin(Me, New UpdateNewsBulletinEventArgs With {
                                                                     .msgId = msgId,
                                                                      .msgType = msgType,
                                                                      .message = message,
                                                                      .origExchange = origExchange
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_UpdatePortfolio(contract As IBApi.Contract, position As Decimal, marketPrice As Double, marketValue As Double, averageCost As Double, unrealizedPNL As Double, realizedPNL As Double, accountName As String) Implements IBApi.EWrapper.updatePortfolio
        InvokeIfRequired(Sub()
                             RaiseEvent UpdatePortfolio(Me, New UpdatePortfolioEventArgs With {
                                                                     .contract = contract,
                                                                      .position = position,
                                                                      .marketPrice = marketPrice,
                                                                      .marketValue = marketValue,
                                                                      .averageCost = averageCost,
                                                                      .unrealizedPNL = unrealizedPNL,
                                                                      .realizedPNL = realizedPNL,
                                                                      .accountName = accountName
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_VerifyCompleted(isSuccessful As Boolean, errorText As String) Implements IBApi.EWrapper.verifyCompleted
        InvokeIfRequired(Sub()
                             RaiseEvent VerifyCompleted(Me, New VerifyCompletedEventArgs With {
                                                                     .isSuccessful = isSuccessful,
                                                                      .errorText = errorText
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_VerifyMessageAPI(apiData As String) Implements IBApi.EWrapper.verifyMessageAPI
        InvokeIfRequired(Sub()
                             RaiseEvent VerifyMessageAPI(Me, New VerifyMessageAPIEventArgs With {
                                                                     .apiData = apiData
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_VerifyAndAuthCompleted(isSuccessful As Boolean, errorText As String) Implements IBApi.EWrapper.verifyAndAuthCompleted
        InvokeIfRequired(Sub()
                             RaiseEvent VerifyAndAuthCompleted(Me, New VerifyAndAuthCompletedEventArgs With {
                                                                     .isSuccessful = isSuccessful,
                                                                     .errorText = errorText
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_VerifyAndAuthMessageAPI(apiData As String, xyzChallenge As String) Implements IBApi.EWrapper.verifyAndAuthMessageAPI
        InvokeIfRequired(Sub()
                             RaiseEvent VerifyAndAuthMessageAPI(Me, New VerifyAndAuthMessageAPIEventArgs With {
                                                                     .apiData = apiData,
                                                                     .xyzChallenge = xyzChallenge
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_ConnectAck() Implements EWrapper.connectAck
        If m_Api.AsyncEConnect Then
            m_Api.startApi()
        End If
    End Sub

    Private Sub EWrapper_PositionMulti(reqId As Integer, account As String, modelCode As String, contract As IBApi.Contract, pos As Decimal, avgCost As Double) Implements IBApi.EWrapper.positionMulti
        InvokeIfRequired(Sub()
                             RaiseEvent PositionMulti(Me, New PositionMultiEventArgs With {
                                                           .reqId = reqId,
                                                           .account = account,
                                                           .modelCode = modelCode,
                                                           .contract = contract,
                                                           .pos = pos,
                                                           .avgCost = avgCost
                                                           })
                         End Sub)
    End Sub

    Private Sub EWrapper_PositionMultiEnd(reqId As Integer) Implements IBApi.EWrapper.positionMultiEnd
        InvokeIfRequired(Sub()
                             RaiseEvent PositionMultiEnd(Me, New PositionMultiEndEventArgs With {
                                                              .reqId = reqId
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_AccountUpdateMulti(reqId As Integer, account As String, modelCode As String, key As String, value As String, currency As String) Implements IBApi.EWrapper.accountUpdateMulti
        InvokeIfRequired(Sub()
                             RaiseEvent AccountUpdateMulti(Me, New AccountUpdateMultiEventArgs With {
                                                                .reqId = reqId,
                                                                .account = account,
                                                                .modelCode = modelCode,
                                                                .key = key,
                                                                .value = value,
                                                                .currency = currency
                                                                })
                         End Sub)
    End Sub

    Private Sub EWrapper_AccountUpdateMultiEnd(reqId As Integer) Implements IBApi.EWrapper.accountUpdateMultiEnd
        InvokeIfRequired(Sub()
                             RaiseEvent AccountUpdateMultiEnd(Me, New AccountUpdateMultiEndEventArgs With {
                                                              .reqId = reqId
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_BondContractDetails(reqId As Integer, contractDetails As IBApi.ContractDetails) Implements IBApi.EWrapper.bondContractDetails
        InvokeIfRequired(Sub()
                             RaiseEvent BondContractDetails(Me, New BondContractDetailsEventArgs With {
                                                                     .reqId = reqId,
                                                                      .contractDetails = contractDetails
                                                                     })
                         End Sub)

    End Sub

    Private Sub EWrapper_SecurityDefinitionOptionParameter(reqId As Integer, exchange As String, underlyingConId As Integer, tradingClass As String, multiplier As String, expirations As HashSet(Of String), strikes As HashSet(Of Double)) Implements EWrapper.securityDefinitionOptionParameter
        InvokeIfRequired(Sub()
                             RaiseEvent SecurityDefinitionOptionParameter(Me, New SecurityDefinitionOptionParameterEventArgs With {
                                                                                .reqId = reqId,
                                                                                .exchange = exchange,
                                                                                .underlyingConId = underlyingConId,
                                                                                .tradingClass = tradingClass,
                                                                                .multiplier = multiplier,
                                                                                .expirations = expirations,
                                                                                .strikes = strikes
                                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_SecurityDefinitionOptionParameterEnd(reqId As Integer) Implements EWrapper.securityDefinitionOptionParameterEnd
        InvokeIfRequired(Sub()
                             RaiseEvent SecurityDefinitionOptionParameterEnd(Me, New SecurityDefinitionOptionParameterEndEventArgs With {
                                                              .reqId = reqId
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_FamilyCodes(familyCodes() As FamilyCode) Implements EWrapper.familyCodes
        InvokeIfRequired(Sub()
                             RaiseEvent FamilyCodes(Me, New FamilyCodesEventArgs With {
                                                              .familyCodes = familyCodes
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_SymbolSamples(reqId As Integer, contractDescriptions() As ContractDescription) Implements EWrapper.symbolSamples
        InvokeIfRequired(Sub()
                             RaiseEvent SymbolSamples(Me, New SymbolSamplesEventArgs With {
                                                            .reqId = reqId,
                                                            .contractDescriptions = contractDescriptions
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_SoftDollarTiers(requestId As Integer, tiers() As SoftDollarTier) Implements EWrapper.softDollarTiers

    End Sub

    Public Sub EWrapper_MktDepthExchanges(depthMktDataDescriptions() As DepthMktDataDescription) Implements EWrapper.mktDepthExchanges
        InvokeIfRequired(Sub()
                             RaiseEvent MktDepthExchanges(Me, New MktDepthExchangesEventArgs With {
                                                            .depthMktDataDescriptions = depthMktDataDescriptions
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_TickNews(tickerId As Integer, timeStamp As Long, providerCode As String, articleId As String, headline As String, extraData As String) Implements EWrapper.tickNews
        InvokeIfRequired(Sub()
                             RaiseEvent TickNews(Me, New TickNewsEventArgs With {
                                                            .tickerId = tickerId,
                                                            .timeStamp = timeStamp,
                                                            .providerCode = providerCode,
                                                            .articleId = articleId,
                                                            .headline = headline,
                                                            .extraData = extraData
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_smartComponents(reqId As Integer, theMap As Dictionary(Of Integer, KeyValuePair(Of String, Char))) Implements EWrapper.smartComponents
        InvokeIfRequired(Sub()
                             RaiseEvent SmartComponents(Me, New SmartComponentsEventArgs With {
                                                            .reqId = reqId,
                                                            .theMap = theMap
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickReqParams(tickerId As Integer, minTick As Double, bboExchange As String, snapshotPermissions As Integer) Implements EWrapper.tickReqParams
        InvokeIfRequired(Sub()
                             RaiseEvent TickReqParams(Me, New TickReqParamsEventArgs With {
                                                            .tickerId = tickerId,
                                                            .minTick = minTick,
                                                            .bboExchange = bboExchange,
                                                            .snapshotPermissions = snapshotPermissions
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_NewsProviders(newsProviders() As NewsProvider) Implements EWrapper.newsProviders
        InvokeIfRequired(Sub()
                             RaiseEvent NewsProviders(Me, New NewsProvidersEventArgs With {
                                                            .newsProviders = newsProviders
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_NewsArticle(requestId As Integer, articleType As Integer, articleText As String) Implements EWrapper.newsArticle
        InvokeIfRequired(Sub()
                             RaiseEvent NewsArticle(Me, New NewsArticleEventArgs With {
                                                            .requestId = requestId,
                                                            .articleType = articleType,
                                                            .articleText = articleText
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_HistoricalNews(requestId As Integer, time As String, providerCode As String, articleId As String, headline As String) Implements EWrapper.historicalNews
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalNews(Me, New HistoricalNewsEventArgs With {
                                                            .requestId = requestId,
                                                            .time = time,
                                                            .providerCode = providerCode,
                                                            .articleId = articleId,
                                                            .headline = headline
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_HistoricalNewsEnd(requestId As Integer, hasMore As Boolean) Implements EWrapper.historicalNewsEnd
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalNewsEnd(Me, New HistoricalNewsEndEventArgs With {
                                                            .requestId = requestId,
                                                            .hasMore = hasMore
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_RerouteMktDataReq(reqId As Integer, conId As Integer, exchange As String) Implements EWrapper.rerouteMktDataReq
        InvokeIfRequired(Sub()
                             RaiseEvent RerouteMktDataReq(Me, New RerouteMktDataReqEventArgs With {
                                                            .reqId = reqId,
                                                            .conId = conId,
                                                            .exchange = exchange
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_RerouteMktDepthReq(reqId As Integer, conId As Integer, exchange As String) Implements EWrapper.rerouteMktDepthReq
        InvokeIfRequired(Sub()
                             RaiseEvent RerouteMktDepthReq(Me, New RerouteMktDepthReqEventArgs With {
                                                            .reqId = reqId,
                                                            .conId = conId,
                                                            .exchange = exchange
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_MarketRule(marketRuleId As Integer, priceIncrements() As PriceIncrement) Implements EWrapper.marketRule
        InvokeIfRequired(Sub()
                             RaiseEvent MarketRule(Me, New MarketRuleEventArgs With {
                                                            .marketRuleId = marketRuleId,
                                                            .priceIncrements = priceIncrements
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_HistoricalTicks(reqId As Integer, ticks As HistoricalTick(), done As Boolean) Implements EWrapper.historicalTicks
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalTicks(Me, New HistoricalTicksEventArgs With {
                                                            .reqId = reqId,
                                                            .ticks = ticks
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_HistoricalTicksBidAsk(reqId As Integer, ticks As HistoricalTickBidAsk(), done As Boolean) Implements EWrapper.historicalTicksBidAsk
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalTicksBidAsk(Me, New HistoricalTicksBidAskEventArgs With {
                                                            .reqId = reqId,
                                                            .ticks = ticks
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_HistoricalTicksLast(reqId As Integer, ticks As HistoricalTickLast(), done As Boolean) Implements EWrapper.historicalTicksLast
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalTicksLast(Me, New HistoricalTicksLastEventArgs With {
                                                            .reqId = reqId,
                                                            .ticks = ticks
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_TickByTickAllLast(reqId As Integer, tickType As Integer, time As Long, price As Double, size As Decimal,
                                          tickAttribLast As TickAttribLast, exchange As String, specialConditions As String) Implements EWrapper.tickByTickAllLast
        InvokeIfRequired(Sub()
                             RaiseEvent TickByTickAllLast(Me, New TickByTickAllLastEventArgs With {
                                                            .reqId = reqId,
                                                            .tickType = tickType,
                                                            .time = time,
                                                            .price = price,
                                                            .size = size,
                                                            .tickAttribLast = tickAttribLast,
                                                            .exchange = exchange,
                                                            .specialConditions = specialConditions 
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_TickByTickBidAsk(reqId As Integer, time As Long, bidPrice As Double, askPrice As Double, bidSize As Decimal, askSize As Decimal, tickAttribBidAsk As TickAttribBidAsk) Implements EWrapper.tickByTickBidAsk
        InvokeIfRequired(Sub()
                             RaiseEvent TickByTickBidAsk(Me, New TickByTickBidAskEventArgs With {
                                                            .reqId = reqId,
                                                            .time = time,
                                                            .bidPrice = bidPrice,
                                                            .askPrice = askPrice,
                                                            .bidSize = bidSize,
                                                            .askSize = askSize,
                                                            .tickAttribBidAsk = tickAttribBidAsk
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_TickByTickMidPoint(reqId As Integer, time As Long, midPoint As Double) Implements EWrapper.tickByTickMidPoint
        InvokeIfRequired(Sub()
                             RaiseEvent TickByTickMidPoint(Me, New TickByTickMidPointEventArgs With {
                                                            .reqId = reqId,
                                                            .time = time,
                                                            .midPoint = midPoint
                                                            })
                         End Sub)
    End Sub

    Public Sub EWrapper_OrderBound(permId As Long, clientId As Integer, orderId As Integer) Implements EWrapper.orderBound
        InvokeIfRequired(Sub()
                             RaiseEvent OrderBound(Me, New OrderBoundEventArgs With {
                                                            .permId = permId,
                                                            .clientId = clientId,
                                                            .orderId = orderId
                                                            })
                         End Sub)
    End Sub

    Private Sub EWrapper_CompletedOrder(contract As IBApi.Contract, order As IBApi.Order, orderState As IBApi.OrderState) Implements IBApi.EWrapper.completedOrder
        InvokeIfRequired(Sub()
                             RaiseEvent CompletedOrder(Me, New OpenOrderEventArgs With {
                                                                      .contract = contract,
                                                                      .order = order,
                                                                      .orderState = orderState
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_CompletedOrdersEnd() Implements IBApi.EWrapper.completedOrdersEnd
        InvokeIfRequired(Sub()
                             RaiseEvent CompletedOrdersEnd(Me, EventArgs.Empty)
                         End Sub)
    End Sub
    Private Sub EWrapper_ReplaceFAEnd(reqId As Integer, text As String) Implements IBApi.EWrapper.replaceFAEnd
        InvokeIfRequired(Sub()
                             RaiseEvent ReplaceFAEnd(Me, New ReplaceFAEndEventArgs With {
                                                              .reqId = reqId,
                                                              .text = text
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_wshMetaData(reqId As Integer, dataJson As String) Implements EWrapper.wshMetaData
        InvokeIfRequired(Sub()
                             RaiseEvent WshMetaData(Me, New WshMetaDataEventArgs With {
                                                              .reqId = reqId,
                                                              .dataJson = dataJson
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_wshEventData(reqId As Integer, dataJson As String) Implements EWrapper.wshEventData
        InvokeIfRequired(Sub()
                             RaiseEvent WshEventData(Me, New WshEventDataEventArgs With {
                                                              .reqId = reqId,
                                                              .dataJson = dataJson
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_historicalSchedule(reqId As Integer, startDateTime As String, endDateTime As String, timeZone As String, sessions As HistoricalSession()) Implements EWrapper.historicalSchedule
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalSchedule(Me, New HistoricalScheduleEventArgs With {
                                                              .reqId = reqId,
                                                              .startDateTime = startDateTime,
                                                              .endDateTime = endDateTime,
                                                              .timeZone = timeZone,
                                                             .sessions = sessions
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_userInfo(reqId As Integer, whiteBrandingId As String) Implements EWrapper.userInfo
        InvokeIfRequired(Sub()
                             RaiseEvent UserInfo(Me, New UserInfoEventArgs With {
                                                              .reqId = reqId,
                                                              .whiteBrandingId = whiteBrandingId
                                                              })
                         End Sub)
    End Sub

    Private Sub EWrapper_CurrentTimeInMillis(timeInMillis As Long) Implements IBApi.EWrapper.currentTimeInMillis
        InvokeIfRequired(Sub()
                             RaiseEvent CurrentTimeInMillis(Me, New CurrentTimeInMillisEventArgs With {
                                                                     .timeInMillis = timeInMillis
                                                                     })
                         End Sub)
    End Sub

    '! [protobuf]
    Public Sub EWrapper_OrderStatusProtoBuf(orderStatusProto As IBApi.protobuf.OrderStatus) Implements IBApi.EWrapper.orderStatusProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent OrderStatusProtoBuf(Me, New OrderStatusProtoBufEventArgs With {
                                                                     .orderStatusProto = orderStatusProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_OpenOrderProtoBuf(openOrderProto As IBApi.protobuf.OpenOrder) Implements IBApi.EWrapper.openOrderProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent OpenOrderProtoBuf(Me, New OpenOrderProtoBufEventArgs With {
                                                                     .OpenOrderProto = openOrderProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_OpenOrdersEndProtoBuf(openOrdersEndProto As IBApi.protobuf.OpenOrdersEnd) Implements IBApi.EWrapper.openOrdersEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent OpenOrdersEndProtoBuf(Me, New OpenOrdersEndProtoBufEventArgs With {
                                                                     .OpenOrdersEndProto = openOrdersEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_ErrorMessageProtoBuf(errorMessageProto As IBApi.protobuf.ErrorMessage) Implements IBApi.EWrapper.errorProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ErrorMessageProtoBuf(Me, New ErrorMessageProtoBufEventArgs With {
                                                                     .ErrorMessageProto = errorMessageProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_ExecutionDetailsProtoBuf(executionDetailsProto As IBApi.protobuf.ExecutionDetails) Implements IBApi.EWrapper.execDetailsProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ExecutionDetailsProtoBuf(Me, New ExecutionDetailsProtoBufEventArgs With {
                                                                     .ExecutionDetailsProto = executionDetailsProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_ExecutionDetailsEndProtoBuf(executionDetailsEndProto As IBApi.protobuf.ExecutionDetailsEnd) Implements IBApi.EWrapper.execDetailsEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ExecutionDetailsEndProtoBuf(Me, New ExecutionDetailsEndProtoBufEventArgs With {
                                                                     .ExecutionDetailsEndProto = executionDetailsEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_CompletedOrderProtoBuf(completedOrderProto As IBApi.protobuf.CompletedOrder) Implements IBApi.EWrapper.completedOrderProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent CompletedOrderProtoBuf(Me, New CompletedOrderProtoBufEventArgs With {
                                                                     .CompletedOrderProto = completedOrderProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_CompletedOrdersEndProtoBuf(completedOrdersEndProto As IBApi.protobuf.CompletedOrdersEnd) Implements IBApi.EWrapper.completedOrdersEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent CompletedOrdersEndProtoBuf(Me, New CompletedOrdersEndProtoBufEventArgs With {
                                                                     .CompletedOrdersEndProto = completedOrdersEndProto
                                                                     })
                         End Sub)
    End Sub
    Public Sub EWrapper_OrderBoundProtoBuf(orderBoundProto As IBApi.protobuf.OrderBound) Implements IBApi.EWrapper.orderBoundProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent OrderBoundProtoBuf(Me, New OrderBoundProtoBufEventArgs With {
                                                                     .OrderBoundProto = orderBoundProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_ContractDataProtoBuf(contractDataProto As IBApi.protobuf.ContractData) Implements IBApi.EWrapper.contractDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ContractDataProtoBuf(Me, New ContractDataProtoBufEventArgs With {
                                                                     .ContractDataProto = contractDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_BondContractDataProtoBuf(contractDataProto As IBApi.protobuf.ContractData) Implements IBApi.EWrapper.bondContractDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent BondContractDataProtoBuf(Me, New ContractDataProtoBufEventArgs With {
                                                                     .ContractDataProto = contractDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_contractDataEndProtoBuf(contractDataEndProto As IBApi.protobuf.ContractDataEnd) Implements IBApi.EWrapper.contractDataEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ContractDataEndProtoBuf(Me, New ContractDataEndProtoBufEventArgs With {
                                                                     .ContractDataEndProto = contractDataEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickPriceProtoBuf(tickPriceProto As IBApi.protobuf.TickPrice) Implements IBApi.EWrapper.tickPriceProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickPriceProtoBuf(Me, New TickPriceProtoBufEventArgs With {
                                                                     .TickPriceProto = tickPriceProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickSizeProtoBuf(tickSizeProto As IBApi.protobuf.TickSize) Implements IBApi.EWrapper.tickSizeProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickSizeProtoBuf(Me, New TickSizeProtoBufEventArgs With {
                                                                     .TickSizeProto = tickSizeProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickOptionComputationProtoBuf(tickOptionComputationProto As IBApi.protobuf.TickOptionComputation) Implements IBApi.EWrapper.tickOptionComputationProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickOptionComputationProtoBuf(Me, New TickOptionComputationProtoBufEventArgs With {
                                                                     .TickOptionComputationProto = tickOptionComputationProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickGenericProtoBuf(tickGenericProto As IBApi.protobuf.TickGeneric) Implements IBApi.EWrapper.tickGenericProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickGenericProtoBuf(Me, New TickGenericProtoBufEventArgs With {
                                                                     .TickGenericProto = tickGenericProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickStringProtoBuf(tickStringProto As IBApi.protobuf.TickString) Implements IBApi.EWrapper.tickStringProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickStringProtoBuf(Me, New TickStringProtoBufEventArgs With {
                                                                     .TickStringProto = tickStringProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickSnapshotEndProtoBuf(tickSnapshotEndProto As IBApi.protobuf.TickSnapshotEnd) Implements IBApi.EWrapper.tickSnapshotEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickSnapshotEndProtoBuf(Me, New TickSnapshotEndProtoBufEventArgs With {
                                                                     .TickSnapshotEndProto = tickSnapshotEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_updateMarketDepthProtoBuf(marketDepthProto As IBApi.protobuf.MarketDepth) Implements IBApi.EWrapper.updateMarketDepthProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateMarketDepthProtoBuf(Me, New UpdateMarketDepthProtoBufEventArgs With {
                                                                     .marketDepthProto = marketDepthProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_updateMarketDepthL2ProtoBuf(marketDepthL2Proto As IBApi.protobuf.MarketDepthL2) Implements IBApi.EWrapper.updateMarketDepthL2ProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateMarketDepthL2ProtoBuf(Me, New UpdateMarketDepthL2ProtoBufEventArgs With {
                                                                     .marketDepthL2Proto = marketDepthL2Proto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_marketDataTypeProtoBuf(marketDataTypeProto As IBApi.protobuf.MarketDataType) Implements IBApi.EWrapper.marketDataTypeProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent marketDataTypeProtoBuf(Me, New MarketDataTypeProtoBufEventArgs With {
                                                                     .marketDataTypeProto = marketDataTypeProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickReqParamsProtoBuf(tickReqParamsProto As IBApi.protobuf.TickReqParams) Implements IBApi.EWrapper.tickReqParamsProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickReqParamsProtoBuf(Me, New TickReqParamsProtoBufEventArgs With {
                                                                     .TickReqParamsProto = tickReqParamsProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_updateAccountValueProtoBuf(accountValueProto As IBApi.protobuf.AccountValue) Implements IBApi.EWrapper.updateAccountValueProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateAccountValueProtoBuf(Me, New UpdateAccountValueProtoBufEventArgs With {
                                                                     .accountValueProto = accountValueProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_updatePortfolioProtoBuf(portfolioValueProto As IBApi.protobuf.PortfolioValue) Implements IBApi.EWrapper.updatePortfolioProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UpdatePortfolioProtoBuf(Me, New UpdatePortfolioProtoBufEventArgs With {
                                                                     .portfolioValueProto = portfolioValueProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_updateAccountTimeProtoBuf(accountUpdateTimeProto As IBApi.protobuf.AccountUpdateTime) Implements IBApi.EWrapper.updateAccountTimeProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateAccountTimeProtoBuf(Me, New UpdateAccountTimeProtoBufEventArgs With {
                                                                     .accountUpdateTimeProto = accountUpdateTimeProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_accountDataEndProtoBuf(accountDataEndProto As IBApi.protobuf.AccountDataEnd) Implements IBApi.EWrapper.accountDataEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent AccountDataEndProtoBuf(Me, New AccountDataEndProtoBufEventArgs With {
                                                                     .accountDataEndProto = accountDataEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_managedAccountsProtoBuf(managedAccountsProto As IBApi.protobuf.ManagedAccounts) Implements IBApi.EWrapper.managedAccountsProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ManagedAccountsProtoBuf(Me, New ManagedAccountsProtoBufEventArgs With {
                                                                     .managedAccountsProto = managedAccountsProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_positionProtoBuf(positionProto As IBApi.protobuf.Position) Implements IBApi.EWrapper.positionProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent PositionProtoBuf(Me, New PositionProtoBufEventArgs With {
                                                                     .positionProto = positionProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_positionEndProtoBuf(positionEndProto As IBApi.protobuf.PositionEnd) Implements IBApi.EWrapper.positionEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent PositionEndProtoBuf(Me, New PositionEndProtoBufEventArgs With {
                                                                     .positionEndProto = positionEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_accountSummaryProtoBuf(accountSummaryProto As IBApi.protobuf.AccountSummary) Implements IBApi.EWrapper.accountSummaryProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent AccountSummaryProtoBuf(Me, New AccountSummaryProtoBufEventArgs With {
                                                                     .accountSummaryProto = accountSummaryProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_accountSummaryEndProtoBuf(accountSummaryEndProto As IBApi.protobuf.AccountSummaryEnd) Implements IBApi.EWrapper.accountSummaryEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent AccountSummaryEndProtoBuf(Me, New AccountSummaryEndProtoBufEventArgs With {
                                                                     .accountSummaryEndProto = accountSummaryEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_positionMultiProtoBuf(positionMultiProto As IBApi.protobuf.PositionMulti) Implements IBApi.EWrapper.positionMultiProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent PositionMultiProtoBuf(Me, New PositionMultiProtoBufEventArgs With {
                                                                     .positionMultiProto = positionMultiProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_positionMultiEndProtoBuf(positionMultiEndProto As IBApi.protobuf.PositionMultiEnd) Implements IBApi.EWrapper.positionMultiEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent PositionMultiEndProtoBuf(Me, New PositionMultiEndProtoBufEventArgs With {
                                                                     .positionMultiEndProto = positionMultiEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_accountUpdateMultiProtoBuf(accountUpdateMultiProto As IBApi.protobuf.AccountUpdateMulti) Implements IBApi.EWrapper.accountUpdateMultiProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent AccountUpdateMultiProtoBuf(Me, New AccountUpdateMultiProtoBufEventArgs With {
                                                                     .accountUpdateMultiProto = accountUpdateMultiProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_accountUpdateMultiEndProtoBuf(accountUpdateMultiEndProto As IBApi.protobuf.AccountUpdateMultiEnd) Implements IBApi.EWrapper.accountUpdateMultiEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent AccountUpdateMultiEndProtoBuf(Me, New AccountUpdateMultiEndProtoBufEventArgs With {
                                                                     .accountUpdateMultiEndProto = accountUpdateMultiEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalDataProtoBuf(historicalDataProto As IBApi.protobuf.HistoricalData) Implements IBApi.EWrapper.historicalDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalDataProtoBuf(Me, New HistoricalDataProtoBufEventArgs With {
                                                                     .historicalDataProto = historicalDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalDataUpdateProtoBuf(historicalDataUpdateProto As IBApi.protobuf.HistoricalDataUpdate) Implements IBApi.EWrapper.historicalDataUpdateProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalDataUpdateProtoBuf(Me, New HistoricalDataUpdateProtoBufEventArgs With {
                                                                     .historicalDataUpdateProto = historicalDataUpdateProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalDataEndProtoBuf(historicalDataEndProto As IBApi.protobuf.HistoricalDataEnd) Implements IBApi.EWrapper.historicalDataEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalDataEndProtoBuf(Me, New HistoricalDataEndProtoBufEventArgs With {
                                                                     .historicalDataEndProto = historicalDataEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_realTimeBarTickProtoBuf(realTimeBarTickProto As IBApi.protobuf.RealTimeBarTick) Implements IBApi.EWrapper.realTimeBarTickProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent RealTimeBarTickProtoBuf(Me, New RealTimeBarTickProtoBufEventArgs With {
                                                                     .realTimeBarTickProto = realTimeBarTickProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_headTimestampProtoBuf(headTimestampProto As IBApi.protobuf.HeadTimestamp) Implements IBApi.EWrapper.headTimestampProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HeadTimestampProtoBuf(Me, New HeadTimestampProtoBufEventArgs With {
                                                                     .headTimestampProto = headTimestampProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_histogramDataProtoBuf(histogramDataProto As IBApi.protobuf.HistogramData) Implements IBApi.EWrapper.histogramDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistogramDataProtoBuf(Me, New HistogramDataProtoBufEventArgs With {
                                                                     .histogramDataProto = histogramDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalTicksProtoBuf(historicalTicksProto As IBApi.protobuf.HistoricalTicks) Implements IBApi.EWrapper.historicalTicksProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalTicksProtoBuf(Me, New HistoricalTicksProtoBufEventArgs With {
                                                                     .historicalTicksProto = historicalTicksProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalTicksBidAskProtoBuf(historicalTicksBidAskProto As IBApi.protobuf.HistoricalTicksBidAsk) Implements IBApi.EWrapper.historicalTicksBidAskProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalTicksBidAskProtoBuf(Me, New HistoricalTicksBidAskProtoBufEventArgs With {
                                                                     .historicalTicksBidAskProto = historicalTicksBidAskProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalTicksLastProtoBuf(historicalTicksLastProto As IBApi.protobuf.HistoricalTicksLast) Implements IBApi.EWrapper.historicalTicksLastProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalTicksLastProtoBuf(Me, New HistoricalTicksLastProtoBufEventArgs With {
                                                                     .historicalTicksLastProto = historicalTicksLastProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickByTickDataProtoBuf(tickByTickDataProto As IBApi.protobuf.TickByTickData) Implements IBApi.EWrapper.tickByTickDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickByTickDataProtoBuf(Me, New TickByTickDataProtoBufEventArgs With {
                                                                     .tickByTickDataProto = tickByTickDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_updateNewsBulletinProtoBuf(newsBulletinProto As IBApi.protobuf.NewsBulletin) Implements IBApi.EWrapper.updateNewsBulletinProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateNewsBulletinProtoBuf(Me, New UpdateNewsBulletinProtoBufEventArgs With {
                                                                     .UpdateNewsBulletinProto = newsBulletinProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_newsArticleProtoBuf(newsArticleProto As IBApi.protobuf.NewsArticle) Implements IBApi.EWrapper.newsArticleProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent NewsArticleProtoBuf(Me, New NewsArticleProtoBufEventArgs With {
                                                                     .newsArticleProto = newsArticleProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_newsProvidersProtoBuf(newsProvidersProto As IBApi.protobuf.NewsProviders) Implements IBApi.EWrapper.newsProvidersProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent NewsProvidersProtoBuf(Me, New NewsProvidersProtoBufEventArgs With {
                                                                     .newsProvidersProto = newsProvidersProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalNewsProtoBuf(historicalNewsProto As IBApi.protobuf.HistoricalNews) Implements IBApi.EWrapper.historicalNewsProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalNewsProtoBuf(Me, New HistoricalNewsProtoBufEventArgs With {
                                                                     .historicalNewsProto = historicalNewsProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_historicalNewsEndProtoBuf(historicalNewsEndProto As IBApi.protobuf.HistoricalNewsEnd) Implements IBApi.EWrapper.historicalNewsEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalNewsEndProtoBuf(Me, New HistoricalNewsEndProtoBufEventArgs With {
                                                                     .historicalNewsEndProto = historicalNewsEndProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_wshMetaDataProtoBuf(wshMetaDataProto As IBApi.protobuf.WshMetaData) Implements IBApi.EWrapper.wshMetaDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent WshMetaDataProtoBuf(Me, New WshMetaDataProtoBufEventArgs With {
                                                                     .wshMetaDataProto = wshMetaDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_wshEventDataProtoBuf(wshEventDataProto As IBApi.protobuf.WshEventData) Implements IBApi.EWrapper.wshEventDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent WshEventDataProtoBuf(Me, New WshEventDataProtoBufEventArgs With {
                                                                     .wshEventDataProto = wshEventDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_tickNewsProtoBuf(tickNewsProto As IBApi.protobuf.TickNews) Implements IBApi.EWrapper.tickNewsProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent TickNewsProtoBuf(Me, New TickNewsProtoBufEventArgs With {
                                                                     .tickNewsProto = tickNewsProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_scannerParametersProtoBuf(scannerParametersProto As IBApi.protobuf.ScannerParameters) Implements IBApi.EWrapper.scannerParametersProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ScannerParametersProtoBuf(Me, New ScannerParametersProtoBufEventArgs With {
                                                                     .scannerParametersProto = scannerParametersProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_scannerDataProtoBuf(scannerDataProto As IBApi.protobuf.ScannerData) Implements IBApi.EWrapper.scannerDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ScannerDataProtoBuf(Me, New ScannerDataProtoBufEventArgs With {
                                                                     .scannerDataProto = scannerDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_fundamentalsDataProtoBuf(fundamentalsDataProto As IBApi.protobuf.FundamentalsData) Implements IBApi.EWrapper.fundamentalsDataProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent FundamentalsDataProtoBuf(Me, New FundamentalsDataProtoBufEventArgs With {
                                                                     .fundamentalsDataProto = fundamentalsDataProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_pnlProtoBuf(pnlProto As IBApi.protobuf.PnL) Implements IBApi.EWrapper.pnlProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent PnLProtoBuf(Me, New PnLProtoBufEventArgs With {
                                                                     .pnlProto = pnlProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_pnlSingleProtoBuf(pnlSingleProto As IBApi.protobuf.PnLSingle) Implements IBApi.EWrapper.pnlSingleProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent PnLSingleProtoBuf(Me, New PnLSingleProtoBufEventArgs With {
                                                                     .pnlSingleProto = pnlSingleProto
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_receiveFAProtoBuf(receiveFAProto As IBApi.protobuf.ReceiveFA) Implements IBApi.EWrapper.receiveFAProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ReceiveFAProtoBuf(Me, New ReceiveFAProtoBufEventArgs With {
                                                                     .receiveFAProto = receiveFAProto
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_replaceFAEndProtoBuf(replaceFAEndProto As IBApi.protobuf.ReplaceFAEnd) Implements IBApi.EWrapper.replaceFAEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ReplaceFAEndProtoBuf(Me, New ReplaceFAEndProtoBufEventArgs With {
                                                                     .replaceFAEndProto = replaceFAEndProto
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_commissionAndFeesReportProtoBuf(commissionAndFeesReportProto As IBApi.protobuf.CommissionAndFeesReport) Implements IBApi.EWrapper.commissionAndFeesReportProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent CommissionAndFeesReportProtoBuf(Me, New CommissionAndFeesReportProtoBufEventArgs With {
                                                                     .commissionAndFeesReportProto = commissionAndFeesReportProto
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_historicalScheduleProtoBuf(historicalScheduleProto As IBApi.protobuf.HistoricalSchedule) Implements IBApi.EWrapper.historicalScheduleProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent HistoricalScheduleProtoBuf(Me, New HistoricalScheduleProtoBufEventArgs With {
                                                                     .historicalScheduleProto = historicalScheduleProto
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_rerouteMarketDataRequestProtoBuf(rerouteMarketDataRequestProto As IBApi.protobuf.RerouteMarketDataRequest) Implements IBApi.EWrapper.rerouteMarketDataRequestProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent RerouteMarketDataRequestProtoBuf(Me, New RerouteMarketDataRequestProtoBufEventArgs With {
                                                                     .rerouteMarketDataRequestProto = rerouteMarketDataRequestProto
                                                                     })
                         End Sub)
    End Sub

    Private Sub EWrapper_rerouteMarketDepthRequestProtoBuf(rerouteMarketDepthRequestProto As IBApi.protobuf.RerouteMarketDepthRequest) Implements IBApi.EWrapper.rerouteMarketDepthRequestProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent RerouteMarketDepthRequestProtoBuf(Me, New RerouteMarketDepthRequestProtoBufEventArgs With {
                                                                     .rerouteMarketDepthRequestProto = rerouteMarketDepthRequestProto
                                                                     })
                         End Sub)
    End Sub

    Public Sub EWrapper_secDefOptParameterProtoBuf(secDefOptParameterProto As IBApi.protobuf.SecDefOptParameter) Implements IBApi.EWrapper.secDefOptParameterProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent SecDefOptParameterProtoBuf(Me, New SecDefOptParameterProtoBufEventArgs With {
                                                                  .secDefOptParameterProto = secDefOptParameterProto
                                                              })
                         End Sub)
    End Sub

    Public Sub EWrapper_secDefOptParameterEndProtoBuf(secDefOptParameterEndProto As IBApi.protobuf.SecDefOptParameterEnd) Implements IBApi.EWrapper.secDefOptParameterEndProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent SecDefOptParameterEndProtoBuf(Me, New SecDefOptParameterEndProtoBufEventArgs With {
                                                                     .secDefOptParameterEndProto = secDefOptParameterEndProto
                                                                 })
                         End Sub)
    End Sub

    Public Sub EWrapper_softDollarTiersProtoBuf(softDollarTiersProto As IBApi.protobuf.SoftDollarTiers) Implements IBApi.EWrapper.softDollarTiersProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent SoftDollarTiersProtoBuf(Me, New SoftDollarTiersProtoBufEventArgs With {
                                                               .softDollarTiersProto = softDollarTiersProto
                                                           })
                         End Sub)
    End Sub

    Public Sub EWrapper_familyCodesProtoBuf(familyCodesProto As IBApi.protobuf.FamilyCodes) Implements IBApi.EWrapper.familyCodesProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent FamilyCodesProtoBuf(Me, New FamilyCodesProtoBufEventArgs With {
                                                           .familyCodesProto = familyCodesProto
                                                       })
                         End Sub)
    End Sub

    Public Sub EWrapper_symbolSamplesProtoBuf(symbolSamplesProto As IBApi.protobuf.SymbolSamples) Implements IBApi.EWrapper.symbolSamplesProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent SymbolSamplesProtoBuf(Me, New SymbolSamplesProtoBufEventArgs With {
                                                             .symbolSamplesProto = symbolSamplesProto
                                                         })
                         End Sub)
    End Sub

    Public Sub EWrapper_smartComponentsProtoBuf(smartComponentsProto As IBApi.protobuf.SmartComponents) Implements IBApi.EWrapper.smartComponentsProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent SmartComponentsProtoBuf(Me, New SmartComponentsProtoBufEventArgs With {
                                                               .smartComponentsProto = smartComponentsProto
                                                           })
                         End Sub)
    End Sub

    Public Sub EWrapper_marketRuleProtoBuf(marketRuleProto As IBApi.protobuf.MarketRule) Implements IBApi.EWrapper.marketRuleProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent MarketRuleProtoBuf(Me, New MarketRuleProtoBufEventArgs With {
                                                          .marketRuleProto = marketRuleProto
                                                      })
                         End Sub)
    End Sub

    Public Sub EWrapper_userInfoProtoBuf(userInfoProto As IBApi.protobuf.UserInfo) Implements IBApi.EWrapper.userInfoProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UserInfoProtoBuf(Me, New UserInfoProtoBufEventArgs With {
                                                        .userInfoProto = userInfoProto
                                                    })
                         End Sub)
    End Sub

    Private Sub EWrapper_nextValidIdProtoBuf(nextValidIdProto As IBApi.protobuf.NextValidId) Implements IBApi.EWrapper.nextValidIdProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent NextValidIdProtoBuf(Me, New NextValidIdProtoBufEventArgs With {
                                                                 .nextValidIdProto = nextValidIdProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_currentTimeProtoBuf(currentTimeProto As IBApi.protobuf.CurrentTime) Implements IBApi.EWrapper.currentTimeProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent CurrentTimeProtoBuf(Me, New CurrentTimeProtoBufEventArgs With {
                                                                 .currentTimeProto = currentTimeProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_currentTimeInMillisProtoBuf(currentTimeInMillisProto As IBApi.protobuf.CurrentTimeInMillis) Implements IBApi.EWrapper.currentTimeInMillisProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent CurrentTimeInMillisProtoBuf(Me, New CurrentTimeInMillisProtoBufEventArgs With {
                                                                 .currentTimeInMillisProto = currentTimeInMillisProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_verifyMessageApiProtoBuf(verifyMessageApiProto As IBApi.protobuf.VerifyMessageApi) Implements IBApi.EWrapper.verifyMessageApiProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent VerifyMessageApiProtoBuf(Me, New VerifyMessageApiProtoBufEventArgs With {
                                                                 .verifyMessageApiProto = verifyMessageApiProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_verifyCompletedProtoBuf(verifyCompletedProto As IBApi.protobuf.VerifyCompleted) Implements IBApi.EWrapper.verifyCompletedProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent VerifyCompletedProtoBuf(Me, New VerifyCompletedProtoBufEventArgs With {
                                                                 .verifyCompletedProto = verifyCompletedProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_displayGroupListProtoBuf(displayGroupListProto As IBApi.protobuf.DisplayGroupList) Implements IBApi.EWrapper.displayGroupListProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent DisplayGroupListProtoBuf(Me, New DisplayGroupListProtoBufEventArgs With {
                                                                 .displayGroupListProto = displayGroupListProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_displayGroupUpdatedProtoBuf(displayGroupUpdatedProto As IBApi.protobuf.DisplayGroupUpdated) Implements IBApi.EWrapper.displayGroupUpdatedProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent DisplayGroupUpdatedProtoBuf(Me, New DisplayGroupUpdatedProtoBufEventArgs With {
                                                                 .displayGroupUpdatedProto = displayGroupUpdatedProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_marketDepthExchangesProtoBuf(marketDepthExchangesProto As IBApi.protobuf.MarketDepthExchanges) Implements IBApi.EWrapper.marketDepthExchangesProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent MarketDepthExchangesProtoBuf(Me, New MarketDepthExchangesProtoBufEventArgs With {
                                                                 .marketDepthExchangesProto = marketDepthExchangesProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_configResponseProtoBuf(configResponseProto As IBApi.protobuf.ConfigResponse) Implements IBApi.EWrapper.configResponseProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent ConfigResponseProtoBuf(Me, New ConfigResponseProtoBufEventArgs With {
                                                                 .configResponseProto = configResponseProto
                                                                 })
                         End Sub)
    End Sub

    Private Sub EWrapper_updateConfigResponseProtoBuf(updateConfigResponseProto As IBApi.protobuf.UpdateConfigResponse) Implements IBApi.EWrapper.updateConfigResponseProtoBuf
        InvokeIfRequired(Sub()
                             RaiseEvent UpdateConfigResponseProtoBuf(Me, New UpdateConfigResponseProtoBufEventArgs With {
                                                                 .updateConfigResponseProto = updateConfigResponseProto
                                                                 })
                         End Sub)
    End Sub
    '! [protobuf]

#End Region

#Region "Event declarations"

    Event PnLSingle(sender As ApiEventSource, e As PnLSingleEventArgs)
    Event PnL(sender As ApiEventSource, e As PnLEventArgs)
    Event HistogramData(sender As ApiEventSource, e As HistogramDataEventArgs)
    Event HeadTimestamp(sender As ApiEventSource, e As HeadTimestampEventArgs)
    Event NextValidId(sender As Object, e As NextValidIdEventArgs)
    Event ErrMsg(sender As Object, e As ErrMsgEventArgs)
    Event ConnectionClosed(sender As Object, e As System.EventArgs)
    Event TickPrice(sender As Object, e As TickPriceEventArgs)
    Event TickSize(sender As Object, e As TickSizeEventArgs)
    Event TickGeneric(sender As Object, e As TickGenericEventArgs)
    Event TickString(sender As Object, e As TickStringEventArgs)
    Event TickEFP(sender As Object, e As TickEFPEventArgs)
    Event TickOptionComputation(sender As Object, e As TickOptionComputationEventArgs)
    Event UpdateMktDepth(sender As Object, e As UpdateMktDepthEventArgs)
    Event AccountDownloadEnd(sender As Object, e As AccountDownloadEndEventArgs)
    Event AccountSummary(sender As Object, e As AccountSummaryEventArgs)
    Event AccountSummaryEnd(sender As Object, e As AccountSummaryEndEventArgs)
    Event CommissionAndFeesReport(sender As Object, e As CommissionAndFeesReportEventArgs)
    Event ContractDetails(sender As Object, e As ContractDetailsEventArgs)
    Event ContractDetailsEnd(sender As Object, e As ContractDetailsEndEventArgs)
    Event CurrentTime(sender As Object, e As CurrentTimeEventArgs)
    Event AccountUpdateMulti(sender As Object, e As AccountUpdateMultiEventArgs)
    Event AccountUpdateMultiEnd(sender As Object, e As AccountUpdateMultiEndEventArgs)
    Event DeltaNeutralValidation(sender As Object, e As DeltaNeutralValidationEventArgs)
    Event DisplayGroupList(sender As Object, e As DisplayGroupListEventArgs)
    Event DisplayGroupUpdated(sender As Object, e As DisplayGroupUpdatedEventArgs)
    Event ExecDetailsEnd(sender As Object, e As ExecDetailsEndEventArgs)
    Event ExecDetails(sender As Object, e As ExecDetailsEventArgs)
    Event FundamentalData(sender As Object, e As FundamentalDataEventArgs)
    Event HistoricalData(sender As Object, e As HistoricalDataEventArgs)
    Event HistoricalDataEnd(sender As Object, e As HistoricalDataEndEventArgs)
    Event ManagedAccounts(sender As Object, e As ManagedAccountsEventArgs)
    Event MarketDataType(sender As Object, e As MarketDataTypeEventArgs)
    Event OpenOrderEnd(sender As Object, e As EventArgs)
    Event OpenOrder(sender As Object, e As OpenOrderEventArgs)
    Event OrderStatus(sender As Object, e As OrderStatusEventArgs)
    Event Position(sender As Object, e As PositionEventArgs)
    Event PositionEnd(sender As Object, e As EventArgs)
    Event PositionMulti(sender As Object, e As PositionMultiEventArgs)
    Event PositionMultiEnd(sender As Object, e As PositionMultiEndEventArgs)
    Event RealtimeBar(sender As Object, e As RealtimeBarEventArgs)
    Event ReceiveFA(sender As Object, e As ReceiveFAEventArgs)
    Event ScannerDataEnd(sender As Object, e As ScannerDataEndEventArgs)
    Event ScannerData(sender As Object, e As ScannerDataEventArgs)
    Event ScannerParameters(sender As Object, e As ScannerParametersEventArgs)
    Event SecurityDefinitionOptionParameter(sender As Object, e As SecurityDefinitionOptionParameterEventArgs)
    Event SecurityDefinitionOptionParameterEnd(sender As Object, e As SecurityDefinitionOptionParameterEndEventArgs)
    Event TickSnapshotEnd(sender As Object, e As TickSnapshotEndEventArgs)
    Event UpdateAccountTime(sender As Object, e As UpdateAccountTimeEventArgs)
    Event UpdateAccountValue(sender As Object, e As UpdateAccountValueEventArgs)
    Event UpdateMktDepthL2(sender As Object, e As UpdateMktDepthL2EventArgs)
    Event UpdateNewsBulletin(sender As Object, e As UpdateNewsBulletinEventArgs)
    Event UpdatePortfolio(sender As Object, e As UpdatePortfolioEventArgs)
    Event VerifyCompleted(sender As Object, e As VerifyCompletedEventArgs)
    Event VerifyMessageAPI(sender As Object, e As VerifyMessageAPIEventArgs)
    Event VerifyAndAuthCompleted(sender As Object, e As VerifyAndAuthCompletedEventArgs)
    Event VerifyAndAuthMessageAPI(sender As Object, e As VerifyAndAuthMessageAPIEventArgs)
    Event FamilyCodes(sender As Object, e As FamilyCodesEventArgs)
    Event SymbolSamples(sender As Object, e As SymbolSamplesEventArgs)
    Event BondContractDetails(sender As Object, e As BondContractDetailsEventArgs)
    Event MktDepthExchanges(sender As Object, e As MktDepthExchangesEventArgs)
    Event TickNews(sender As Object, e As TickNewsEventArgs)
    Event SmartComponents(sender As ApiEventSource, e As SmartComponentsEventArgs)
    Event TickReqParams(sender As ApiEventSource, e As TickReqParamsEventArgs)
    Event NewsProviders(sender As Object, e As NewsProvidersEventArgs)
    Event NewsArticle(sender As Object, e As NewsArticleEventArgs)
    Event HistoricalNews(sender As Object, e As HistoricalNewsEventArgs)
    Event HistoricalNewsEnd(sender As Object, e As HistoricalNewsEndEventArgs)
    Event RerouteMktDataReq(sender As Object, e As RerouteMktDataReqEventArgs)
    Event RerouteMktDepthReq(sender As Object, e As RerouteMktDepthReqEventArgs)
    Event MarketRule(sender As Object, e As MarketRuleEventArgs)
    Event HistoricalTicks(sender As Object, e As HistoricalTicksEventArgs)
    Event HistoricalTicksBidAsk(sender As Object, e As HistoricalTicksBidAskEventArgs)
    Event HistoricalTicksLast(sender As Object, e As HistoricalTicksLastEventArgs)
    Event TickByTickAllLast(sender As Object, e As TickByTickAllLastEventArgs)
    Event TickByTickBidAsk(sender As Object, e As TickByTickBidAskEventArgs)
    Event TickByTickMidPoint(sender As Object, e As TickByTickMidPointEventArgs)
    Event OrderBound(sender As Object, e As OrderBoundEventArgs)
    Event CompletedOrder(sender As Object, e As OpenOrderEventArgs)
    Event CompletedOrdersEnd(sender As Object, e As EventArgs)
    Event ReplaceFAEnd(sender As Object, e As ReplaceFAEndEventArgs)
    Event WshMetaData(sender As Object, e As WshMetaDataEventArgs)
    Event WshEventData(sender As Object, e As WshEventDataEventArgs)
    Event HistoricalSchedule(sender As Object, e As HistoricalScheduleEventArgs)
    Event UserInfo(sender As Object, e As UserInfoEventArgs)
    Event CurrentTimeInMillis(sender As Object, e As CurrentTimeInMillisEventArgs)
    Event OrderStatusProtoBuf(sender As Object, e As OrderStatusProtoBufEventArgs)
    Event OpenOrderProtoBuf(sender As Object, e As OpenOrderProtoBufEventArgs)
    Event OpenOrdersEndProtoBuf(sender As Object, e As OpenOrdersEndProtoBufEventArgs)
    Event ErrorMessageProtoBuf(sender As Object, e As ErrorMessageProtoBufEventArgs)
    Event ExecutionDetailsProtoBuf(sender As Object, e As ExecutionDetailsProtoBufEventArgs)
    Event ExecutionDetailsEndProtoBuf(sender As Object, e As ExecutionDetailsEndProtoBufEventArgs)
    Event CompletedOrderProtoBuf(sender As Object, e As CompletedOrderProtoBufEventArgs)
    Event CompletedOrdersEndProtoBuf(sender As Object, e As CompletedOrdersEndProtoBufEventArgs)
    Event OrderBoundProtoBuf(sender As Object, e As OrderBoundProtoBufEventArgs)
    Event ContractDataProtoBuf(sender As Object, e As ContractDataProtoBufEventArgs)
    Event BondContractDataProtoBuf(sender As Object, e As ContractDataProtoBufEventArgs)
    Event ContractDataEndProtoBuf(sender As Object, e As ContractDataEndProtoBufEventArgs)
    Event TickPriceProtoBuf(sender As Object, e As TickPriceProtoBufEventArgs)
    Event TickSizeProtoBuf(sender As Object, e As TickSizeProtoBufEventArgs)
    Event TickOptionComputationProtoBuf(sender As Object, e As TickOptionComputationProtoBufEventArgs)
    Event TickGenericProtoBuf(sender As Object, e As TickGenericProtoBufEventArgs)
    Event TickStringProtoBuf(sender As Object, e As TickStringProtoBufEventArgs)
    Event TickSnapshotEndProtoBuf(sender As Object, e As TickSnapshotEndProtoBufEventArgs)
    Event UpdateMarketDepthProtoBuf(sender As Object, e As UpdateMarketDepthProtoBufEventArgs)
    Event UpdateMarketDepthL2ProtoBuf(sender As Object, e As UpdateMarketDepthL2ProtoBufEventArgs)
    Event MarketDataTypeProtoBuf(sender As Object, e As MarketDataTypeProtoBufEventArgs)
    Event TickReqParamsProtoBuf(sender As Object, e As TickReqParamsProtoBufEventArgs)
    Event UpdateAccountValueProtoBuf(sender As Object, e As UpdateAccountValueProtoBufEventArgs)
    Event UpdatePortfolioProtoBuf(sender As Object, e As UpdatePortfolioProtoBufEventArgs)
    Event UpdateAccountTimeProtoBuf(sender As Object, e As UpdateAccountTimeProtoBufEventArgs)
    Event AccountDataEndProtoBuf(sender As Object, e As AccountDataEndProtoBufEventArgs)
    Event ManagedAccountsProtoBuf(sender As Object, e As ManagedAccountsProtoBufEventArgs)
    Event PositionProtoBuf(sender As Object, e As PositionProtoBufEventArgs)
    Event PositionEndProtoBuf(sender As Object, e As PositionEndProtoBufEventArgs)
    Event AccountSummaryProtoBuf(sender As Object, e As AccountSummaryProtoBufEventArgs)
    Event AccountSummaryEndProtoBuf(sender As Object, e As AccountSummaryEndProtoBufEventArgs)
    Event PositionMultiProtoBuf(sender As Object, e As PositionMultiProtoBufEventArgs)
    Event PositionMultiEndProtoBuf(sender As Object, e As PositionMultiEndProtoBufEventArgs)
    Event AccountUpdateMultiProtoBuf(sender As Object, e As AccountUpdateMultiProtoBufEventArgs)
    Event AccountUpdateMultiEndProtoBuf(sender As Object, e As AccountUpdateMultiEndProtoBufEventArgs)
    Event HistoricalDataProtoBuf(sender As Object, e As HistoricalDataProtoBufEventArgs)
    Event HistoricalDataUpdateProtoBuf(sender As Object, e As HistoricalDataUpdateProtoBufEventArgs)
    Event HistoricalDataEndProtoBuf(sender As Object, e As HistoricalDataEndProtoBufEventArgs)
    Event RealTimeBarTickProtoBuf(sender As Object, e As RealTimeBarTickProtoBufEventArgs)
    Event HeadTimestampProtoBuf(sender As Object, e As HeadTimestampProtoBufEventArgs)
    Event HistogramDataProtoBuf(sender As Object, e As HistogramDataProtoBufEventArgs)
    Event HistoricalTicksProtoBuf(sender As Object, e As HistoricalTicksProtoBufEventArgs)
    Event HistoricalTicksBidAskProtoBuf(sender As Object, e As HistoricalTicksBidAskProtoBufEventArgs)
    Event HistoricalTicksLastProtoBuf(sender As Object, e As HistoricalTicksLastProtoBufEventArgs)
    Event TickByTickDataProtoBuf(sender As Object, e As TickByTickDataProtoBufEventArgs)
    Event UpdateNewsBulletinProtoBuf(sender As Object, e As UpdateNewsBulletinProtoBufEventArgs)
    Event NewsArticleProtoBuf(sender As Object, e As NewsArticleProtoBufEventArgs)
    Event NewsProvidersProtoBuf(sender As Object, e As NewsProvidersProtoBufEventArgs)
    Event HistoricalNewsProtoBuf(sender As Object, e As HistoricalNewsProtoBufEventArgs)
    Event HistoricalNewsEndProtoBuf(sender As Object, e As HistoricalNewsEndProtoBufEventArgs)
    Event WshMetaDataProtoBuf(sender As Object, e As WshMetaDataProtoBufEventArgs)
    Event WshEventDataProtoBuf(sender As Object, e As WshEventDataProtoBufEventArgs)
    Event TickNewsProtoBuf(sender As Object, e As TickNewsProtoBufEventArgs)
    Event ScannerParametersProtoBuf(sender As Object, e As ScannerParametersProtoBufEventArgs)
    Event ScannerDataProtoBuf(sender As Object, e As ScannerDataProtoBufEventArgs)
    Event FundamentalsDataProtoBuf(sender As Object, e As FundamentalsDataProtoBufEventArgs)
    Event PnLProtoBuf(sender As Object, e As PnLProtoBufEventArgs)
    Event PnLSingleProtoBuf(sender As Object, e As PnLSingleProtoBufEventArgs)
    Event ReceiveFAProtoBuf(sender As Object, e As ReceiveFAProtoBufEventArgs)
    Event ReplaceFAEndProtoBuf(sender As Object, e As ReplaceFAEndProtoBufEventArgs)
    Event CommissionAndFeesReportProtoBuf(sender As Object, e As CommissionAndFeesReportProtoBufEventArgs)
    Event HistoricalScheduleProtoBuf(sender As Object, e As HistoricalScheduleProtoBufEventArgs)
    Event RerouteMarketDataRequestProtoBuf(sender As Object, e As RerouteMarketDataRequestProtoBufEventArgs)
    Event RerouteMarketDepthRequestProtoBuf(sender As Object, e As RerouteMarketDepthRequestProtoBufEventArgs)
    Event SecDefOptParameterProtoBuf(sender As Object, e As SecDefOptParameterProtoBufEventArgs)
    Event SecDefOptParameterEndProtoBuf(sender As Object, e As SecDefOptParameterEndProtoBufEventArgs)
    Event SoftDollarTiersProtoBuf(sender As Object, e As SoftDollarTiersProtoBufEventArgs)
    Event FamilyCodesProtoBuf(sender As Object, e As FamilyCodesProtoBufEventArgs)
    Event SymbolSamplesProtoBuf(sender As Object, e As SymbolSamplesProtoBufEventArgs)
    Event SmartComponentsProtoBuf(sender As Object, e As SmartComponentsProtoBufEventArgs)
    Event MarketRuleProtoBuf(sender As Object, e As MarketRuleProtoBufEventArgs)
    Event UserInfoProtoBuf(sender As Object, e As UserInfoProtoBufEventArgs)
    Event NextValidIdProtoBuf(sender As Object, e As NextValidIdProtoBufEventArgs)
    Event CurrentTimeProtoBuf(sender As Object, e As CurrentTimeProtoBufEventArgs)
    Event CurrentTimeInMillisProtoBuf(sender As Object, e As CurrentTimeInMillisProtoBufEventArgs)
    Event VerifyMessageApiProtoBuf(sender As Object, e As VerifyMessageApiProtoBufEventArgs)
    Event VerifyCompletedProtoBuf(sender As Object, e As VerifyCompletedProtoBufEventArgs)
    Event DisplayGroupListProtoBuf(sender As Object, e As DisplayGroupListProtoBufEventArgs)
    Event DisplayGroupUpdatedProtoBuf(sender As Object, e As DisplayGroupUpdatedProtoBufEventArgs)
    Event MarketDepthExchangesProtoBuf(sender As Object, e As MarketDepthExchangesProtoBufEventArgs)
    Event ConfigResponseProtoBuf(sender As Object, e As ConfigResponseProtoBufEventArgs)
    Event UpdateConfigResponseProtoBuf(sender As Object, e As UpdateConfigResponseProtoBufEventArgs)
#End Region

End Class

