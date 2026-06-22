VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Executions"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Option Explicit

'=================
' local constants
'=================
' table constants
Const CELL_EXECFILTER_CLIENTID = "A6"
Const CELL_EXECFILTER_ACCTCODE = "B6"
Const CELL_EXECFILTER_TIME = "C6"
Const CELL_EXECFILTER_SYMBOL = "D6"
Const CELL_EXECFILTER_SECTYPE = "E6"
Const CELL_EXECFILTER_EXCH = "F6"
Const CELL_EXECFILTER_SIDE = "G6"
Const CELL_EXECFILTER_LASTNDAYS = "H6"
Const CELL_EXECFILTER_SPECIFICDATES = "I6"

' contract id not in standard column
Const Col_CONID = 11

Private Enum ExecutionDetailsColumns
    Col_ORDERID = 1
    Col_EXECID
    Col_TIME
    Col_ACCOUNT
    Col_EXCHANGE
    Col_SIDE
    Col_QUANTITY
    Col_CUMQTY
    Col_PRICE
    Col_AVGPRICE
    Col_PERMID
    Col_LIQUIDATION
    Col_CLIENTID
    Col_ORDERREF
    Col_EVRULE
    Col_EVMULTIPLIER
    Col_MODELCODE
    Col_LASTLIQUIDITY
    Col_PENDINGPRICEREVISION
    Col_SUBMITTER
    Col_OPTEXERCISEORLAPSETYPE
End Enum

' local variables

Private contractTable As Range
Private executionsTable As Range

Private rowId As Long

'=================
' private methods
'=================
' request executions
Private Sub RequestExecutions_Click()
    If Not CheckConnected Then Exit Sub
    
    Clear
    
    ' apply execution filter
    Dim lExecFilter As TWSLib.IExecutionFilter
    Set lExecFilter = Api.Tws.createExecutionFilter()
    
    Dim arrSpecificDatesStr() As String
    arrSpecificDatesStr = Split(Range(CELL_EXECFILTER_SPECIFICDATES).value, ",")
    
    Dim arrSpecificDatesLong As TWSLib.IIntegerList
    Set arrSpecificDatesLong = Api.Tws.createIntegerList()
    Dim i As Integer
    For i = LBound(arrSpecificDatesStr) To UBound(arrSpecificDatesStr)
        arrSpecificDatesLong.Add (CLng(arrSpecificDatesStr(i)))
    Next i
    
    With lExecFilter
        .clientId = Range(CELL_EXECFILTER_CLIENTID).value
        .acctCode = Range(CELL_EXECFILTER_ACCTCODE).value
        .time = Range(CELL_EXECFILTER_TIME).value
        .Symbol = Range(CELL_EXECFILTER_SYMBOL).value
        .SecType = Range(CELL_EXECFILTER_SECTYPE).value
        .Exchange = Range(CELL_EXECFILTER_EXCH).value
        .side = Range(CELL_EXECFILTER_SIDE).value
        If Range(CELL_EXECFILTER_LASTNDAYS).value > 0 Then
            .lastNDays = Range(CELL_EXECFILTER_LASTNDAYS).value
        End If
        Set .specificDates = arrSpecificDatesLong
    End With

    Api.Tws.reqExecutionsEx ActiveCell.row, lExecFilter
End Sub

' clear executions table
Private Sub ClearExecutionsTable_Click()
    Clear
End Sub

Private Sub Clear()
    contractTable.ClearContents
    executionsTable.ClearContents
    rowId = 1
End Sub

'=================
' public methods
'=================
' update execution table
Public Sub UpdateExecution(ByVal orderId As Long, ByVal contract As TWSLib.IContract, ByVal execution As TWSLib.IExecution)
    
    If rowId <= contractTable.Rows.Count Then
        ' contract details
        With contract
            contractTable(rowId, Col_SYMBOL).value = .Symbol
            contractTable(rowId, Col_SECTYPE).value = .SecType
            contractTable(rowId, Col_LASTTRADEDATE).value = .lastTradeDateOrContractMonth
            contractTable(rowId, Col_STRIKE).value = Util.DblMaxStr(.Strike)
            contractTable(rowId, Col_RIGHT).value = .Right
            contractTable(rowId, Col_MULTIPLIER).value = .multiplier
            contractTable(rowId, Col_EXCH).value = .Exchange
            contractTable(rowId, Col_PRIMEXCH).value = .primaryExchange
            contractTable(rowId, Col_CURRENCY).value = .currency
            contractTable(rowId, Col_LOCALSYMBOL).value = .localSymbol
            contractTable(rowId, Col_CONID).value = .conId
        End With
    
        ' execution details
        With execution
            executionsTable(rowId, Col_ORDERID).value = .orderId
            executionsTable(rowId, Col_EXECID).value = .execId
            executionsTable(rowId, Col_TIME).value = .time
            executionsTable(rowId, Col_ACCOUNT).value = .acctNumber
            executionsTable(rowId, Col_EXCHANGE).value = .Exchange
            executionsTable(rowId, Col_SIDE).value = .side
            executionsTable(rowId, Col_QUANTITY).value = Util.DecimalToString(.shares)
            executionsTable(rowId, Col_CUMQTY).value = Util.DecimalToString(.cumQty)
            executionsTable(rowId, Col_PRICE).value = .price
            executionsTable(rowId, Col_AVGPRICE).value = .avgPrice
            executionsTable(rowId, Col_PERMID).value = .permIdStr
            executionsTable(rowId, Col_LIQUIDATION).value = .liquidation
            executionsTable(rowId, Col_CLIENTID).value = .clientId
            executionsTable(rowId, Col_ORDERREF).value = .orderRef
            executionsTable(rowId, Col_EVRULE).value = .evRule
            executionsTable(rowId, Col_EVMULTIPLIER).value = .evMultiplier
            executionsTable(rowId, Col_MODELCODE).value = .modelCode
            executionsTable(rowId, Col_LASTLIQUIDITY).value = .lastLiquidity
            executionsTable(rowId, Col_PENDINGPRICEREVISION).value = .pendingPriceRevision
            executionsTable(rowId, Col_SUBMITTER).value = .submitter
            executionsTable(rowId, Col_OPTEXERCISEORLAPSETYPE).value = .optExerciseOrLapseType
        End With
    
        rowId = rowId + 1
    End If

End Sub

Public Sub Initialise()
    Set contractTable = Me.Range("$A$11:$K$1000")
    Set executionsTable = Me.Range("$L$11:$AF$1000")
    Clear
End Sub

Private Sub Worksheet_Activate()
    Main.Initialise
End Sub


