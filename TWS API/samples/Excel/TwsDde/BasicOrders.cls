VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "BasicOrders"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Option Explicit

' constants
Const STR_SHEET_NAME = "BasicOrders"
Const STR_PLACEORDER = "placeOrder"
Const STR_CLEARORDER = "clearOrder"
Const STR_CANCELORDER = "cancelOrder"
Const STR_ORDERSTATUS = "orderStatus"
Const STR_GLOBAL_CANCEL = "globalCancel"
Const STR_WHAT_IF = "whatIf"
Const STR_WHAT_IF_REQUEST = "whatIfRequest"

' cells
Const CELL_SERVER_NAME = "B5" ' cell with server name
Const CELL_GLOBAL_CANCEL_EXT_OPERATOR = "M5" ' cell with global cancel ext operator value
Const CELL_GLOBAL_CANCEL_MANUAL_ORDER_INDICATOR = "N5" ' cell with global cancel manual order indicator

' columns
Const startOfContractColumns = 1 ' contract first column index (symbol)
Const orderBaseColumnsStart = 17 ' index of first column in Order Description
Const orderBaseColumnsEnd = 21 ' index of last column in Order Description
Const errorColumnIndex = 22 ' index of error column
Const idColumnIndex = 23 ' index of id column
Const idCommissionAndFeesIndex = 34 ' index of commission and fees column
Const idManualOrderCancelTime = 174 ' index of manual order cancel time column
Const idExtOperator = 159 ' index of ext operator column
Const idManualOrderIndicator = 183 ' index of manual order indicator column
Const idSlOrderId = 192 ' stop-loss order id
Const idSlOrderType = 193 ' stop-loss order type
Const idPtOrderId = 194 ' profit-taker order id
Const idPtOrderType = 195 ' profit-taker order type
Const orderExtColumnsStart = 59 ' index of first column in Extended Order Attributes
Const orderExtColumnsEnd = 195 ' index of last column in Extended Order Attributes

' rows
Const dataStartRowIndex = 10 ' starting row of data

' variables
Dim orderStatusColumnsArray() As Variant
Dim contractColumnsArray() As Variant
Dim whatIfColumnsArray() As Variant



' ========================================================
' contract columns
' ========================================================
Private Function getContractColumns() As Variant()

    If (Not Not contractColumnsArray) <> 0 Then
        ' do not re-initialize array
        GoTo getContractColumnsEnd
    End If

    contractColumnsArray = Array("SYMBOL", "SECTYPE", "LASTTRADEDATE", "STRIKE", "RIGHT", "MULTIPLIER", "TRADINGCLASS", "EXCH", "PRIMEXCH", "CURRENCY", "LOCALSYMBOL", "CONID", _
        "COMBOLEGS", "DELTANEUTRAL", "SECIDTYPE", "SECID")
    
getContractColumnsEnd:
    getContractColumns = contractColumnsArray
End Function

' ========================================================
' order status columns
' ========================================================
Private Function getOrderStatusColumns() As Variant()
    Dim size As Integer

    If (Not Not orderStatusColumnsArray) <> 0 Then
        ' do not re-initialize array
        GoTo getOrderStatusColumnsEnd
    End If
    
    orderStatusColumnsArray = Array("status", "filled", "remaining", "price", "lastFillPrice", "whyHeld", "mktCapPrice", "parentId", "clientId", "permId")

getOrderStatusColumnsEnd:
    getOrderStatusColumns = orderStatusColumnsArray
End Function

' ========================================================
' what-if columns
' ========================================================
Private Function getWhatIfColumns() As Variant()
    Dim size As Integer

    If (Not Not whatIfColumnsArray) <> 0 Then
        ' do not re-initialize array
        GoTo getWhatIfColumnsEnd
    End If
    
    whatIfColumnsArray = Array("commissionAndFees", "commissionAndFeesCurrency", "currentEquityWithLoan", "currentInitMargin", "currentMaintMargin", _
        "changeEquityWithLoan", "changeInitMargin", "changeMaintMargin", "postEquityWithLoan", "postInitMargin", "postMaintMargin", _
        "marginCurrency", _
        "equityWithLoanBeforeOutsideRTH", "initMarginBeforeOutsideRTH", "maintMarginBeforeOutsideRTH", _
        "equityWithLoanChangeOutsideRTH", "initMarginChangeOutsideRTH", "maintMarginChangeOutsideRTH", _
        "equityWithLoanAfterOutsideRTH", "initMarginAfterOutsideRTH", "maintMarginAfterOutsideRTH", _
        "suggestedSize", "rejectReason", "orderAllocations", _
        "bondAccruedInterest")

getWhatIfColumnsEnd:
    getWhatIfColumns = whatIfColumnsArray
End Function

' ========================================================
' copies extended order attributes to basic orders page
' ========================================================
Sub applyTemplate()
    Call OrderFunctions.applyTemplate(Selection.Rows, orderExtColumnsStart)
End Sub

' ========================================================
' clear order for active row
' ========================================================
Sub clearOrder()
    Dim server As String, id As String, i As Integer, row As Range, lastRowIndex As Integer
    Dim chan As Long
    
    server = util.getServerVal(STR_SHEET_NAME, CELL_SERVER_NAME)
    If server = util.STR_EMPTY Then Exit Sub

    On Error GoTo EndSub
    chan = Application.DDEInitiate(server, STR_CLEARORDER)

    With Worksheets(STR_SHEET_NAME)
        For Each row In Selection.Rows
            lastRowIndex = row.row
            If .Cells(row.row, idColumnIndex).value = STR_EMPTY Then GoTo Continue
            If Not util.hasContractData(Worksheets(STR_SHEET_NAME), dataStartRowIndex, row, startOfContractColumns, getContractColumns()) Then GoTo Continue
            
            id = .Cells(row.row, idColumnIndex).value
            
            clearOrderStatusColumns row
            clearWhatIfColumns row
            Cells(row.row, idSlOrderId).value = ""
            Cells(row.row, idPtOrderId).value = ""
            
            util.sendRequestForChannel server, STR_CLEARORDER, id, chan
            
Continue:
        Next row
    
        .Cells(lastRowIndex, 1).offset(1, 0).Activate
    End With
    
    Application.DDETerminate chan
EndSub:

End Sub

' ========================================================
' clears order status columns
' ========================================================
Sub clearOrderStatusColumns(cell As Range)
    Dim i As Integer
    With Worksheets(STR_SHEET_NAME)
        .Cells(cell.row, idColumnIndex).value = util.STR_EMPTY
        .Cells(cell.row, errorColumnIndex).value = util.STR_EMPTY
        ' order status columns
        orderStatusColumnsArray = getOrderStatusColumns()
        Range(.Cells(cell.row, idColumnIndex + 1), .Cells(cell.row, idColumnIndex + (UBound(orderStatusColumnsArray) - LBound(orderStatusColumnsArray) + 1))).ClearContents
    End With
End Sub

' ========================================================
' clears what-if columns
' ========================================================
Sub clearWhatIfColumns(cell As Range)
    Dim i As Integer
    With Worksheets(STR_SHEET_NAME)
        ' what-if columns
        whatIfColumnsArray = getWhatIfColumns()
        Range(.Cells(cell.row, idCommissionAndFeesIndex), .Cells(cell.row, idCommissionAndFeesIndex + (UBound(whatIfColumnsArray) - LBound(whatIfColumnsArray) + 1))).ClearContents
    End With
End Sub

' ========================================================
' global cancel
' ========================================================
Sub globalCancel()
    Dim server As String
    Dim extOperator As String, manualOrderIndicator As String
    
    server = util.getServerVal(STR_SHEET_NAME, CELL_SERVER_NAME)
    If server = util.STR_EMPTY Then Exit Sub
    
    With Worksheets(STR_SHEET_NAME)
        extOperator = .Range(CELL_GLOBAL_CANCEL_EXT_OPERATOR).value
        manualOrderIndicator = .Range(CELL_GLOBAL_CANCEL_MANUAL_ORDER_INDICATOR).value
    End With
    
    util.sendRequest server, STR_GLOBAL_CANCEL, IDENTIFIER_ZERO & util.QMARK & STR_EMPTY & util.UNDERSCORE & extOperator & util.UNDERSCORE & manualOrderIndicator
End Sub

' ========================================================
' cancel order for active row
' ========================================================
Sub cancelOrder()
    Dim server As String, id As String, manualOrderCancelTime As String, i As Integer, row As Range, lastRowIndex As Integer
    Dim extOperator As String, manualOrderIndicator As String
    Dim chan As Long
    
    server = util.getServerVal(STR_SHEET_NAME, CELL_SERVER_NAME)
    If server = util.STR_EMPTY Then Exit Sub

    On Error GoTo EndSub
    chan = Application.DDEInitiate(server, STR_CANCELORDER)

    With Worksheets(STR_SHEET_NAME)
        For Each row In Selection.Rows
            lastRowIndex = row.row
            If .Cells(row.row, idColumnIndex).value = STR_EMPTY Then GoTo Continue
            If Not util.hasContractData(Worksheets(STR_SHEET_NAME), dataStartRowIndex, row, startOfContractColumns, getContractColumns()) Then GoTo Continue
            
            id = .Cells(row.row, idColumnIndex).value
            manualOrderCancelTime = .Cells(row.row, idManualOrderCancelTime).value
            extOperator = .Cells(row.row, idExtOperator).value
            manualOrderIndicator = .Cells(row.row, idManualOrderIndicator).value
            
            util.sendRequestForChannel server, STR_CANCELORDER, id & util.QMARK & manualOrderCancelTime & util.UNDERSCORE & extOperator & util.UNDERSCORE & manualOrderIndicator, chan
            
Continue:
        Next row
        
        .Cells(lastRowIndex, 1).offset(1, 0).Activate
        
    End With
    
    Application.DDETerminate chan
EndSub:

End Sub

' ========================================================
' place orders for active rows
' ========================================================
Sub placeOrder()
    Dim row As Range, server As String, lastRowIndex As Integer
    Dim rowsData() As RowProcessingData
    Dim ids() As String
    Dim rowCount As Integer
    Dim i As Integer, idIndex As Integer
    Dim baseId As Long
    Dim baseIdStr As String
    
    server = util.getServerVal(STR_SHEET_NAME, CELL_SERVER_NAME)
    If server = util.STR_EMPTY Then Exit Sub
    
    ' Count and initialize
    rowCount = 0
    For Each row In Selection.Rows
        If util.hasContractData(Worksheets(STR_SHEET_NAME), dataStartRowIndex, row, startOfContractColumns, getContractColumns()) Then
            rowCount = rowCount + 1
        End If
    Next row
    
    If rowCount = 0 Then Exit Sub
    ReDim rowsData(1 To rowCount)
    ReDim ids(1 To rowCount)
    
    Dim placeOrderStr As String
    If cbWhatIf.value = True Then
        placeOrderStr = STR_WHAT_IF
    Else
        placeOrderStr = STR_PLACEORDER
    End If
    
    ' ========================================================
    ' FIRST LOOP: Generate sequential IDs
    ' ========================================================
    i = 0
    idIndex = 0
    With Worksheets(STR_SHEET_NAME)
    
        For Each row In Selection.Rows
            lastRowIndex = row.row
            If Not util.hasContractData(Worksheets(STR_SHEET_NAME), dataStartRowIndex, row, startOfContractColumns, getContractColumns()) Then GoTo Continue2
            
            i = i + 1
            idIndex = idIndex + 1
            Set rowsData(i).rowRange = row
            
            baseIdStr = .Cells(row.row, errorColumnIndex + 1).value
            
            If baseIdStr = util.STR_EMPTY Then ' none exists yet -- is original placement as opposed to modify
                If i = 1 Then
                    baseIdStr = OrderFunctions.makeId(server)
                    If baseIdStr = util.STR_EMPTY Then Exit Sub
                    
                    baseId = CLng(baseIdStr)
                    rowsData(i).id = CStr(util.IDENTIFIER_PREFIX & baseId)
                Else
                    rowsData(i).id = CStr(util.IDENTIFIER_PREFIX & baseId + idIndex - 1)
                End If
                
                If .Cells(row.row, idSlOrderType).value <> util.STR_EMPTY Then
                    idIndex = idIndex + 1
                    .Cells(row.row, idSlOrderId).value = CStr(baseId + idIndex - 1)
                End If
                If .Cells(row.row, idPtOrderType).value <> util.STR_EMPTY Then
                    idIndex = idIndex + 1
                    .Cells(row.row, idPtOrderId).value = CStr(baseId + idIndex - 1)
                End If
                
            Else
                baseId = CLng(Right(baseIdStr, Len(baseIdStr) - 2))
                rowsData(i).id = CStr(util.IDENTIFIER_PREFIX & baseId)
            End If
            
            rowsData(i).isValid = True
            ids(i) = rowsData(i).id
            
Continue2:
        Next row
    End With
    
    ' ========================================================
    ' Send orders
    ' ========================================================
    util.sendOrders Worksheets(STR_SHEET_NAME), server, placeOrderStr, ids, Selection.Rows, _
                 startOfContractColumns, getContractColumns(), idColumnIndex, _
                 orderBaseColumnsStart, orderBaseColumnsEnd, orderExtColumnsStart, orderExtColumnsEnd
    
    ' ========================================================
    ' SECOND LOOP: Fill cells and formulas
    ' ========================================================
    For i = 1 To rowCount
        If rowsData(i).isValid Then
            fillCellsAndFormulas server, rowsData(i).rowRange, rowsData(i).id
        End If
    Next i
    
    Worksheets(STR_SHEET_NAME).Cells(lastRowIndex, 1).offset(1, 0).Activate
End Sub

' ========================================================
' Fill cells and formulas of active rows
' ========================================================
Sub fillCellsAndFormulas(server As String, cell As Range, id As String)
    Dim requestStr As String
    Dim i As Integer
    Dim columnsArray() As Variant
    Dim columnIndex As Integer
    
    With Worksheets(STR_SHEET_NAME)
        If id = util.STR_EMPTY Then Exit Sub
        
        If cbWhatIf.value = True Then
            requestStr = STR_WHAT_IF_REQUEST
            columnsArray = getWhatIfColumns()
            columnIndex = idCommissionAndFeesIndex
        Else
            requestStr = STR_ORDERSTATUS
            columnsArray = getOrderStatusColumns()
            columnIndex = idColumnIndex + 1
        End If
        
        .Cells(cell.row, errorColumnIndex + 1).value = id
        
        .Cells(cell.row, errorColumnIndex).Formula = util.composeLink(server, requestStr, id, util.STR_ERROR)
        If util.cleanOnError(.Cells(cell.row, errorColumnIndex)) Then
            clearOrderStatusColumns cell
            clearWhatIfColumns cell
            Exit Sub
        End If
        
        For i = 0 To UBound(columnsArray) - LBound(columnsArray)
            .Cells(cell.row, columnIndex + i).Formula = util.composeLink(server, requestStr, id, columnsArray(i))
        Next i
    End With
End Sub
