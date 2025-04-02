import glob
import multiprocessing
import subprocess as sp
import logging
import os
import re


def safe_read(filepath):
    """ Error handling for reading all content of specified path
    :param filepath: Path to file"""

    try:
        with open(filepath, 'r') as f:
            return f.read()
    except:
        return None


def check_installed(tool):
    """ Check if tool is installed """
    try:
        p = sp.Popen(tool, stdout=sp.PIPE, stderr=sp.PIPE)
        _, _ = p.communicate()
    except OSError:
        return False

    return True


def process_cpu_list(cpu_list):
    """ Convert string representation of CPU list of an array of ints """
    res = []
    cpu_list = cpu_list.rstrip("\n")
    for cpu_range in cpu_list.split(','):
        if cpu_range.find('-') != -1:
            start, end = cpu_range.split('-')
            res.extend(range(int(start), int(end) + 1))
        else:
            res.append(int(cpu_range))
    return res


def check_interface_exists(interface):
    """ Check that the network interface exists. Uses sysfs """
    interfaces = os.listdir("/sys/class/net")
    if interface not in interfaces:
        logging.error("Could not find interface. Detected interfaces are: {}".format(', '.join(interfaces)))
        return False
    return True


def stop_irq_balancer():
    """ Stop IRQ balancer"""
    p = sp.Popen(["service", "irqbalance", "stop"], stdout=sp.PIPE, stderr=sp.PIPE)
    _, _ = p.communicate()

    logging.info("Stop irqbalance service")


def configure_huge_pages(nof_huge_pages):
    """ Use maximum number of huge pages """

    p = sp.Popen(["sysctl", "-w", "vm.nr_hugepages={}".format(str(nof_huge_pages))], stdout=sp.PIPE, stderr=sp.PIPE)
    output, _ = p.communicate()

    if output != b"" and output.find(nof_huge_pages):
        logging.info("Allocated {} huge pages".format(nof_huge_pages))
        return True
    else:
        logging.warning("Could not allocate {} huge pages".format(nof_huge_pages))
        return False


def get_cache_information():
    """ Get cache information. Uses sysfs"""

    # Loop through all caches
    cache_info = {}
    processed_cores = []
    for core in range(multiprocessing.cpu_count()):
        for cache_index in glob.glob("/sys/devices/system/cpu/cpu{}/cache/index*".format(core)):
            type = safe_read("{}/type".format(cache_index))
            level = safe_read("{}/level".format(cache_index))
            cpu_list = safe_read("{}/shared_cpu_list".format(cache_index))

            # Ignore L1 instruction cache (interested in Data and Unified caches)
            if type.lower().strip('\n') != "instruction":
                cache_cores = process_cpu_list(cpu_list)
                if len(set(cache_cores).intersection(set(processed_cores))) == 0:
                    if "L{}".format(int(level)) in cache_info.keys():
                        cache_info["L{}".format(int(level))].append(cache_cores)
                    else:
                        cache_info["L{}".format(int(level))] = [cache_cores]
    return cache_info


def set_number_of_rx_queues(interface, nof_queues):
    """ Change the number of RX queues for the interface
    :param interface: Network interface
    :param nof_queues: Number of required RX queues """

    # Check if ethtool is installed
    if not check_installed("ethtool"):
        logging.error("ethtool not installed, cannot continue")
        exit()

    # Get number of supported RX queues
    p = sp.Popen(["sudo", "ethtool", "-l", interface], stdout=sp.PIPE, stderr=sp.PIPE)
    output, error = p.communicate()

    if error.find(b"Operation not supported") != -1:
        logging.error("Required ethtool operation not supported")
        return False
    elif error.find(b"bad command line") != -1:
        logging.error("Malformed ethtool command")
        return False

    # Parse maximum supported settings
    queue_type = "rx"
    maximum = re.search(r"Pre-set maximums:\s*\nRX:\s+(?P<size>\d+)", output.decode())
    if maximum:
        maximum = int(maximum.groupdict()['size'])
    else:
        logging.warning("Could not detect maximum RX ring buffer size for {}. Skipping".format(interface))
        return

    # Some network cards only allow combined TX/RX queues. Check for combined
    if maximum == 0:
        queue_type = "combined"
        maximum = re.search(r"Pre-set maximums:\s*.*Combined:\s+(?P<size>\d+).*Current hardware settings", output.decode(),
                            re.DOTALL)
        if maximum:
            maximum = int(maximum.groupdict()['size'])
        else:
            logging.warning("Could not detect maximum RX ring buffer size for {}. Skipping".format(interface))
            return False

    # Check that request number of queues is within range
    if nof_queues > maximum:
        logging.warning("Requested number of queues ({}) exceeds maximum ({}). Not setting".format(nof_queues, maximum))
        return False

    p = sp.Popen(["sudo", "ethtool", "-L", interface, queue_type, str(nof_queues)], stdout=sp.PIPE, stderr=sp.PIPE)
    _, error = p.communicate()

    if error.find(b"Operation not supported") != -1:
        logging.error("Required ethtool operation not supported")
        return False
    elif error.find(b"bad command line") != -1:
        logging.error("Malformed ethtool command")
        return False
    elif error.find(b"Invalid argument") != -1:

        logging.error("Invalid number of RX queues ({}) for {} requested".format(nof_queues, interface))
        return False
    else:
        logging.info("Set number of RX queues for {} to {}".format(interface, nof_queues))
        return True


def optimise_network_interface(interface):
    """ Fine tune parameters for network interface
    :param interface: Network interface"""

    # Check if ethtool is installed
    if not check_installed("ethtool"):
        logging.error("ethtool not installed, cannot continue")
        exit()

    # Get maximum RX ring buffer size
    p = sp.Popen(["ethtool", "-g", interface], stdout=sp.PIPE, stderr=sp.PIPE)
    output, _ = p.communicate()
    maximum = re.search(r"Pre-set maximums:\s*\nRX:\s+(?P<size>\d+)", output.decode())
    if maximum:
        maximum = maximum.groupdict()['size']
    else:
        logging.warning("Could not detect maximum RX ring buffer size for {}. Skipping".format(interface))

    # Get maximum RX ring buffer size
    p = sp.Popen(["sudo", "ethtool", "-G", interface, 'rx', maximum], stdout=sp.PIPE, stderr=sp.PIPE)
    output, error = p.communicate()
    logging.info("Set RX ring buffer size for {} to {}".format(interface, maximum))

    # Enable Jumbo frames
    p = sp.Popen(["ifconfig", interface, "mtu", "9000"], stdout=sp.PIPE, stderr=sp.PIPE)
    _, _ = p.communicate()
    logging.info("Enabled Jumbo frames for {}".format(interface))

    # Disable Ethernet flow control
    p = sp.Popen(["ethtool", "-A", interface, "autoneg", "off", "rx", "off", "tx", "off"],
                 stdout=sp.PIPE, stderr=sp.PIPE)
    _, _ = p.communicate()
    logging.info("Disabled Ethernet flow control (pause frames) for {}".format(interface))

    logging.info("Link speed is not set by this script, please make sure the correct link speed is set")


def optimise_cpu_cores(cores):
    """ Optimise core settings (like scaling governor)"""

    # Set CPU scaling governor to performance
    for c in cores:
        with open("/sys/devices/system/cpu/cpu{}/cpufreq/scaling_governor".format(c), 'w') as f:
            f.write("performance")


def get_interrupt_numbers(interface, queues):
    """ Get the IRQ numbers:
     :param interface: Network interface
     :param queues: List of RX queues for which IRQ numbers are required """

    with open("/proc/interrupts", 'r') as f:
        interrupt_list = f.readlines()[1:]

    interrupt_mapping = {}
    for line in interrupt_list:
        res = re.search(r"\s*(?P<irq>\d+):.*" + interface + r"-*(?P<core>\d+)", line, re.DOTALL)
        if res:
            values = res.groupdict()
            if int(values['core']) in queues:
                interrupt_mapping[int(values['core'])] = values['irq']

    return interrupt_mapping


def set_interrupt_affinity(interface, rx_queues):
    """ Set the interrupt to core mapping for the interface
    :param interface: The network interface
    :param rx_queues: The number of RX queues """

    # Check interface information
    info = get_interface_information(interface)

    # Stop IRQ balancer
    stop_irq_balancer()

    # Set the number of RX queues
    if not set_number_of_rx_queues(interface, rx_queues):
        return

    # Keep track of what gets assigned and which core are chosen to run
    # the receiver threads
    interrupt_cores = []
    receiver_cores = []

    # Decide what to do depending on number of cores vs number of queues
    # and whether the core are hyper-threaded or not
    nof_cores = len(info['cpu_list'])

    # We are running on a CPU with threading enabled
    nof_threads_per_core = len(info['cache_sharing']['L1'][0])
    if nof_threads_per_core > 1:
        logging.info("CPU threading enabled. Each core has {} threads".format(nof_threads_per_core))

    # Check whether we can assigned an interrupt to each physical core
    if nof_cores / nof_threads_per_core >= rx_queues:
        # We can assign an RX queue to a separate physical core and place receiver threads and
        # the shared CPU core thread
        logging.info("RX queues will be mapped to separate physical cores")
        for i in range(rx_queues):
            interrupt_cores.append(info['cache_sharing']['L1'][i][0])
            receiver_cores.append(info['cache_sharing']['L1'][i][1])

    elif nof_cores > rx_queues:
        # We can assigned an RX queue to a separate logical core and place receiver threads on the same core
        logging.info("RX queues will be mapped to separate logical cores (Hyperthreads)")
        for i in range(rx_queues):
            interrupt_cores.append(info['cache_sharing']['L1'][i / nof_threads_per_core][i % nof_threads_per_core])
            receiver_cores.append(info['cache_sharing']['L1'][i / nof_threads_per_core][i % nof_threads_per_core])

    else:
        # We need to distribute multiple RX queues to each physical core
        for i in range(rx_queues):
            logging.info("RX queues will be multiplexed amongst available logical cores (Hyperthreads/physical)")
            interrupt_cores.append(info['cache_sharing']['L1'][i % (nof_cores / nof_threads_per_core)][0])
            if nof_threads_per_core == 1:
                receiver_cores.append(info['cache_sharing']['L1'][i % (nof_cores / nof_threads_per_core)][0])
            else:
                receiver_cores.append(info['cache_sharing']['L1'][i % (nof_cores / nof_threads_per_core)][1])

    # Get interrupt affinity for RX queues
    interrupt_mapping = get_interrupt_numbers(interface, range(rx_queues))

    # Set interrupt affinity
    for k, v in interrupt_mapping.iteritems():
        with open("/proc/irq/{}/smp_affinity".format(v), 'w') as f:
            low_bits = ((2 ** interrupt_cores[k]) & 0xFFFFFFFF)
            hi_bits = ((2 ** (interrupt_cores[k]) >> 32) & 0xFFFFFFFF)
            f.write("%08x,%08x" % (hi_bits, low_bits))
            logging.info("RX queue {} mapped to core {} (and mapped to IRQ {})".format(k, interrupt_cores[k], v))

    logging.info("Place receiver threads on cores: {}".format(', '.join([str(x) for x in receiver_cores])))
    logging.info("If custom packet steering rules will be applied make sure to distribute them to these cores")

    # All done, return
    return interrupt_cores, receiver_cores


def get_interface_information(interface):
    """ Get interface information """
    # noinspection PyDictCreation
    info = {}

    # Get NUMA node
    info['numa_node'] = safe_read("/sys/class/net/{}/device/numa_node".format(interface))
    if info["numa_node"] is not None:
        info["numa_node"] = int(info["numa_node"])

    # Get CPU list
    info['cpu_list'] = safe_read("/sys/class/net/{}/device/local_cpulist".format(interface))
    if info['cpu_list'] is not None:
        info['cpu_list'] = process_cpu_list(info['cpu_list'])

    # Get cache sharing information
    info['cache_sharing'] = get_cache_information()

    return info


if __name__ == "__main__":
    from sys import stdout, argv

    # Set logging
    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    line_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch = logging.StreamHandler(stdout)
    ch.setFormatter(line_format)
    log.addHandler(ch)

    # Check for root privileges
    if os.getuid() != 0:
        logging.error("Root privileges are required to run this script. Re-run with sudo "
                      "or ask a system administrator")
        exit()

    # Process arguments
    from optparse import OptionParser

    parser = OptionParser(usage="usage: %configure_interface [options]")
    parser.add_option("-i", "--interface", action="store", dest="interface",
                      default="eth0", help="Interface to configure [default: eth0]")
    parser.add_option("--rx-queues", action="store", dest="rx_queues", type="int",
                      default=8, help="Required number of RX queues [default: 8]")
    parser.add_option("--nof-hugepages", action="store", dest="hugepages", type="int",
                      default=1024, help="Number of huge pages [default: 1024]")
    (opts, args) = parser.parse_args(argv[1:])

    # Convert interface to lower case (precaution)
    opts.interface = opts.interface.lower()

    # Check if interface exists
    if not check_interface_exists(opts.interface):
        exit()

    # Optimise interface parameters
    optimise_network_interface(opts.interface)

    # Get interrupt and receiver thread affinity
    result = set_interrupt_affinity(opts.interface, opts.rx_queues)

    # Optimise cores
    if result is not None:
        interrupt_cores, receiver_cores = result
        optimise_cpu_cores(set(interrupt_cores).union(set(receiver_cores)))

    # Optimise system
    stop_irq_balancer()
    configure_huge_pages(opts.hugepages)
