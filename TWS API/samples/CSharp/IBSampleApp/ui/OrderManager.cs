/* Copyright (C) 2025 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System.Collections.Generic;

using IBSampleApp.messages;
using IBApi;
using System.Windows.Forms;
using System;

namespace IBSampleApp.ui
{
    class OrderManager
    {        
        private OrderDialog orderDialog;
        private List<string> managedAccounts;

        private List<OpenOrderMessage> openOrders = new List<OpenOrderMessage>();
        private List<CompletedOrderMessage> completedOrders = new List<CompletedOrderMessage>();

        private DataGridView liveOrdersGrid;
        private DataGridView completedOrdersGrid;
        private DataGridView tradeLogGrid;

        public IBClient IBClient { get; }

        public OrderManager(IBClient ibClient, DataGridView liveOrdersGrid, DataGridView completedOrdersGrid, DataGridView tradeLogGrid)
        {
            IBClient = ibClient;
            orderDialog = new OrderDialog(this);
            this.liveOrdersGrid = liveOrdersGrid;
            this.completedOrdersGrid = completedOrdersGrid;
            this.tradeLogGrid = tradeLogGrid;
        }

        public List<string> ManagedAccounts
        {
            get { return managedAccounts; }
            set 
            {
                orderDialog.SetManagedAccounts(value);
                managedAccounts = value;
            }
        }

        public void PlaceOrder(Contract contract, Order order)
        {
            if (order.OrderId != 0)
            {
                IBClient.ClientSocket.placeOrder(order.OrderId, contract, order);
            }
            else
            {
                int orderId = IBClient.NextOrderId++;
                if (!string.IsNullOrWhiteSpace(order.SlOrderType))
                {
                    order.SlOrderId = IBClient.NextOrderId++;
                }
                if (!string.IsNullOrWhiteSpace(order.PtOrderType))
                {
                    order.PtOrderId = IBClient.NextOrderId++;
                }
                IBClient.ClientSocket.placeOrder(orderId, contract, order);
            }
        }

        public void CancelOrder(Order order, OrderCancel orderCancel)
        {
            if (order.OrderId != 0)
            {
                IBClient.ClientSocket.cancelOrder(order.OrderId, orderCancel);
            }
        }

        public void GlobalCancel(OrderCancel orderCancel)
        {
            IBClient.ClientSocket.reqGlobalCancel(orderCancel);
        }

        public void OpenOrderDialog()
        {
            orderDialog.ShowDialog();
        }

        public void OpenNewOrderDialog()
        {
            orderDialog = new OrderDialog(this);

            orderDialog.ShowDialog();
        }

        public void EditOrder()
        {
            if (liveOrdersGrid.SelectedRows.Count > 0)
            {
                DataGridViewRow selectedRow = liveOrdersGrid.SelectedRows[0];
                int orderId;
                int clientId;
                if (int.TryParse(selectedRow.Cells[2].Value.ToString(), out orderId) &&
                    int.TryParse(selectedRow.Cells[1].Value.ToString(), out clientId) &&
                    int.Equals(clientId, IBClient.ClientId))
                {
                    for (int i = 0; i < openOrders.Count; i++)
                    {
                        if (openOrders[i].OrderId == orderId)
                        {
                            orderDialog.SetOrderContract(openOrders[i].Contract);
                            orderDialog.SetOrder(openOrders[i].Order);
                        }
                    }
                }
                orderDialog.ShowDialog();
            }
        }


        public void AttachOrder()
        {
            if (liveOrdersGrid.SelectedRows.Count > 0)
            {
                DataGridViewRow selectedRow = liveOrdersGrid.SelectedRows[0];

                int orderId;
                int clientId;
                if (int.TryParse(selectedRow.Cells[2].Value.ToString(), out orderId) &&
                    int.TryParse(selectedRow.Cells[1].Value.ToString(), out clientId) &&
                    int.Equals(clientId, IBClient.ClientId))
                {
                    for (int i = 0; i < openOrders.Count; i++)
                    {
                        if (openOrders[i].OrderId == orderId)
                        {
                            orderDialog.SetOrderContract(openOrders[i].Contract);
                            orderDialog.SetOrder(openOrders[i].Order);

                            orderDialog.SetOrderId(IBClient.NextOrderId);
                            IBClient.NextOrderId++;
                            orderDialog.SetParentOrderId(orderId);
                        }
                    }
                }
                orderDialog.ShowDialog();
            }
        }

        public void CancelSelection()
        {
            if (liveOrdersGrid.SelectedRows.Count > 0)
            {
                for (int i = 0; i < liveOrdersGrid.SelectedRows.Count; i++)
                {
                    int orderId;
                    int clientId;

                    if (int.TryParse(liveOrdersGrid.SelectedRows[i].Cells[2].Value.ToString(), out orderId) &&
                        int.TryParse(liveOrdersGrid.SelectedRows[i].Cells[1].Value.ToString(), out clientId))
                    {
                        OpenOrderMessage openOrder = GetOpenOrderMessage(orderId, clientId);
                        if (openOrder != null)
                        {
                            orderDialog.SetOrderContract(openOrder.Contract);
                            orderDialog.SetOrder(openOrder.Order);
                            orderDialog.ShowDialog();
                        }
                    }
                }
            }
        }

        private OpenOrderMessage GetOpenOrderMessage(int orderId, int clientId)
        {
            for (int i = 0; i < openOrders.Count; i++)
            {
                if (openOrders[i].Order.OrderId == orderId && openOrders[i].Order.ClientId == clientId)
                    return openOrders[i];
            }
            return null;
        }

        public void HandleCommissionAndFeesMessage(CommissionAndFeesMessage message)
        {
            for (int i = 0; i < tradeLogGrid.Rows.Count; i++)
            {
                if (tradeLogGrid["executionIdExecColumn", i].Value != null && ((string)tradeLogGrid["executionIdExecColumn", i].Value).Equals(message.CommissionAndFeesReport.ExecId))
                {
                    tradeLogGrid["commissionAndFeesExecColumn", i].Value = Util.DoubleMaxString(message.CommissionAndFeesReport.CommissionAndFees);
                    tradeLogGrid["realizedPnLExecColumn", i].Value = Util.DoubleMaxString(message.CommissionAndFeesReport.RealizedPNL);
                }
            }
        }

        public void handleOpenOrder(OpenOrderMessage openOrder)
        {
            if (openOrder.Order.WhatIf)
                orderDialog.HandleOpenOrder(openOrder);
            else
            {
                UpdateLiveOrders(openOrder);
                UpdateLiveOrdersGrid(openOrder);
            }
        }

        public void handleCompletedOrder(CompletedOrderMessage completedOrder)
        {
            UpdateCompletedOrdersGrid(completedOrder);
        }

        public void HandleExecutionMessage(ExecutionMessage message)
        {
            for (int i = 0; i < tradeLogGrid.Rows.Count; i++)
            {
                if (message.Execution.ExecId != null && ((string)tradeLogGrid["executionIdExecColumn", i].Value).Equals(message.Execution.ExecId))
                {
                    PopulateTradeLog(i, message);
                }
            }
            tradeLogGrid.Rows.Add(1);
            PopulateTradeLog(tradeLogGrid.Rows.Count-1, message);
        }

        private void PopulateTradeLog(int index, ExecutionMessage message)
        {
            tradeLogGrid["executionIdExecColumn", index].Value = message.Execution.ExecId;
            tradeLogGrid["dateTimeExecColumn", index].Value = message.Execution.Time;
            tradeLogGrid["accountExecColumn", index].Value = message.Execution.AcctNumber;
            tradeLogGrid["modelCodeExecColumn", index].Value = message.Execution.ModelCode;
            tradeLogGrid["actionExecColumn", index].Value = message.Execution.Side;
            tradeLogGrid["quantityExecColumn", index].Value = Util.DecimalMaxString(message.Execution.Shares);
            tradeLogGrid["descriptionExecColumn", index].Value = message.Contract.Symbol + " " + message.Contract.SecType + " " + message.Contract.Exchange;
            tradeLogGrid["priceExecColumn", index].Value = Util.DoubleMaxString(message.Execution.Price);
            tradeLogGrid["lastLiquidityExecColumn", index].Value = message.Execution.LastLiquidity;
            tradeLogGrid["pendingPriceRevisionExecColumn", index].Value = message.Execution.PendingPriceRevision;
            tradeLogGrid["permIdExecColumn", index].Value = message.Execution.PermId;
            tradeLogGrid["submitterExecColumn", index].Value = message.Execution.Submitter;
            tradeLogGrid["optExerciseOrLapseTypeExecColumn", index].Value = message.Execution.OptExerciseOrLapseType;
        }

        public void HandleOrderStatus(OrderStatusMessage statusMessage)
        {
            for (int i = 0; i < liveOrdersGrid.Rows.Count; i++)
            {
                if (liveOrdersGrid["permIdColumn", i].Value.Equals(statusMessage.PermId))
                {
                    liveOrdersGrid["statusColumn", i].Value = statusMessage.Status;
                    return;
                }
            }
        }

        public void HandleSoftDollarTiers(SoftDollarTiersMessage msg)
        {
            orderDialog.HandleSoftDollarTiers(msg);
        }

        private void UpdateCompletedOrdersGrid(CompletedOrderMessage completedOrderMessage)
        {
            completedOrdersGrid.Rows.Add(1);
            PopulateCompletedOrderRow(completedOrdersGrid.Rows.Count - 1, completedOrderMessage);
        }

        private void UpdateLiveOrders(OpenOrderMessage orderMesage)
        {
            for (int i = 0; i < openOrders.Count; i++ )
            {
                if (openOrders[i].Order.OrderId == orderMesage.OrderId)
                {
                    openOrders[i] = orderMesage;
                    return;
                }
            }
            openOrders.Add(orderMesage);
        }

        private void UpdateLiveOrdersGrid(OpenOrderMessage orderMessage)
        {
            for (int i = 0; i<liveOrdersGrid.Rows.Count; i++)
            {
                if (Convert.ToInt32(liveOrdersGrid["orderIdColumn", i].Value) == orderMessage.Order.OrderId)
                {
                    PopulateOrderRow(i, orderMessage);
                    return;
                }
            }
            liveOrdersGrid.Rows.Add(1);
            PopulateOrderRow(liveOrdersGrid.Rows.Count - 1, orderMessage);
        }

        private void PopulateOrderRow(int rowIndex, OpenOrderMessage orderMessage)
        {
            liveOrdersGrid["permIdColumn", rowIndex].Value = Util.LongMaxString(orderMessage.Order.PermId);
            liveOrdersGrid["clientIdColumn", rowIndex].Value = Util.IntMaxString(orderMessage.Order.ClientId);
            liveOrdersGrid["orderIdColumn", rowIndex].Value = Util.IntMaxString(orderMessage.Order.OrderId);
            liveOrdersGrid["accountColumn", rowIndex].Value = orderMessage.Order.Account;
            liveOrdersGrid["modelCodeColumn", rowIndex].Value = orderMessage.Order.ModelCode;
            liveOrdersGrid["actionColumn", rowIndex].Value = orderMessage.Order.Action;
            liveOrdersGrid["quantityColumn", rowIndex].Value = Util.DecimalMaxString(orderMessage.Order.TotalQuantity);
            liveOrdersGrid["contractColumn", rowIndex].Value = orderMessage.Contract.Symbol+" "+orderMessage.Contract.SecType+" "+orderMessage.Contract.Exchange;
            liveOrdersGrid["customerAccountColumn", rowIndex].Value = orderMessage.Order.CustomerAccount;
            liveOrdersGrid["professionalCustomerColumn", rowIndex].Value = orderMessage.Order.ProfessionalCustomer;
            liveOrdersGrid["includeOvernightColumn", rowIndex].Value = orderMessage.Order.IncludeOvernight;
            liveOrdersGrid["statusColumn", rowIndex].Value = orderMessage.OrderState.Status;
            liveOrdersGrid["cashQtyColumn", rowIndex].Value = Util.DoubleMaxString(orderMessage.Order.CashQty);
            liveOrdersGrid["extOperatorColumn", rowIndex].Value = orderMessage.Order.ExtOperator;
            liveOrdersGrid["manualOrderIndicatorColumn", rowIndex].Value = Util.IntMaxString(orderMessage.Order.ManualOrderIndicator);
            liveOrdersGrid["submitterColumn", rowIndex].Value = orderMessage.Order.Submitter;
            liveOrdersGrid["imbalanceOnlyColumn", rowIndex].Value = orderMessage.Order.ImbalanceOnly;
            liveOrdersGrid["postOnlyColumn", rowIndex].Value = orderMessage.Order.PostOnly;
            liveOrdersGrid["allowPreOpenColumn", rowIndex].Value = orderMessage.Order.AllowPreOpen;
            liveOrdersGrid["ignoreOpenAuctionColumn", rowIndex].Value = orderMessage.Order.IgnoreOpenAuction;
            liveOrdersGrid["deactivateColumn", rowIndex].Value = orderMessage.Order.Deactivate;
            liveOrdersGrid["seekPriceImprovementColumn", rowIndex].Value = orderMessage.Order.SeekPriceImprovement;
            liveOrdersGrid["routeMarketableToBboColumn", rowIndex].Value = orderMessage.Order.RouteMarketableToBbo;
        }

        private void PopulateCompletedOrderRow(int rowIndex, CompletedOrderMessage completedOrderMessage)
        {
            completedOrdersGrid["completedOrdersPermId", rowIndex].Value = Util.LongMaxString(completedOrderMessage.Order.PermId);
            completedOrdersGrid["completedOrdersParentPermId", rowIndex].Value = Util.LongMaxString(completedOrderMessage.Order.ParentPermId);
            completedOrdersGrid["completedOrdersAccount", rowIndex].Value = completedOrderMessage.Order.Account;
            completedOrdersGrid["completedOrdersAction", rowIndex].Value = completedOrderMessage.Order.Action;
            completedOrdersGrid["completedOrdersQuantity", rowIndex].Value = Util.DecimalMaxString(completedOrderMessage.Order.TotalQuantity);
            completedOrdersGrid["completedOrdersCashQuantity", rowIndex].Value = Util.DoubleMaxString(completedOrderMessage.Order.CashQty);
            completedOrdersGrid["completedOrdersFilledQuantity", rowIndex].Value = Util.DecimalMaxString(completedOrderMessage.Order.FilledQuantity);
            completedOrdersGrid["completedOrdersLmtPrice", rowIndex].Value = Util.DoubleMaxString(completedOrderMessage.Order.LmtPrice);
            completedOrdersGrid["completedOrdersAuxPrice", rowIndex].Value = Util.DoubleMaxString(completedOrderMessage.Order.AuxPrice);
            completedOrdersGrid["completedOrdersContract", rowIndex].Value = completedOrderMessage.Contract.Symbol + " " + completedOrderMessage.Contract.SecType + " " + completedOrderMessage.Contract.Exchange;
            completedOrdersGrid["completedOrdersCustomerAccount", rowIndex].Value = completedOrderMessage.Order.CustomerAccount;
            completedOrdersGrid["completedOrdersProfessionalCustomer", rowIndex].Value = completedOrderMessage.Order.ProfessionalCustomer;
            completedOrdersGrid["completedOrdersSubmitter", rowIndex].Value = completedOrderMessage.Order.Submitter;
            completedOrdersGrid["completedOrdersImbalanceOnly", rowIndex].Value = completedOrderMessage.Order.ImbalanceOnly;
            completedOrdersGrid["completedOrdersStatus", rowIndex].Value = completedOrderMessage.OrderState.Status;
            completedOrdersGrid["completedOrdersCompTime", rowIndex].Value = completedOrderMessage.OrderState.CompletedTime;
            completedOrdersGrid["completedOrdersCompStatus", rowIndex].Value = completedOrderMessage.OrderState.CompletedStatus;
        }

    }
}
