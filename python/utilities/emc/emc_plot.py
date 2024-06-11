import sys
import glob
import numpy as np
import datetime
import calendar
from matplotlib import pyplot as plt
from matplotlib.gridspec import GridSpec
from pydaq.persisters import ChannelFormatFileManager, FileDAQModes


def fname_to_tstamp(date_time_string):
    time_parts = date_time_string.split('_')
    d = datetime.datetime.strptime(time_parts[0], "%Y%m%d")  # "%d/%m/%Y %H:%M:%S"
    timestamp = calendar.timegm(d.timetuple())
    timestamp += int(time_parts[1])# - (60 * 60 * 8)  # Australian Time
    return timestamp


def closest(serie, num):
    return serie.tolist().index(min(serie.tolist(), key=lambda z: abs(z - num)))


def dt_to_timestamp(d):
    return calendar.timegm(d.timetuple())


def ts_to_datestring(tstamp, formato="%Y-%m-%d %H:%M:%S"):
    return datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(tstamp), formato)


def dB2Linear(valueIndB):
    return pow(10, valueIndB / 10.0)


def linear2dB(valueInLinear):
    return 10.0 * np.log10(valueInLinear)


def dBm2Linear(valueIndBm):
    return dB2Linear(valueIndBm) / 1000.


def linear2dBm(valueInLinear):
    return linear2dB(valueInLinear * 1000.)


def moving_average(xx, w):
    return np.convolve(xx, np.ones(w), 'valid') / w


# def on_motion(event):
#     global text_coord, fig
#     if event.xdata is not None:
#         text_coord.set_text("%3.1f, %3.1f" % (event.xdata, event.ydata))
#         fig.canvas.draw()


if __name__ == "__main__":
    from optparse import OptionParser
    from sys import argv
    # global text_coord, fig
    parser = OptionParser(usage="usage: %emc_plot_integrated_data [options]")
    parser.add_option("--directory", action="store", dest="directory",
                      default="/storage/integrated_channels_test",
                      help="Directory containing Raw data (default: /storage/integrated_channels_test)")
    # parser.add_option("--tiles", action="store", dest="tiles", type=int,
    #                   default=8, help="Number of Tiles")
    parser.add_option("--samplerate", action="store", dest="samplerate", type=int,
                      default=8e8, help="ADC Sample Rate (Default 800 MSPS: 800e6")
    parser.add_option("--spectrogram", action="store_true", dest="spectrogram",
                      default=False, help="Plot Spectrogram")
    parser.add_option("--wclim", action="store", dest="wclim",
                      default="0,25", help="Waterfall Color Scale Limits (Def: '0,25')")
    parser.add_option("--start", action="store", dest="start",
                      default="", help="Start time for filter (YYYY-mm-DD_HH:MM:SS)")
    parser.add_option("--stop", action="store", dest="stop",
                      default="", help="Stop time for filter (YYYY-mm-DD_HH:MM:SS)")
    parser.add_option("--date", action="store", dest="date",
                      default="", help="Date in YYYY-MM-DD (required)")
    parser.add_option("--move_avg_len", action="store", dest="move_avg_len", type=int,
                      default=1, help="Moving Average Window Length")
    parser.add_option("--title", action="store", dest="title",
                      default="", help="String to be added in the picture (example: EMC Test #1)")
    (opts, args) = parser.parse_args(argv[1:])

    t_start = 0
    t_stop = 0
    antenne = np.arange(16)
    move_avg_len = opts.move_avg_len
    if move_avg_len < 1:
        move_avg_len = 1

    datapath = opts.directory
    if not datapath[-1] == "/":
        datapath += "/"
    print("\nChecking Directory: %s" % datapath)

    if opts.date:
        try:
            t_date = datetime.datetime.strptime(opts.date, "%Y-%m-%d")
            t_start = dt_to_timestamp(t_date)
            t_stop = dt_to_timestamp(t_date) + (60 * 60 * 24)
            sys.stdout.write("\nStart Time:  " + ts_to_datestring(t_start) + "    Timestamp: " + str(t_start))
            sys.stdout.write("\nStop  Time:  " + ts_to_datestring(t_stop) + "    Timestamp: " + str(t_stop))
        except:
            sys.stdout.write("\nBad date format detected (must be YYYY-MM-DD)")
    else:
        if opts.start:
            try:
                t_start = dt_to_timestamp(datetime.datetime.strptime(opts.start, "%Y-%m-%d_%H:%M:%S"))
                sys.stdout.write("\nStart Time:  " + ts_to_datestring(t_start) + "    Timestamp: " + str(t_start))
            except:
                sys.stdout.write("\nBad t_start time format detected (must be YYYY-MM-DD_HH:MM:SS)")
        if opts.stop:
            try:
                t_stop = dt_to_timestamp(datetime.datetime.strptime(opts.stop, "%Y-%m-%d_%H:%M:%S"))
                sys.stdout.write("\nStop  Time:  " + ts_to_datestring(t_stop) + "    Timestamp: " + str(t_stop))
            except:
                sys.stdout.write("\nBad t_stop time format detected (must be YYYY-MM-DD_HH:MM:SS)")

    fig = plt.figure(figsize=(16, 9), facecolor='w')
    plt.rc('axes', axisbelow=True)
    gs = GridSpec(6, 5, left=0.08, right=0.95, bottom=0.1, top=0.96, hspace=1.6, wspace=0.4)
    ax_spgr = fig.add_subplot(gs[0:3, 0:3])
    # cid = fig.canvas.mpl_connect('motion_notify_event', on_motion)
    ax_pow = fig.add_subplot(gs[3:5, 0:3])
    ax_tstamps = fig.add_subplot(gs[5, 0:3])
    ax_spectrum = fig.add_subplot(gs[0:3, 3:5])
    ax_text = fig.add_subplot(gs[3:6, 3:5])
    ax_text.set_axis_off()
    wclim = (float(opts.wclim.split(",")[0]), float(opts.wclim.split(",")[1]))

    file_manager = ChannelFormatFileManager(root_path=datapath, daq_mode=FileDAQModes.Integrated)
    # tiles = [i+1 for i in range(opts.tiles)]
    l = sorted(glob.glob(datapath + "channel_integ_0_*_0.hdf5"))[0]

    t_cnt = 0
    t_stamps = []
    orari = []

    max_hold = {}
    min_hold = {}
    channel_power = {}

    orari = []
    deltas = []
    delta = 0

    sys.stdout.write("\n")
    # Check for latest DAQ files
    listdir = sorted(glob.glob(datapath + "channel_integ_0_*_0.hdf5"), reverse=True)
    if listdir:
        fname_datetime = listdir[0][-21:-7]

        # Check for number of Tile Files for that datetime
        lista_files = sorted(glob.glob(datapath + "channel_integ_*_%s_0.hdf5" % fname_datetime))
        dic = file_manager.get_metadata(timestamp=fname_to_tstamp(lista_files[0][-21:-7]), tile_id=0)
        sys.stdout.write("\nFound %d Tiles, %d samples\n" % (len(lista_files), dic["n_blocks"]))
        deltas = np.array([np.zeros(dic["n_blocks"])] * len(lista_files))
        deltas[:][:] = np.nan
        orari = np.array([np.zeros(dic["n_blocks"])] * len(lista_files))
        orari[:][:] = np.nan
        max_peak_spgram = np.array([np.zeros(dic["n_chans"])] * dic["n_blocks"])
        max_peak_spgram[:][:] = np.nan

        for nTpm, fname in enumerate(lista_files):
            for ant in antenne:
                for pol in [0, 1]:
                    channel_power["%02d_%02d" % (nTpm, pol+2*ant)] = np.zeros(dic["n_blocks"])
                    channel_power["%02d_%02d" % (nTpm, pol+2*ant)][:] = np.nan

        if (opts.date == "") and (opts.start == "") and (opts.stop == ""):
            data, timestamps = file_manager.read_data(timestamp=fname_to_tstamp(lista_files[0][-21:-7]), tile_id=0, n_samples=dic["n_blocks"])
            t_start = timestamps[0]
            t_stop = timestamps[-1]
            sys.stdout.write("No time specified, using the full data sets\n")
            sys.stdout.write("\nStart Time:  " + ts_to_datestring(int(t_start)) + "    Timestamp: " + str(t_start))
            sys.stdout.write("\nStop  Time:  " + ts_to_datestring(int(t_stop)) + "    Timestamp: " + str(t_stop) + "\n")

        sys.stdout.write("\n")
        for nTpm, fname in enumerate(lista_files):
            dic = file_manager.get_metadata(timestamp=fname_to_tstamp(fname[-21:-7]), tile_id=nTpm)
            if dic:
                data, timestamps = file_manager.read_data(timestamp=fname_to_tstamp(fname[-21:-7]), tile_id=nTpm, n_samples=dic["n_blocks"])
                t_cnt = 0
                if timestamps[0] > t_stop:
                    break
                # Check if the file contains useful timestamps
                if not t_start > timestamps[-1]:
                    if not t_stop < timestamps[0]:
                        for i, t in enumerate(timestamps):
                            # Check if it is a good timestamp
                            #print(nTpm, t_cnt, i, t_start, t_stop, t[0])
                            if t_start <= t[0] <= t_stop:
                                orario = ts_to_datestring(t[0], formato="%Y-%m-%d %H:%M:%S")
                                sys.stdout.write("\rProcessing Tile-%02d, timestamp %d --> %s" % (nTpm + 1, t[0], orario))
                                orari[nTpm][t_cnt] = t[0]
                                if not t_cnt:
                                    prev = t[0]
                                else:
                                    delta = t[0] - prev
                                    prev = t[0]
                                    deltas[nTpm][t_cnt] = delta
                                for ant in antenne:
                                    #print(nTpm, ant)
                                    for pol in [0, 1]:
                                        if not str(t[0]) in max_hold.keys():
                                            max_hold[str(t[0])] = data[:, ant, pol, i]
                                            min_hold[str(t[0])] = data[:, ant, pol, i]
                                        else:
                                            max_hold[str(t[0])] = np.maximum(max_hold[str(t[0])], data[:, ant, pol, i])
                                            min_hold[str(t[0])] = np.minimum(min_hold[str(t[0])], data[:, ant, pol, i])
                                        with np.errstate(divide='ignore'):
                                            chan_power = 10 * np.log10(np.sum(data[1:, ant, pol, i]))
                                        channel_power["%02d_%02d" % (nTpm, pol+2*ant)][t_cnt] = chan_power
                                t_cnt = t_cnt + 1

        # Requested moving average window cannot be greater than the available data
        if move_avg_len > len(max_hold):
            move_avg_len = len(max_hold) - 1

        # Compute DateTime Tick for X Axes
        x_tick = []
        x_ticklabels = []
        if t_stop - t_start > 3600:
            step = datetime.datetime.utcfromtimestamp(orari[0][0]).hour - 1
            div = np.array([1, 2, 3, 4, 6, 8, 12, 24])
            for z in orari[0]:
                if not np.isnan(z):
                    tz = datetime.datetime.utcfromtimestamp(z)
                    if not tz.hour == step:
                        # print str(orari[z])
                        x_tick += [dt_to_timestamp(tz)]
                        if tz.hour == 0:
                            x_ticklabels += [datetime.datetime.strftime(tz, "%m-%d")]
                        else:
                            x_ticklabels += [tz.hour]
                        # step = (step + 1) % 24
                        step = tz.hour

            decimation = div[closest(div, len(x_tick) / 24)]
            # print("\n\nDecimation", decimation, "XTick[0]", x_tick[0], "Label", x_ticklabels[0], "\n")
            skip = decimation - datetime.datetime.utcfromtimestamp(x_tick[0]).hour % decimation
            x_tick = x_tick[skip::decimation]
            x_ticklabels = x_ticklabels[skip::decimation]
        else:
            # equal less than 1 hour
            prec = datetime.datetime.utcfromtimestamp(orari[0][0]).minute - 1
            div = np.array([1, 2, 5, 10, 20, 30])
            for z in orari[0]:
                if not np.isnan(z):
                    tz = datetime.datetime.utcfromtimestamp(z)
                    if not z == prec:
                        x_tick += [z]
                        x_ticklabels += [datetime.datetime.strftime(tz, "%H:%M:%S")]
                        prec = z
            decimation = div[closest(div, len(x_tick) / 20)]
            skip = decimation - int(x_tick[0]) % decimation
            x_tick = x_tick[skip::decimation]
            x_ticklabels = x_ticklabels[skip::decimation]

        # force -inf to zero
        for n, k in enumerate(max_hold.keys()):
            with np.errstate(divide='ignore'):
                spettro_max = 10 * np.log10(max_hold[k])
            spettro_max[spettro_max==-np.inf] = 0
            max_peak_spgram[n][:] = spettro_max
            # max_peak_spgram = np.concatenate((max_peak_spgram, [spettro_max]), axis=0)
            with np.errstate(divide='ignore'):
                spettro_min = 10 * np.log10(min_hold[k])
            spettro_min[spettro_min==-np.inf] = 0

        # moving average on power traces
        for k in sorted(channel_power.keys()):
            t_move = moving_average(np.array(channel_power[k]), move_avg_len)
            ax_pow.plot(orari[0][move_avg_len-1:], t_move - t_move[0])

        # plot power traces
        ax_pow.set_xticks(x_tick)
        ax_pow.set_xticklabels(x_ticklabels, rotation=45, fontsize=8)
        ax_pow.set_ylim(-5, 5)
        ax_pow.set_xlim(orari[0][move_avg_len-1], orari[0][-1])
        ax_pow.grid()
        ax_pow.set_ylabel("dB", fontsize=12)
        ax_pow.set_title("RMS Power")

        # plot spectrogram
        # first_empty, max_peak_spgram = max_peak_spgram[:1], max_peak_spgram[1:]
        ax_spgr.imshow(np.rot90(max_peak_spgram), extent=[orari[0][0], orari[0][-1], 0, 400], interpolation='none', aspect='auto', cmap='jet', clim=wclim)
        ax_spgr.set_xticks(x_tick)
        ax_spgr.set_xticklabels(x_ticklabels, rotation=45, fontsize=8)
        ax_spgr.yaxis.set_label_text("MHz", fontsize=14)
        ax_spgr.set_title("Max Peak Aggregated Spectrogram")

        # plot spectra
        sampling_frequency = opts.samplerate
        nsamples = 1024
        RBW = sampling_frequency / nsamples
        asse_x = np.arange(nsamples / 2) * RBW / 1000.
        asse_x = asse_x / 1000.
        ax_spectrum.plot(asse_x, spettro_max, label="Max Peak Spectrum")
        ax_spectrum.plot(asse_x, spettro_min, label="Min Peak Spectrum")
        ax_spectrum.grid()
        ax_spectrum.legend()
        ax_spectrum.set_xlabel("MHz", fontsize=12)
        ax_spectrum.set_ylabel("norm. dB", fontsize=12)
        ax_spectrum.set_xlim(asse_x[1], asse_x[-1])
        ax_spectrum.set_title("Aggregated Spectrum Analysis")

        #ax_tstamps.annotate("1° PKT", (orari[0][0]+5, 10), fontsize=9, rotation=90, color='k')
        for nTpm, fname in enumerate(lista_files):
            ax_tstamps.plot(orari[nTpm], deltas[nTpm])
        ax_tstamps.set_xticks(x_tick)
        ax_tstamps.set_xticklabels(x_ticklabels, rotation=45, fontsize=8)
        ax_tstamps.set_ylim(0, 60)
        ax_tstamps.set_xlim(orari[0][move_avg_len-1], orari[0][-1])
        ax_tstamps.set_xlabel("UTC Time", fontsize=12)
        ax_tstamps.set_ylabel("sec", fontsize=12)
        ax_tstamps.set_title("TPM Packets Timestamp Deltas")

        ax_text.set_axis_off()
        ax_text.plot(range(100), color='w')
        ax_text.set_xlim(0, 100)
        ax_text.annotate("Start Time: ", (0.1, 80), fontsize=12, color='g')
        ax_text.annotate(ts_to_datestring(orari[0][0]) + " UTC", (30, 80), fontsize=12, color='g')
        ax_text.annotate("Stop Time: ", (0.1, 70), fontsize=12, color='g')
        ax_text.annotate(ts_to_datestring(orari[0][-1]) + " UTC", (30, 70), fontsize=12, color='g')

        # text_coord = ax_text.annotate("Cursor Coordinates: ", (0.1, 40), fontsize=12, color='k')
        #
        # from options Title
        if not opts.title == "":
            ax_text.annotate(opts.title, (0.1, 100), fontsize=12, color='k')

        plt.show()

    sys.stdout.write("\n")
