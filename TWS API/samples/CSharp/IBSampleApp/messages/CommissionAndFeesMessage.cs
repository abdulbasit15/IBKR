/* Copyright (C) 2024 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using IBApi;

namespace IBSampleApp.messages
{
    class CommissionAndFeesMessage
    {
        public CommissionAndFeesMessage(CommissionAndFeesReport commissionAndFeesReport)
        {
            CommissionAndFeesReport = commissionAndFeesReport;
        }

        public CommissionAndFeesReport CommissionAndFeesReport { get; set; }
    }
}
