/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

namespace Samples
{
    public class ConfigSamples
    {
        public static IBApi.protobuf.UpdateConfigRequest UpdateConfigApiSettings(int reqId)
        {
            //! [UpdateApiSettingsConfig]
            IBApi.protobuf.UpdateConfigRequest updateConfigRequestProto = new IBApi.protobuf.UpdateConfigRequest();
            IBApi.protobuf.ApiConfig apiConfigProto = new IBApi.protobuf.ApiConfig();

            IBApi.protobuf.ApiSettingsConfig apiSettingsConfigProto = new IBApi.protobuf.ApiSettingsConfig();
            apiSettingsConfigProto.TotalQuantityForMutualFunds = true;
            apiSettingsConfigProto.DownloadOpenOrdersOnConnection = true;
            apiSettingsConfigProto.IncludeVirtualFxPositions = true;
            apiSettingsConfigProto.PrepareDailyPnL = true;
            apiSettingsConfigProto.SendStatusUpdatesForVolatilityOrders = true;
            apiSettingsConfigProto.EncodeApiMessages = "osCodePage";
            apiSettingsConfigProto.SocketPort = 7497;
            apiSettingsConfigProto.UseNegativeAutoRange = true;
            apiSettingsConfigProto.CreateApiMessageLogFile = true;
            apiSettingsConfigProto.IncludeMarketDataInLogFile = true;
            apiSettingsConfigProto.ExposeTradingScheduleToApi = true;
            apiSettingsConfigProto.SplitInsuredDepositFromCashBalance = true;
            apiSettingsConfigProto.SendZeroPositionsForTodayOnly = true;
            apiSettingsConfigProto.UseAccountGroupsWithAllocationMethods = true;
            apiSettingsConfigProto.LoggingLevel = "error";
            apiSettingsConfigProto.MasterClientId = 3;
            apiSettingsConfigProto.BulkDataTimeout = 25;
            apiSettingsConfigProto.ComponentExchSeparator = "#";
            apiSettingsConfigProto.RoundAccountValuesToNearestWholeNumber = true;
            apiSettingsConfigProto.ShowAdvancedOrderRejectInUi = true;
            apiSettingsConfigProto.RejectMessagesAboveMaxRate = true;
            apiSettingsConfigProto.MaintainConnectionOnIncorrectFields = true;
            apiSettingsConfigProto.CompatibilityModeNasdaqStocks = true;
            apiSettingsConfigProto.SendInstrumentTimezone = "utc";
            apiSettingsConfigProto.SendForexDataInCompatibilityMode = true;
            apiSettingsConfigProto.MaintainAndResubmitOrdersOnReconnect = true;
            apiSettingsConfigProto.HistoricalDataMaxSize = 4;
            apiSettingsConfigProto.AutoReportNettingEventContractTrades = true;
            apiSettingsConfigProto.OptionExerciseRequestType = "final";
            apiSettingsConfigProto.TrustedIPs.Add("127.0.0.1");

            apiConfigProto.Settings = apiSettingsConfigProto;
            updateConfigRequestProto.ReqId = reqId;
            updateConfigRequestProto.Api = apiConfigProto;

            return updateConfigRequestProto;
            //! [UpdateApiSettingsConfig]
        }

        public static IBApi.protobuf.UpdateConfigRequest UpdateOrdersConfig(int reqId)
        {
            //! [UpdateOrderConfig]
            IBApi.protobuf.UpdateConfigRequest updateConfigRequestProto = new IBApi.protobuf.UpdateConfigRequest();
            IBApi.protobuf.OrdersConfig ordersConfigProto = new IBApi.protobuf.OrdersConfig();
            IBApi.protobuf.OrdersSmartRoutingConfig ordersSmartRoutingConfigProto = new IBApi.protobuf.OrdersSmartRoutingConfig();
            ordersSmartRoutingConfigProto.SeekPriceImprovement = true;
            ordersSmartRoutingConfigProto.DoNotRouteToDarkPools = true;
            ordersConfigProto.SmartRouting = ordersSmartRoutingConfigProto;
            updateConfigRequestProto.ReqId = reqId;
            updateConfigRequestProto.Orders = ordersConfigProto;
            return updateConfigRequestProto;
            //! [UpdateOrderConfig]
        }

        public static IBApi.protobuf.UpdateConfigRequest UpdateMessageConfigConfirmMandatoryCapPriceAccepted(int reqId)
        {
            //! [UpdateMessageConfigConfirmMandatoryCapPriceAccepted]
            IBApi.protobuf.UpdateConfigRequest updateConfigRequestProto = new IBApi.protobuf.UpdateConfigRequest();
            IBApi.protobuf.MessageConfig messageConfigProto = new IBApi.protobuf.MessageConfig();
            messageConfigProto.Id = 131;
            messageConfigProto.Enabled = false;
            updateConfigRequestProto.ReqId = reqId;
            updateConfigRequestProto.Messages.Add(messageConfigProto);

            IBApi.protobuf.UpdateConfigWarning updateConfigWarningProto = new IBApi.protobuf.UpdateConfigWarning();
            updateConfigWarningProto.MessageId = 131;
            updateConfigRequestProto.AcceptedWarnings.Add(updateConfigWarningProto);

            return updateConfigRequestProto;
            //! [UpdateMessageConfigConfirmMandatoryCapPriceAccepted]
        }

        public static IBApi.protobuf.UpdateConfigRequest UpdateConfigOrderIdReset(int reqId)
        {
            //! [ UpdateConfigOrderIdReset]
            IBApi.protobuf.UpdateConfigRequest updateConfigRequestProto = new IBApi.protobuf.UpdateConfigRequest();
            updateConfigRequestProto.ReqId = reqId;
            updateConfigRequestProto.ResetAPIOrderSequence = true;
            return updateConfigRequestProto;
            //! [ UpdateConfigOrderIdReset]
        }
    }
}
