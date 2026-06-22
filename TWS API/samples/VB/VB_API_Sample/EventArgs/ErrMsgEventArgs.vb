' Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
' and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.

Class ErrMsgEventArgs

    Property id As Integer

    Property errorTime As Long

    Property errorCode As Integer

    Property errorMsg As String

    Property advancedOrderRejectJson As String

End Class

