from typing import ClassVar as _ClassVar
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import any_pb2 as _any_pb2
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

class ConfigurationResponse(_message.Message):
    __slots__ = [
        "acquisition_duration",
        "acquisition_start_time",
        "append_integrated",
        "continuous_period",
        "description",
        "directory",
        "logging",
        "max_filesize",
        "nof_antennas",
        "nof_beam_channels",
        "nof_beam_samples",
        "nof_beams",
        "nof_channel_samples",
        "nof_channels",
        "nof_correlator_channels",
        "nof_correlator_samples",
        "nof_polarisations",
        "nof_raw_samples",
        "nof_station_samples",
        "nof_tiles",
        "observation_metadata",
        "oversampling_factor",
        "raw_rms_threshold",
        "receiver_frame_size",
        "receiver_frames_per_block",
        "receiver_interface",
        "receiver_ip",
        "receiver_nof_blocks",
        "receiver_nof_threads",
        "receiver_ports",
        "sampling_rate",
        "sampling_time",
        "station_config",
        "write_to_disk",
    ]
    ACQUISITION_DURATION_FIELD_NUMBER: _ClassVar[int]
    ACQUISITION_START_TIME_FIELD_NUMBER: _ClassVar[int]
    APPEND_INTEGRATED_FIELD_NUMBER: _ClassVar[int]
    CONTINUOUS_PERIOD_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    DIRECTORY_FIELD_NUMBER: _ClassVar[int]
    LOGGING_FIELD_NUMBER: _ClassVar[int]
    MAX_FILESIZE_FIELD_NUMBER: _ClassVar[int]
    NOF_ANTENNAS_FIELD_NUMBER: _ClassVar[int]
    NOF_BEAMS_FIELD_NUMBER: _ClassVar[int]
    NOF_BEAM_CHANNELS_FIELD_NUMBER: _ClassVar[int]
    NOF_BEAM_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    NOF_CHANNELS_FIELD_NUMBER: _ClassVar[int]
    NOF_CHANNEL_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    NOF_CORRELATOR_CHANNELS_FIELD_NUMBER: _ClassVar[int]
    NOF_CORRELATOR_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    NOF_POLARISATIONS_FIELD_NUMBER: _ClassVar[int]
    NOF_RAW_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    NOF_STATION_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    NOF_TILES_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_METADATA_FIELD_NUMBER: _ClassVar[int]
    OVERSAMPLING_FACTOR_FIELD_NUMBER: _ClassVar[int]
    RAW_RMS_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_FRAMES_PER_BLOCK_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_FRAME_SIZE_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_INTERFACE_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_IP_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_NOF_BLOCKS_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_NOF_THREADS_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_PORTS_FIELD_NUMBER: _ClassVar[int]
    SAMPLING_RATE_FIELD_NUMBER: _ClassVar[int]
    SAMPLING_TIME_FIELD_NUMBER: _ClassVar[int]
    STATION_CONFIG_FIELD_NUMBER: _ClassVar[int]
    WRITE_TO_DISK_FIELD_NUMBER: _ClassVar[int]
    acquisition_duration: int
    acquisition_start_time: int
    append_integrated: bool
    continuous_period: int
    description: str
    directory: str
    logging: bool
    max_filesize: empty
    nof_antennas: int
    nof_beam_channels: int
    nof_beam_samples: int
    nof_beams: int
    nof_channel_samples: int
    nof_channels: int
    nof_correlator_channels: int
    nof_correlator_samples: int
    nof_polarisations: int
    nof_raw_samples: int
    nof_station_samples: int
    nof_tiles: int
    observation_metadata: str
    oversampling_factor: float
    raw_rms_threshold: int
    receiver_frame_size: int
    receiver_frames_per_block: int
    receiver_interface: str
    receiver_ip: str
    receiver_nof_blocks: int
    receiver_nof_threads: int
    receiver_ports: str
    sampling_rate: float
    sampling_time: float
    station_config: empty
    write_to_disk: bool
    def __init__(
        self,
        nof_antennas: _Optional[int] = ...,
        nof_channels: _Optional[int] = ...,
        nof_beams: _Optional[int] = ...,
        nof_polarisations: _Optional[int] = ...,
        nof_tiles: _Optional[int] = ...,
        nof_raw_samples: _Optional[int] = ...,
        raw_rms_threshold: _Optional[int] = ...,
        nof_channel_samples: _Optional[int] = ...,
        nof_correlator_samples: _Optional[int] = ...,
        nof_correlator_channels: _Optional[int] = ...,
        continuous_period: _Optional[int] = ...,
        nof_beam_samples: _Optional[int] = ...,
        nof_beam_channels: _Optional[int] = ...,
        nof_station_samples: _Optional[int] = ...,
        receiver_frames_per_block: _Optional[int] = ...,
        receiver_nof_blocks: _Optional[int] = ...,
        receiver_nof_threads: _Optional[int] = ...,
        receiver_frame_size: _Optional[int] = ...,
        acquisition_duration: _Optional[int] = ...,
        acquisition_start_time: _Optional[int] = ...,
        append_integrated: bool = ...,
        logging: bool = ...,
        write_to_disk: bool = ...,
        sampling_time: _Optional[float] = ...,
        sampling_rate: _Optional[float] = ...,
        oversampling_factor: _Optional[float] = ...,
        receiver_ports: _Optional[str] = ...,
        observation_metadata: _Optional[str] = ...,
        receiver_interface: _Optional[str] = ...,
        receiver_ip: _Optional[str] = ...,
        directory: _Optional[str] = ...,
        description: _Optional[str] = ...,
        station_config: _Optional[_Union[empty, _Mapping]] = ...,
        max_filesize: _Optional[_Union[empty, _Mapping]] = ...,
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

class empty(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

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
