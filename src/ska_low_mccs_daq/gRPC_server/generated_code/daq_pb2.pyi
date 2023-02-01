from typing import ClassVar as _ClassVar
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

class startDaqRequest(_message.Message):
    __slots__ = ["modes_to_start"]
    MODES_TO_START_FIELD_NUMBER: _ClassVar[int]
    modes_to_start: str
    def __init__(self, modes_to_start: _Optional[str] = ...) -> None: ...

class stopDaqRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class ResultCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
