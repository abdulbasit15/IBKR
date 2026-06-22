/* Copyright (C) 2026 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 * and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable. */

using System;
using System.Windows.Forms;
using Google.Protobuf;
using IBSampleApp.messages;

namespace IBSampleApp.ui
{
    class ConfigManager
    {
        public ConfigManager(IBClient ibClient, TextBox configOutput)
        {
            IbClient = ibClient;
            ConfigOutput = configOutput;
        }

        public void RequestConfig()
        {
            IBApi.protobuf.ConfigRequest configRequestProto = new IBApi.protobuf.ConfigRequest();
            configRequestProto.ReqId = new Random(DateTime.Now.Millisecond).Next();
            IbClient.ClientSocket.reqConfigProtoBuf(configRequestProto);
        }

        public void UpdateConfig()
        {
            string updateConfigText = ConfigOutput.Text;
            if (!string.IsNullOrEmpty(updateConfigText))
            {
                IBApi.protobuf.UpdateConfigRequest updateConfigRequestProto = new IBApi.protobuf.UpdateConfigRequest();
                try
                {
                    updateConfigRequestProto = IBApi.protobuf.UpdateConfigRequest.Parser.ParseJson(updateConfigText);
                }
                catch (Exception)
                {
                    MessageBox.Show("Cannot parse update config text", "Error", MessageBoxButtons.OK);
                    return;
                }
                if (!updateConfigRequestProto.HasReqId) updateConfigRequestProto.ReqId = 0;
                IbClient.ClientSocket.updateConfigProtoBuf(updateConfigRequestProto);
            }
        }

        public void HandleConfigResponseMessage(ConfigResponseMessage configResponseMessage)
        {
            var formatter = new JsonFormatter(JsonFormatter.Settings.Default.WithIndentation());
            ConfigOutput.Text = formatter.Format(configResponseMessage.ConfigResponseProto);
        }

        public void HandleUpdateConfigResponseMessage(UpdateConfigResponseMessage updateConfigResponseMessage)
        {
            var formatter = new JsonFormatter(JsonFormatter.Settings.Default.WithIndentation());
            ConfigOutput.Text = formatter.Format(updateConfigResponseMessage.UpdateConfigResponseProto);
        }

        public IBClient IbClient { get; set; }

        public TextBox ConfigOutput { get; set; }
    }
}
