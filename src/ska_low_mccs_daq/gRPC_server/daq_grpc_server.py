# -*- coding: utf-8 -*-
#
# This file is part of the SKA SAT.LMC project
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE.txt for more info.
from concurrent import futures
import logging

import grpc
from ska_low_mccs_daq.gRPC_server.generated_code import daq_pb2, daq_pb2_grpc
from pydaq.daq_receiver_interface import DaqModes, DaqReceiver
from ska_control_model import ResultCode


class DaqServer(daq_pb2_grpc.DaqServicer):

    def __init__(self):
        self.daq_instance: DaqReceiver = None
        self._receiver_started: bool = False

    def StartDaq(self, request, context):
        print("IN RPC START")
        modes_to_start = request.modes_to_start
        if not self._receiver_started:
            self.daq_instance.initialise_daq()
            self._receiver_started = True
        try:
            modes_to_start = [DaqModes(mode) for mode in modes_to_start]
        except ValueError as e:
            logging.Logger.error(f"Value Error! Invalid DaqMode supplied! {e}")
        # TODO: callbacks
        callbacks = None
        #callbacks = [self._received_data_callback] * len(modes_to_start)
        self.daq_instance.start_daq(modes_to_start, callbacks)
        return daq_pb2.commandResponse(result_code=ResultCode.OK, message="Daq started.")
    
    def StopDaq(self, request, context):
        print("IN RPC STOP")
        self.daq_instance.stop_daq()
        self._receiver_started = False
        return daq_pb2.commandResponse(result_code=ResultCode.OK, message="Daq stopped.")
    
    def InitDaq(self, request, context):
        print("IN RPC INIT")
        self.daq_instance = DaqReceiver()
        try:
            if request.config != "":
                self.daq_instance.populate_configuration(request.config)
            self.daq_instance.initialise_daq()
            self._receiver_started = True
        # pylint: disable=broad-except
        except Exception as e:
            logging.Logger.error(f"Caught exception in `daq_grcp_server.InitDaq`: {e}")
            return daq_pb2.commandResponse(result_code=ResultCode.FAILED, message=f"Caught exception: {e}")
        return daq_pb2.commandResponse(result_code=ResultCode.OK, message="Daq successfully initialised.")
    
    def ConfigureDaq(self, request, context):
        if request.config != "":
            self.daq_instance.populate_configuration(request.config)
            return daq_pb2.commandResponse(result_code=ResultCode.OK, message="Daq reconfigured.")
        else:
            return daq_pb2.commandResponse(result_code=ResultCode.REJECTED, message="ERROR: No configuration data supplied.")


def serve():
    port = '50051'
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    daq_pb2_grpc.add_DaqServicer_to_server(DaqServer(), server)
    server.add_insecure_port('[::]:' + port)
    server.start()
    print("Server started, listening on " + port)
    server.wait_for_termination()


if __name__ == '__main__':
    logging.basicConfig()
    serve()