from generate_templates import generate_templates
from download_firmware import FirmwareManager
from oxford_subrack_power_control import RALSubrack3
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-a', "--aavs", action='store_true')
args = parser.parse_args()

subrack = RALSubrack3()
subrack.power_cycle_tpm([1, 2])

# If AAVS-System CI Pipeline
if args.aavs:
    fm = FirmwareManager()
    latest_firmware_version = fm.get_latest_firmware_version()
    latest_firmware_version_underscore = fm.semver_to_underscore(latest_firmware_version)
    bitfile_path = f"/opt/aavs-ci-runner/bitfiles/tpm_firmware_{latest_firmware_version_underscore}.bit"
# Else use default bitfile path
else:
    bitfile_path = "/opt/aavs-ci-runner/bitfiles/itpm_v1_5_tpm_test_wrap_ci.bit"

generate_templates(template_name="ral_ci_runner.yml.template", bitfile_path=bitfile_path)

print("AAVS CI prepared")
