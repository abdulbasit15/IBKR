' Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

Namespace Samples

    Public Class ConfigSamples

        Public Shared Function UpdateConfigApiSettings(reqId As Integer) As IBApi.protobuf.UpdateConfigRequest
            '! [UpdateApiSettingsConfig]
            Dim updateConfigRequestProto As IBApi.protobuf.UpdateConfigRequest = New IBApi.protobuf.UpdateConfigRequest
            Dim apiConfigProto As IBApi.protobuf.ApiConfig = New IBApi.protobuf.ApiConfig
            Dim apiSettingsConfigProto As IBApi.protobuf.ApiSettingsConfig = New IBApi.protobuf.ApiSettingsConfig

            apiSettingsConfigProto.TotalQuantityForMutualFunds = True
            apiSettingsConfigProto.DownloadOpenOrdersOnConnection = True
            apiSettingsConfigProto.IncludeVirtualFxPositions = True
            apiSettingsConfigProto.PrepareDailyPnL = True
            apiSettingsConfigProto.SendStatusUpdatesForVolatilityOrders = True
            apiSettingsConfigProto.EncodeApiMessages = "osCodePage"
            apiSettingsConfigProto.SocketPort = 7497
            apiSettingsConfigProto.UseNegativeAutoRange = True
            apiSettingsConfigProto.CreateApiMessageLogFile = True
            apiSettingsConfigProto.IncludeMarketDataInLogFile = True
            apiSettingsConfigProto.ExposeTradingScheduleToApi = True
            apiSettingsConfigProto.SplitInsuredDepositFromCashBalance = True
            apiSettingsConfigProto.SendZeroPositionsForTodayOnly = True
            apiSettingsConfigProto.UseAccountGroupsWithAllocationMethods = True
            apiSettingsConfigProto.LoggingLevel = "error"
            apiSettingsConfigProto.MasterClientId = 3
            apiSettingsConfigProto.BulkDataTimeout = 25
            apiSettingsConfigProto.ComponentExchSeparator = "#"
            apiSettingsConfigProto.RoundAccountValuesToNearestWholeNumber = True
            apiSettingsConfigProto.ShowAdvancedOrderRejectInUi = True
            apiSettingsConfigProto.RejectMessagesAboveMaxRate = True
            apiSettingsConfigProto.MaintainConnectionOnIncorrectFields = True
            apiSettingsConfigProto.CompatibilityModeNasdaqStocks = True
            apiSettingsConfigProto.SendInstrumentTimezone = "utc"
            apiSettingsConfigProto.SendForexDataInCompatibilityMode = True
            apiSettingsConfigProto.MaintainAndResubmitOrdersOnReconnect = True
            apiSettingsConfigProto.HistoricalDataMaxSize = 4
            apiSettingsConfigProto.AutoReportNettingEventContractTrades = True
            apiSettingsConfigProto.OptionExerciseRequestType = "final"
            apiSettingsConfigProto.TrustedIPs.Add("127.0.0.1")

            apiConfigProto.Settings = apiSettingsConfigProto
            updateConfigRequestProto.ReqId = reqId
            updateConfigRequestProto.Api = apiConfigProto

            Return updateConfigRequestProto
            ' ![UpdateApiSettingsConfig]
        End Function


        Public Shared Function UpdateOrdersConfig(reqId As Integer) As IBApi.protobuf.UpdateConfigRequest
            '! [UpdateOrderConfig]
            Dim updateConfigRequestProto As IBApi.protobuf.UpdateConfigRequest = New IBApi.protobuf.UpdateConfigRequest
            Dim ordersConfigProto As IBApi.protobuf.OrdersConfig = New IBApi.protobuf.OrdersConfig
            Dim ordersSmartRoutingConfigProto As IBApi.protobuf.OrdersSmartRoutingConfig = New IBApi.protobuf.OrdersSmartRoutingConfig
            ordersSmartRoutingConfigProto.SeekPriceImprovement = True
            ordersSmartRoutingConfigProto.DoNotRouteToDarkPools = True
            ordersConfigProto.SmartRouting = ordersSmartRoutingConfigProto
            updateConfigRequestProto.ReqId = reqId
            updateConfigRequestProto.Orders = ordersConfigProto
            Return updateConfigRequestProto
            '! [UpdateOrderConfig]
        End Function

        Public Shared Function UpdateMessageConfigConfirmMandatoryCapPriceAccepted(reqId As Integer) As IBApi.protobuf.UpdateConfigRequest
            '! [UpdateMessageConfigConfirmMandatoryCapPriceAccepted]
            Dim updateConfigRequestProto As IBApi.protobuf.UpdateConfigRequest = New IBApi.protobuf.UpdateConfigRequest
            Dim messageConfigProto As IBApi.protobuf.MessageConfig = New IBApi.protobuf.MessageConfig
            messageConfigProto.Id = 131
            messageConfigProto.Enabled = False
            updateConfigRequestProto.ReqId = reqId
            updateConfigRequestProto.Messages.Add(messageConfigProto)
            Dim updateConfigWarningProto As IBApi.protobuf.UpdateConfigWarning = New IBApi.protobuf.UpdateConfigWarning
            updateConfigWarningProto.MessageId = 131
            updateConfigRequestProto.AcceptedWarnings.Add(updateConfigWarningProto)
            Return updateConfigRequestProto
            '! [UpdateMessageConfigConfirmMandatoryCapPriceAccepted]
        End Function

        Public Shared Function UpdateConfigOrderIdReset(reqId As Integer) As IBApi.protobuf.UpdateConfigRequest
            '! [ UpdateConfigOrderIdReset]
            Dim updateConfigRequestProto As IBApi.protobuf.UpdateConfigRequest = New IBApi.protobuf.UpdateConfigRequest
            updateConfigRequestProto.ReqId = reqId
            updateConfigRequestProto.ResetAPIOrderSequence = True
            Return updateConfigRequestProto
            '! [ UpdateConfigOrderIdReset]
        End Function

    End Class

End Namespace
