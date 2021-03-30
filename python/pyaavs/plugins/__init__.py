__author__ = 'Alessio Magro'

# Helper to reduces import names

# Plugin Superclass
from pyfabil.plugins.firmwareblock import FirmwareBlock

# TPM plugins
from pyaavs.plugins.tpm.tpm_test_firmware import TpmTestFirmware

# TPM 1.6 plugins
from pyaavs.plugins.tpm_1_6.tpm_test_firmware import Tpm_1_6_TestFirmware
