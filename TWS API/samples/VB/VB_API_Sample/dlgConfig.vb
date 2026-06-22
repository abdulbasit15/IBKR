' Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

Option Explicit On

Friend Class dlgConfig
    Inherits System.Windows.Forms.Form
#Region "Windows Form Designer generated code "
    Public Sub New()
        MyBase.New()
        If m_vb6FormDefInstance Is Nothing Then
            If m_InitializingDefInstance Then
                m_vb6FormDefInstance = Me
            Else
                Try
                    'For the start-up form, the first instance created is the default instance.
                    If System.Reflection.Assembly.GetExecutingAssembly.EntryPoint.DeclaringType Is Me.GetType Then
                        m_vb6FormDefInstance = Me
                    End If
                Catch
                End Try
            End If
        End If
        'This call is required by the Windows Form Designer.
        InitializeComponent()
    End Sub
    'Form overrides dispose to clean up the component list.
    Protected Overloads Overrides Sub Dispose(Disposing As Boolean)
        If Disposing Then
            If Not components Is Nothing Then
                components.Dispose()
            End If
        End If
        MyBase.Dispose(Disposing)
    End Sub
    'Required by the Windows Form Designer
    Private components As System.ComponentModel.IContainer
    Public ToolTip1 As System.Windows.Forms.ToolTip
    Public WithEvents configTextEditor As System.Windows.Forms.TextBox
    Public WithEvents Frame1 As System.Windows.Forms.GroupBox
    Public WithEvents cmdClose As Button
    Public WithEvents cmdUpdateConfig As System.Windows.Forms.Button
    'NOTE: The following procedure is required by the Windows Form Designer
    'It can be modified using the Windows Form Designer.
    'Do not modify it using the code editor.
    <System.Diagnostics.DebuggerStepThrough()> Private Sub InitializeComponent()
        Me.components = New System.ComponentModel.Container()
        Me.ToolTip1 = New System.Windows.Forms.ToolTip(Me.components)
        Me.Frame1 = New System.Windows.Forms.GroupBox()
        Me.configTextEditor = New System.Windows.Forms.TextBox()
        Me.cmdUpdateConfig = New System.Windows.Forms.Button()
        Me.cmdClose = New System.Windows.Forms.Button()
        Me.Frame1.SuspendLayout()
        Me.SuspendLayout()
        '
        'Frame1
        '
        Me.Frame1.BackColor = System.Drawing.Color.Gainsboro
        Me.Frame1.Controls.Add(Me.configTextEditor)
        Me.Frame1.Font = New System.Drawing.Font("Arial", 8.0!, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, CType(0, Byte))
        Me.Frame1.ForeColor = System.Drawing.SystemColors.Highlight
        Me.Frame1.Location = New System.Drawing.Point(8, 16)
        Me.Frame1.Name = "Frame1"
        Me.Frame1.RightToLeft = System.Windows.Forms.RightToLeft.No
        Me.Frame1.Size = New System.Drawing.Size(649, 538)
        Me.Frame1.TabIndex = 1
        Me.Frame1.TabStop = False
        '
        'configTextEditor
        '
        Me.configTextEditor.AcceptsReturn = True
        Me.configTextEditor.BackColor = System.Drawing.SystemColors.Window
        Me.configTextEditor.BorderStyle = System.Windows.Forms.BorderStyle.None
        Me.configTextEditor.Cursor = System.Windows.Forms.Cursors.IBeam
        Me.configTextEditor.Font = New System.Drawing.Font("Arial", 8.0!, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, CType(0, Byte))
        Me.configTextEditor.ForeColor = System.Drawing.SystemColors.WindowText
        Me.configTextEditor.Location = New System.Drawing.Point(8, 24)
        Me.configTextEditor.MaxLength = 0
        Me.configTextEditor.Multiline = True
        Me.configTextEditor.Name = "configTextEditor"
        Me.configTextEditor.RightToLeft = System.Windows.Forms.RightToLeft.No
        Me.configTextEditor.ScrollBars = System.Windows.Forms.ScrollBars.Both
        Me.configTextEditor.Size = New System.Drawing.Size(633, 514)
        Me.configTextEditor.TabIndex = 2
        Me.configTextEditor.WordWrap = False
        '
        'cmdUpdateConfig
        '
        Me.cmdUpdateConfig.BackColor = System.Drawing.SystemColors.Control
        Me.cmdUpdateConfig.Cursor = System.Windows.Forms.Cursors.Default
        Me.cmdUpdateConfig.Font = New System.Drawing.Font("Arial", 8.0!, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, CType(0, Byte))
        Me.cmdUpdateConfig.ForeColor = System.Drawing.SystemColors.ControlText
        Me.cmdUpdateConfig.Location = New System.Drawing.Point(208, 560)
        Me.cmdUpdateConfig.Name = "cmdUpdateConfig"
        Me.cmdUpdateConfig.RightToLeft = System.Windows.Forms.RightToLeft.No
        Me.cmdUpdateConfig.Size = New System.Drawing.Size(119, 25)
        Me.cmdUpdateConfig.TabIndex = 0
        Me.cmdUpdateConfig.Text = "Update Config"
        Me.cmdUpdateConfig.UseVisualStyleBackColor = True
        '
        'cmdClose
        '
        Me.cmdClose.BackColor = System.Drawing.SystemColors.Control
        Me.cmdClose.Cursor = System.Windows.Forms.Cursors.Default
        Me.cmdClose.Font = New System.Drawing.Font("Arial", 8.0!, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, CType(0, Byte))
        Me.cmdClose.ForeColor = System.Drawing.SystemColors.ControlText
        Me.cmdClose.Location = New System.Drawing.Point(333, 560)
        Me.cmdClose.Name = "cmdClose"
        Me.cmdClose.RightToLeft = System.Windows.Forms.RightToLeft.No
        Me.cmdClose.Size = New System.Drawing.Size(114, 25)
        Me.cmdClose.TabIndex = 2
        Me.cmdClose.Text = "Close"
        Me.cmdClose.UseVisualStyleBackColor = True
        '
        'dlgConfig
        '
        Me.AutoScaleBaseSize = New System.Drawing.Size(5, 13)
        Me.BackColor = System.Drawing.Color.Gainsboro
        Me.ClientSize = New System.Drawing.Size(667, 595)
        Me.Controls.Add(Me.cmdClose)
        Me.Controls.Add(Me.Frame1)
        Me.Controls.Add(Me.cmdUpdateConfig)
        Me.Cursor = System.Windows.Forms.Cursors.Default
        Me.Font = New System.Drawing.Font("Arial", 8.0!, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, CType(0, Byte))
        Me.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog
        Me.Location = New System.Drawing.Point(315, 341)
        Me.MaximizeBox = False
        Me.MinimizeBox = False
        Me.Name = "dlgConfig"
        Me.RightToLeft = System.Windows.Forms.RightToLeft.No
        Me.ShowInTaskbar = False
        Me.Text = "Config"
        Me.Frame1.ResumeLayout(False)
        Me.Frame1.PerformLayout()
        Me.ResumeLayout(False)

    End Sub
#End Region
#Region "Upgrade Support "
    Private Shared m_vb6FormDefInstance As dlgConfig
    Private Shared m_InitializingDefInstance As Boolean
    Public Shared Property DefInstance() As dlgConfig
        Get
            If m_vb6FormDefInstance Is Nothing OrElse m_vb6FormDefInstance.IsDisposed Then
                m_InitializingDefInstance = True
                m_vb6FormDefInstance = New dlgConfig
                m_InitializingDefInstance = False
            End If
            DefInstance = m_vb6FormDefInstance
        End Get
        Set(Value As dlgConfig)
            m_vb6FormDefInstance = Value
        End Set
    End Property
#End Region

    Public m_ok As Boolean
    Public updateConfigRequestProto As IBApi.protobuf.UpdateConfigRequest = New IBApi.protobuf.UpdateConfigRequest

    ' ========================================================
    ' Button Events
    ' ========================================================
    Private Sub cmdUpdateConfig_Click(sender As Object, e As EventArgs) Handles cmdUpdateConfig.Click
        Dim updateConfigText As String
        updateConfigText = configTextEditor.Text

        If Not String.IsNullOrEmpty(updateConfigText) Then
            Try
                updateConfigRequestProto = IBApi.protobuf.UpdateConfigRequest.Parser.ParseJson(updateConfigText)
            Catch ex As Exception
                MessageBox.Show("Cannot parse update config text", "Error", MessageBoxButtons.OK)
                Return
            End Try

            If Not updateConfigRequestProto.HasReqId Then updateConfigRequestProto.ReqId = 0
        End If

        m_ok = True
        Hide()
    End Sub

    Private Sub cmdClose_Click(sender As Object, e As EventArgs) Handles cmdClose.Click
        m_ok = False
        Hide()
    End Sub

    ' ========================================================
    ' Public methods
    ' ========================================================

    Public Sub init(configResponseText As String)
        configTextEditor.Text = configResponseText
        m_ok = False
    End Sub

End Class
