/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

namespace IBSampleApp.messages
{
    class UpdateConfigResponseMessage
    {
        public UpdateConfigResponseMessage(IBApi.protobuf.UpdateConfigResponse updateConfigResponseProto)
        {
            UpdateConfigResponseProto = updateConfigResponseProto;
        }

        public IBApi.protobuf.UpdateConfigResponse UpdateConfigResponseProto { get; set; }
    }
}
