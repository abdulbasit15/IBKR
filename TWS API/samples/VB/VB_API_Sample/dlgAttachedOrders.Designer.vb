' Copyright (C) 2025 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

<Global.Microsoft.VisualBasic.CompilerServices.DesignerGenerated()> _
Partial Class dlgAttachedOrders
    Inherits System.Windows.Forms.Form

    'Form overrides dispose to clean up the component list.
    <System.Diagnostics.DebuggerNonUserCode()> _
    Protected Overrides Sub Dispose(ByVal disposing As Boolean)
        Try
            If disposing AndAlso components IsNot Nothing Then
                components.Dispose()
            End If
        Finally
            MyBase.Dispose(disposing)
        End Try
    End Sub

    'Required by the Windows Form Designer
    Private components As System.ComponentModel.IContainer

    'NOTE: The following procedure is required by the Windows Form Designer
    'It can be modified using the Windows Form Designer.  
    'Do not modify it using the code editor.
    <System.Diagnostics.DebuggerStepThrough()> _
    Private Sub InitializeComponent()
        Me.tbProfitTakerOrderType = New System.Windows.Forms.TextBox()
        Me.labelProfitTakerOrderType = New System.Windows.Forms.Label()
        Me.labelStopLossOrderType = New System.Windows.Forms.Label()
        Me.tbStopLossOrderId = New System.Windows.Forms.TextBox()
        Me.labelStopLossOrderId = New System.Windows.Forms.Label()
        Me.btnOK = New System.Windows.Forms.Button()
        Me.btnCancel = New System.Windows.Forms.Button()
        Me.tbStopLossOrderType = New System.Windows.Forms.TextBox()
        Me.tbProfitTakerOrderId = New System.Windows.Forms.TextBox()
        Me.labelProfitTakerOrderId = New System.Windows.Forms.Label()
        Me.SuspendLayout()
        '
        'tbProfitTakerOrderType
        '
        Me.tbProfitTakerOrderType.Anchor = CType((System.Windows.Forms.AnchorStyles.Bottom Or System.Windows.Forms.AnchorStyles.Right), System.Windows.Forms.AnchorStyles)
        Me.tbProfitTakerOrderType.BorderStyle = System.Windows.Forms.BorderStyle.None
        Me.tbProfitTakerOrderType.Location = New System.Drawing.Point(167, 84)
        Me.tbProfitTakerOrderType.Name = "tbProfitTakerOrderType"
        Me.tbProfitTakerOrderType.Size = New System.Drawing.Size(195, 13)
        Me.tbProfitTakerOrderType.TabIndex = 7
        '
        'labelProfitTakerOrderType
        '
        Me.labelProfitTakerOrderType.AccessibleRole = System.Windows.Forms.AccessibleRole.Grip
        Me.labelProfitTakerOrderType.Anchor = CType((System.Windows.Forms.AnchorStyles.Bottom Or System.Windows.Forms.AnchorStyles.Right), System.Windows.Forms.AnchorStyles)
        Me.labelProfitTakerOrderType.AutoSize = True
        Me.labelProfitTakerOrderType.Location = New System.Drawing.Point(12, 84)
        Me.labelProfitTakerOrderType.Name = "labelProfitTakerOrderType"
        Me.labelProfitTakerOrderType.Size = New System.Drawing.Size(118, 13)
        Me.labelProfitTakerOrderType.TabIndex = 6
        Me.labelProfitTakerOrderType.Text = "Profit-Taker Order Type"
        '
        'labelStopLossOrderType
        '
        Me.labelStopLossOrderType.AccessibleRole = System.Windows.Forms.AccessibleRole.Grip
        Me.labelStopLossOrderType.AutoSize = True
        Me.labelStopLossOrderType.Location = New System.Drawing.Point(12, 35)
        Me.labelStopLossOrderType.Name = "labelStopLossOrderType"
        Me.labelStopLossOrderType.Size = New System.Drawing.Size(110, 13)
        Me.labelStopLossOrderType.TabIndex = 2
        Me.labelStopLossOrderType.Text = "Stop-Loss Order Type"
        '
        'tbStopLossOrderId
        '
        Me.tbStopLossOrderId.BorderStyle = System.Windows.Forms.BorderStyle.None
        Me.tbStopLossOrderId.Location = New System.Drawing.Point(167, 6)
        Me.tbStopLossOrderId.Name = "tbStopLossOrderId"
        Me.tbStopLossOrderId.Size = New System.Drawing.Size(195, 13)
        Me.tbStopLossOrderId.TabIndex = 1
        '
        'labelStopLossOrderId
        '
        Me.labelStopLossOrderId.AccessibleRole = System.Windows.Forms.AccessibleRole.Grip
        Me.labelStopLossOrderId.AutoSize = True
        Me.labelStopLossOrderId.Location = New System.Drawing.Point(12, 9)
        Me.labelStopLossOrderId.Name = "labelStopLossOrderId"
        Me.labelStopLossOrderId.Size = New System.Drawing.Size(95, 13)
        Me.labelStopLossOrderId.TabIndex = 0
        Me.labelStopLossOrderId.Text = "Stop-Loss Order Id"
        '
        'btnOK
        '
        Me.btnOK.Anchor = CType((System.Windows.Forms.AnchorStyles.Bottom Or System.Windows.Forms.AnchorStyles.Right), System.Windows.Forms.AnchorStyles)
        Me.btnOK.Location = New System.Drawing.Point(209, 103)
        Me.btnOK.Name = "btnOK"
        Me.btnOK.Size = New System.Drawing.Size(75, 23)
        Me.btnOK.TabIndex = 8
        Me.btnOK.Text = "OK"
        Me.btnOK.UseVisualStyleBackColor = True
        '
        'btnCancel
        '
        Me.btnCancel.Anchor = CType((System.Windows.Forms.AnchorStyles.Bottom Or System.Windows.Forms.AnchorStyles.Right), System.Windows.Forms.AnchorStyles)
        Me.btnCancel.Location = New System.Drawing.Point(290, 103)
        Me.btnCancel.Name = "btnCancel"
        Me.btnCancel.Size = New System.Drawing.Size(75, 23)
        Me.btnCancel.TabIndex = 9
        Me.btnCancel.Text = "Cancel"
        Me.btnCancel.UseVisualStyleBackColor = True
        '
        'tbStopLossOrderType
        '
        Me.tbStopLossOrderType.BorderStyle = System.Windows.Forms.BorderStyle.None
        Me.tbStopLossOrderType.Location = New System.Drawing.Point(167, 32)
        Me.tbStopLossOrderType.Name = "tbStopLossOrderType"
        Me.tbStopLossOrderType.Size = New System.Drawing.Size(195, 13)
        Me.tbStopLossOrderType.TabIndex = 3
        '
        'tbProfitTakerOrderId
        '
        Me.tbProfitTakerOrderId.BorderStyle = System.Windows.Forms.BorderStyle.None
        Me.tbProfitTakerOrderId.Location = New System.Drawing.Point(167, 58)
        Me.tbProfitTakerOrderId.Name = "tbProfitTakerOrderId"
        Me.tbProfitTakerOrderId.Size = New System.Drawing.Size(195, 13)
        Me.tbProfitTakerOrderId.TabIndex = 5
        '
        'labelProfitTakerOrderId
        '
        Me.labelProfitTakerOrderId.AccessibleRole = System.Windows.Forms.AccessibleRole.Grip
        Me.labelProfitTakerOrderId.AutoSize = True
        Me.labelProfitTakerOrderId.Location = New System.Drawing.Point(12, 61)
        Me.labelProfitTakerOrderId.Name = "labelProfitTakerOrderId"
        Me.labelProfitTakerOrderId.Size = New System.Drawing.Size(103, 13)
        Me.labelProfitTakerOrderId.TabIndex = 4
        Me.labelProfitTakerOrderId.Text = "Profit-Taker Order Id"
        '
        'dlgAttachedOrders
        '
        Me.AutoScaleDimensions = New System.Drawing.SizeF(6.0!, 13.0!)
        Me.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font
        Me.BackColor = System.Drawing.Color.Gainsboro
        Me.ClientSize = New System.Drawing.Size(377, 138)
        Me.Controls.Add(Me.labelProfitTakerOrderId)
        Me.Controls.Add(Me.tbProfitTakerOrderId)
        Me.Controls.Add(Me.tbStopLossOrderType)
        Me.Controls.Add(Me.btnCancel)
        Me.Controls.Add(Me.btnOK)
        Me.Controls.Add(Me.tbProfitTakerOrderType)
        Me.Controls.Add(Me.labelProfitTakerOrderType)
        Me.Controls.Add(Me.labelStopLossOrderType)
        Me.Controls.Add(Me.tbStopLossOrderId)
        Me.Controls.Add(Me.labelStopLossOrderId)
        Me.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog
        Me.Name = "dlgAttachedOrders"
        Me.Text = "dlgAttachedOrders"
        Me.ResumeLayout(False)
        Me.PerformLayout()

    End Sub
    Private WithEvents tbProfitTakerOrderType As System.Windows.Forms.TextBox
    Private WithEvents labelProfitTakerOrderType As System.Windows.Forms.Label
    Private WithEvents labelStopLossOrderType As System.Windows.Forms.Label
    Private WithEvents tbStopLossOrderId As System.Windows.Forms.TextBox
    Private WithEvents labelStopLossOrderId As System.Windows.Forms.Label
    Friend WithEvents btnOK As System.Windows.Forms.Button
    Friend WithEvents btnCancel As System.Windows.Forms.Button
    Friend WithEvents tbStopLossOrderType As System.Windows.Forms.TextBox
    Friend WithEvents tbProfitTakerOrderId As System.Windows.Forms.TextBox
    Private WithEvents labelProfitTakerOrderId As System.Windows.Forms.Label
End Class
