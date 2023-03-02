from typing import ClassVar as _ClassVar
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

ABORTED: ResultCode
DESCRIPTOR: _descriptor.FileDescriptor
FAILED: ResultCode
NOT_ALLOWED: ResultCode
OK: ResultCode
QUEUED: ResultCode
REJECTED: ResultCode
STARTED: ResultCode
UNKNOWN: ResultCode

class CallInfo(_message.Message):
    __slots__ = ["data_types_received", "extra_info", "files_written"]
    DATA_TYPES_RECEIVED_FIELD_NUMBER: _ClassVar[int]
    EXTRA_INFO_FIELD_NUMBER: _ClassVar[int]
    FILES_WRITTEN_FIELD_NUMBER: _ClassVar[int]
    data_types_received: str
    extra_info: str
    files_written: str
    def __init__(
        self,
        data_types_received: _Optional[str] = ...,
        files_written: _Optional[str] = ...,
        extra_info: _Optional[str] = ...,
    ) -> None: ...

class CallState(_message.Message):
    __slots__ = ["state"]

    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    LISTENING: CallState.State
    RECEIVING: CallState.State
    STATE_FIELD_NUMBER: _ClassVar[int]
    STOPPED: CallState.State
    state: CallState.State
    def __init__(
        self, state: _Optional[_Union[CallState.State, str]] = ...
    ) -> None: ...

class commandResponse(_message.Message):
    __slots__ = ["message", "result_code"]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESULT_CODE_FIELD_NUMBER: _ClassVar[int]
    message: str
    result_code: ResultCode
    def __init__(
        self,
        result_code: _Optional[_Union[ResultCode, str]] = ...,
        message: _Optional[str] = ...,
    ) -> None: ...

class configDaqRequest(_message.Message):
    __slots__ = ["config"]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    config: str
    def __init__(self, config: _Optional[str] = ...) -> None: ...

class daqStatusRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class daqStatusResponse(_message.Message):
    __slots__ = ["status"]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: str
    def __init__(self, status: _Optional[str] = ...) -> None: ...

class getConfigRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class getConfigResponse(_message.Message):
    __slots__ = ["config"]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    config: str
    def __init__(self, config: _Optional[str] = ...) -> None: ...

class startDaqRequest(_message.Message):
    __slots__ = ["modes_to_start"]
    MODES_TO_START_FIELD_NUMBER: _ClassVar[int]
    modes_to_start: str
    def __init__(self, modes_to_start: _Optional[str] = ...) -> None: ...

class startDaqResponse(_message.Message):
    __slots__ = ["call_info", "call_state"]
    CALL_INFO_FIELD_NUMBER: _ClassVar[int]
    CALL_STATE_FIELD_NUMBER: _ClassVar[int]
    call_info: CallInfo
    call_state: CallState
    def __init__(
        self,
        call_state: _Optional[_Union[CallState, _Mapping]] = ...,
        call_info: _Optional[_Union[CallInfo, _Mapping]] = ...,
    ) -> None: ...

class stopDaqRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class ResultCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
