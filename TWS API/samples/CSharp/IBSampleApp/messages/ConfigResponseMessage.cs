/* Copyright (C) 2025 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

namespace IBSampleApp.messages
{
    class ConfigResponseMessage
    {
        public ConfigResponseMessage(IBApi.protobuf.ConfigResponse configResponseProto)
        {
            ConfigResponseProto = configResponseProto;
        }

        public IBApi.protobuf.ConfigResponse ConfigResponseProto { get; set; }
    }
}
