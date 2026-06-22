VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "CommissionAndFeesReports"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Option Explicit

'=================
' local constants
'=================

Private Enum CommissionAndFeesReportColumns
    Col_EXECID = 1
    Col_COMMISSIONANDFEES
    Col_CURRENCY
    Col_REALIZEDPNL
    Col_YIELD
    Col_YIELDREDEMPTIONDATE
End Enum

' local variables
Private rowId As Long

Private commissionAndFeesReportsTable As Range

'=================
' private methods
'=================
' clear executions table
Private Sub clearCommissionAndFeesReports_Click()
Clear
End Sub

Private Sub Clear()
    commissionAndFeesReportsTable.ClearContents
    rowId = 1
End Sub


'=================
' public methods
'=================
' update commission and fees reports table
Public Sub UpdateCommissionAndFeesReports(ByVal commissionAndFeesReport As TWSLib.ICommissionAndFeesReport)
    If rowId <= commissionAndFeesReportsTable.Rows.Count Then
        ' commission and fees report
        With commissionAndFeesReport
            commissionAndFeesReportsTable(rowId, Col_EXECID).value = .execId
            commissionAndFeesReportsTable(rowId, Col_COMMISSIONANDFEES).value = Util.DblMaxStr(.commissionAndFees)
            commissionAndFeesReportsTable(rowId, Col_CURRENCY).value = .currency
            commissionAndFeesReportsTable(rowId, Col_REALIZEDPNL).value = Util.DblMaxStr(.realizedPNL)
            commissionAndFeesReportsTable(rowId, Col_YIELD).value = Util.DblMaxStr(.yield)
            commissionAndFeesReportsTable(rowId, Col_YIELDREDEMPTIONDATE).value = Util.IntMaxStr(.yieldRedemptionDate)
        End With
    
        rowId = rowId + 1
    End If

End Sub

Public Sub Initialise()
    Set commissionAndFeesReportsTable = Me.Range("$A$7:$F$103")
    Clear
End Sub

Private Sub Worksheet_Activate()
    Main.Initialise
    If commissionAndFeesReportsTable Is Nothing Then
        Set commissionAndFeesReportsTable = Me.Range("$A$7:$F$103")
        Clear
    End If
End Sub


