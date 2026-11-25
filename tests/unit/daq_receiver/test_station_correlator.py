"""Tests for the station beam correlator mode of DaqReceiver.

Mocks replace the C++ consumer, so these tests do not need the DAQ libraries or
a GPU.
"""

from __future__ import annotations

import ctypes
from pathlib import Path
from unittest import mock

import h5py
import numpy as np
import pytest

from ska_low_mccs_daq.pydaq.daq_receiver_interface import (
    DaqModes,
    DaqReceiver,
    tcc_upper_triangular_order,
)

SUBSTATION_IDS = [4, 9, 2]
START_CHANNEL = 100
NOF_CHANNELS = 2
NOF_SAMPLES = 2 * 2048
SPEAD_STATION_ID = 345
NOF_BASELINES = len(SUBSTATION_IDS) * (len(SUBSTATION_IDS) + 1) // 2
NOF_STOKES = 4


@pytest.fixture(name="daq")
def daq_fixture(tmp_path: Path) -> DaqReceiver:
    """
    Return a DaqReceiver configured for the station correlator mode.

    :param tmp_path: a temporary directory for the data files.

    :return: the DaqReceiver
    """
    daq = DaqReceiver()
    daq.populate_configuration(
        {
            "directory": str(tmp_path),
            "receiver_ip": "127.0.0.1",
            # As given on the command line
            "station_correlator_substation_ids": ",".join(
                str(i) for i in SUBSTATION_IDS
            ),
            "station_correlator_start_channel": START_CHANNEL,
            "nof_station_correlator_channels": NOF_CHANNELS,
            "nof_station_correlator_samples": NOF_SAMPLES,
        }
    )
    return daq


def start_station_correlator(daq: DaqReceiver) -> tuple[mock.Mock, mock.Mock]:
    """
    Start the station correlator mode with the C++ consumer mocked out.

    :param daq: the DaqReceiver to start.

    :return: the mocked _start_consumer and the external callback
    """
    external_callback = mock.Mock()
    with mock.patch.object(
        daq, "_start_consumer", return_value=DaqReceiver.Result.Success
    ) as start_consumer:
        daq.start_daq(DaqModes.STATION_CORRELATOR_DATA, external_callback)
    return start_consumer, external_callback


def deliver(daq: DaqReceiver, tcc_vis: np.ndarray, timestamp: float) -> None:
    """
    Call the station correlator callback as the C++ consumer does.

    :param daq: the DaqReceiver whose callback to call.
    :param tcc_vis: visibilities in TCC order, [channel][baseline][stokes].
    :param timestamp: integration timestamp.
    """
    ints = np.empty(2 * tcc_vis.size, dtype=np.int32)
    ints[0::2] = tcc_vis.real.ravel()
    ints[1::2] = tcc_vis.imag.ravel()

    metadata = DaqReceiver.StationCorrelatorMetadata(
        time_taken=1.5,
        h2d_time=0.5,
        kern_time=0.25,
        d2h_time=0.125,
        scan_id=7,
        nof_samples=NOF_SAMPLES,
        nof_packets=12,
        station_id=SPEAD_STATION_ID,
        start_channel=START_CHANNEL,
        nof_channels=NOF_CHANNELS,
        nof_substations=len(SUBSTATION_IDS),
    )
    metadata.substation_ids[: len(SUBSTATION_IDS)] = SUBSTATION_IDS

    daq._station_correlator_callback(
        ints.ctypes.data_as(ctypes.POINTER(ctypes.c_void_p)),
        timestamp,
        ctypes.cast(ctypes.pointer(metadata), ctypes.POINTER(ctypes.c_void_p)),
    )


def tcc_test_vis(offset: int = 0) -> np.ndarray:
    """
    Return TCC visibilities with a different value at every position.

    :param offset: added to every value, to tell integrations apart.

    :return: [channel][baseline][stokes] complex64 array
    """
    vis = np.zeros((NOF_CHANNELS, NOF_BASELINES, NOF_STOKES), dtype=np.complex64)
    for channel, baseline, stokes in np.ndindex(vis.shape):
        value = offset + channel * 100 + baseline * 10 + stokes
        vis[channel, baseline, stokes] = value - 1j * (value + 1)
    return vis


@pytest.mark.parametrize("nof_receivers", range(1, 8))
def test_baseline_order_matches_tc_correlator(nof_receivers: int) -> None:
    """
    Check the baseline reorder against the loops in _tc_correlator_callback.

    :param nof_receivers: number of correlator inputs.
    """
    # The grid reorder in _tc_correlator_callback, as indices
    tcc_index = {}
    counter = 0
    for i in range(nof_receivers):
        for j in range(i + 1):
            tcc_index[(j, i)] = counter
            counter += 1
    expected = [
        tcc_index[(i, j)] for i in range(nof_receivers) for j in range(i, nof_receivers)
    ]

    assert list(tcc_upper_triangular_order(nof_receivers)) == expected


def test_substation_ids_are_parsed_from_a_string(daq: DaqReceiver) -> None:
    """
    Check that a comma-separated substation list becomes a list of ints.

    :param daq: the DaqReceiver under test.
    """
    assert (
        daq.get_configuration()["station_correlator_substation_ids"] == SUBSTATION_IDS
    )


def test_start_configures_the_consumer(daq: DaqReceiver) -> None:
    """
    Check the configuration passed to the C++ consumer on start.

    :param daq: the DaqReceiver under test.
    """
    start_consumer, _ = start_station_correlator(daq)

    start_consumer.assert_called_once_with(
        "stationcorrelator",
        {
            "substation_ids": SUBSTATION_IDS,
            "start_channel": START_CHANNEL,
            "nof_channels": NOF_CHANNELS,
            "nof_samples": NOF_SAMPLES,
            "max_packet_size": 8500,
        },
        daq._callbacks[DaqModes.STATION_CORRELATOR_DATA],
        dynamic_callback=True,
    )
    assert daq._running_consumers[DaqModes.STATION_CORRELATOR_DATA]
    assert daq._sampling_time[DaqModes.STATION_CORRELATOR_DATA] == pytest.approx(
        NOF_SAMPLES * 1.08e-6
    )


def test_start_without_substations_fails(daq: DaqReceiver) -> None:
    """
    Check that the mode cannot start without substations to correlate.

    :param daq: the DaqReceiver under test.
    """
    daq._config["station_correlator_substation_ids"] = None
    with pytest.raises(Exception, match="station_correlator_substation_ids"):
        start_station_correlator(daq)
    assert not daq._running_consumers.get(DaqModes.STATION_CORRELATOR_DATA, False)


@pytest.mark.parametrize(
    ("consumer", "from_tcc_library"),
    [("stationcorrelator", True), ("tensorcorrelator", True), ("stationdata", False)],
)
def test_tcc_consumers_load_from_the_tcc_library(
    daq: DaqReceiver, consumer: str, from_tcc_library: bool
) -> None:
    """
    Check that both TCC consumers are loaded from libaavsdaq_tcc.so.

    :param daq: the DaqReceiver under test.
    :param consumer: the consumer to start.
    :param from_tcc_library: whether it should come from the TCC library.
    """
    library = mock.Mock(
        **{
            "loadConsumer.return_value": 0,
            "initialiseConsumer.return_value": 0,
            "startConsumerDynamic.return_value": 0,
        }
    )

    with mock.patch.object(daq, "_daq_library", library):
        result = daq._start_consumer(consumer, {}, None, dynamic_callback=True)

    assert result == DaqReceiver.Result.Success
    loaded_from = library.loadConsumer.call_args[0][0]
    expected = daq._tcc_correlator_path if from_tcc_library else daq._daq_library_path
    assert loaded_from == expected


def test_stop_daq_stops_the_consumer(daq: DaqReceiver) -> None:
    """
    Check that stopping the DAQ stops the station correlator consumer.

    :param daq: the DaqReceiver under test.
    """
    start_station_correlator(daq)

    with mock.patch.object(
        daq, "_stop_consumer", return_value=DaqReceiver.Result.Success
    ) as stop_consumer, mock.patch.object(
        daq, "_call_stop_receiver", return_value=DaqReceiver.Result.Success.value
    ):
        daq.stop_daq()

    stop_consumer.assert_called_once_with("stationcorrelator")
    assert not daq._running_consumers[DaqModes.STATION_CORRELATOR_DATA]
    assert daq._external_callbacks[DaqModes.STATION_CORRELATOR_DATA] is None


def test_callback_writes_upper_triangular_visibilities(daq: DaqReceiver) -> None:
    """
    Check what the callback writes to file and passes to the external callback.

    :param daq: the DaqReceiver under test.
    """
    _, external_callback = start_station_correlator(daq)
    timestamp = 1.7e9
    sampling_time = daq._sampling_time[DaqModes.STATION_CORRELATOR_DATA]

    deliver(daq, tcc_test_vis(), timestamp)
    deliver(daq, tcc_test_vis(offset=1000), timestamp + sampling_time)

    # The file has upper-triangular baselines with XY and YX swapped
    order = tcc_upper_triangular_order(len(SUBSTATION_IDS))
    swap = [0, 2, 1, 3]
    expected = np.stack(
        [
            tcc_test_vis()[:, order][:, :, swap],
            tcc_test_vis(offset=1000)[:, order][:, :, swap],
        ]
    )

    assert external_callback.call_count == 2
    args, kwargs = external_callback.call_args
    assert args[0] == "station_correlator"
    assert kwargs == {
        "nof_packets": 12,
        "nof_samples": NOF_SAMPLES,
        "correlator_time_taken": 1.5,
        "host_to_device_copy_time": 0.5,
        "correlator_solve_time": 0.25,
        "device_to_host_copy_time": 0.125,
        "station_ids": {None: SPEAD_STATION_ID},
    }

    # Both integrations are appended to the same file
    filename = args[1]
    assert external_callback.call_args_list[0][0][1] == filename
    with h5py.File(filename, "r") as f:
        np.testing.assert_array_equal(f["correlation_matrix"]["data"][:], expected)
        np.testing.assert_allclose(
            f["sample_timestamps"]["data"][:, 0],
            [timestamp, timestamp + sampling_time],
        )

        root = f["root"].attrs
        assert root["n_antennas"] == len(SUBSTATION_IDS)
        assert root["n_chans"] == NOF_CHANNELS
        assert root["n_baselines"] == NOF_BASELINES
        assert root["channel_id"] == START_CHANNEL

        observation = f["observation_info"].attrs
        assert list(observation["substation_ids"]) == SUBSTATION_IDS
        assert observation["start_channel"] == START_CHANNEL
