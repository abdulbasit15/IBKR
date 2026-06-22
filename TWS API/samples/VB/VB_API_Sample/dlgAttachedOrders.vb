' Copyright (C) 2025 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

Imports IBApi

Public Class dlgAttachedOrders

    Dim order As IBApi.Order

    Sub New(order As Order)
        ' This is required by the designer.
        InitializeComponent()

        Me.order = order
    End Sub

    Private Sub btnOK_Click(sender As Object, e As EventArgs) Handles btnOK.Click
        order.SlOrderId = If(String.IsNullOrEmpty(tbStopLossOrderId.Text), Integer.MaxValue, CInt(tbStopLossOrderId.Text))
        order.SlOrderType = tbStopLossOrderType.Text
        order.PtOrderId = If(String.IsNullOrEmpty(tbProfitTakerOrderId.Text), Integer.MaxValue, CInt(tbProfitTakerOrderId.Text))
        order.PtOrderType = tbProfitTakerOrderType.Text

        Close()
    End Sub

    Private Sub btnCancel_Click(sender As Object, e As EventArgs) Handles btnCancel.Click
        Close()
    End Sub
End Class