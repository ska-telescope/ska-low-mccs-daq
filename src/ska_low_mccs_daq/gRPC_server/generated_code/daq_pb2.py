# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: daq.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\tdaq.proto\x12\x03\x64\x61q")\n\x0fstartDaqRequest\x12\x16\n\x0emodes_to_start\x18\x01 \x01(\t"\x10\n\x0estopDaqRequest"\x12\n\x10getConfigRequest"#\n\x11getConfigResponse\x12\x0e\n\x06\x63onfig\x18\x01 \x01(\t"\x12\n\x10\x64\x61qStatusRequest"#\n\x11\x64\x61qStatusResponse\x12\x0e\n\x06status\x18\x01 \x01(\t"H\n\x0f\x63ommandResponse\x12$\n\x0bresult_code\x18\x01 \x01(\x0e\x32\x0f.daq.ResultCode\x12\x0f\n\x07message\x18\x02 \x01(\t""\n\x10\x63onfigDaqRequest\x12\x0e\n\x06\x63onfig\x18\x01 \x01(\t*r\n\nResultCode\x12\x06\n\x02OK\x10\x00\x12\x0b\n\x07STARTED\x10\x01\x12\n\n\x06QUEUED\x10\x02\x12\n\n\x06\x46\x41ILED\x10\x03\x12\x0b\n\x07UNKNOWN\x10\x04\x12\x0c\n\x08REJECTED\x10\x05\x12\x0f\n\x0bNOT_ALLOWED\x10\x06\x12\x0b\n\x07\x41\x42ORTED\x10\x07\x32\xf3\x02\n\x03\x44\x61q\x12\x38\n\x08StartDaq\x12\x14.daq.startDaqRequest\x1a\x14.daq.commandResponse"\x00\x12\x36\n\x07StopDaq\x12\x13.daq.stopDaqRequest\x1a\x14.daq.commandResponse"\x00\x12\x38\n\x07InitDaq\x12\x15.daq.configDaqRequest\x1a\x14.daq.commandResponse"\x00\x12=\n\x0c\x43onfigureDaq\x12\x15.daq.configDaqRequest\x1a\x14.daq.commandResponse"\x00\x12\x43\n\x10GetConfiguration\x12\x15.daq.getConfigRequest\x1a\x16.daq.getConfigResponse"\x00\x12<\n\tDaqStatus\x12\x15.daq.daqStatusRequest\x1a\x16.daq.daqStatusResponse"\x00\x62\x06proto3'
)

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "daq_pb2", globals())
if _descriptor._USE_C_DESCRIPTORS == False:

    DESCRIPTOR._options = None
    _RESULTCODE._serialized_start = 303
    _RESULTCODE._serialized_end = 417
    _STARTDAQREQUEST._serialized_start = 18
    _STARTDAQREQUEST._serialized_end = 59
    _STOPDAQREQUEST._serialized_start = 61
    _STOPDAQREQUEST._serialized_end = 77
    _GETCONFIGREQUEST._serialized_start = 79
    _GETCONFIGREQUEST._serialized_end = 97
    _GETCONFIGRESPONSE._serialized_start = 99
    _GETCONFIGRESPONSE._serialized_end = 134
    _DAQSTATUSREQUEST._serialized_start = 136
    _DAQSTATUSREQUEST._serialized_end = 154
    _DAQSTATUSRESPONSE._serialized_start = 156
    _DAQSTATUSRESPONSE._serialized_end = 191
    _COMMANDRESPONSE._serialized_start = 193
    _COMMANDRESPONSE._serialized_end = 265
    _CONFIGDAQREQUEST._serialized_start = 267
    _CONFIGDAQREQUEST._serialized_end = 301
    _DAQ._serialized_start = 420
    _DAQ._serialized_end = 791
# @@protoc_insertion_point(module_scope)