from generate_templates import generate_templates
from download_firmware import FirmwareManager
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-a', "--aavs", action='store_true')
args = parser.parse_args()

fm = FirmwareManager()
latest_firmware_version = fm.get_latest_firmware_version().replace(".", "_")

bitfile_path = None

if args.aavs:
    bitfile_path = f"/opt/aavs-ci-runner/bitfiles/tpm_firmware_{latest_firmware_version}.bit"

generate_templates(template_name="ral_ci_runner.yml.template", bitfile_path=bitfile_path)

print("AAVS CI config produced")
