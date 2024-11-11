from generate_templates import generate_templates
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-a', "--aavs", action='store_true')
args = parser.parse_args()

with open("../.latest-firmware-version") as file:
    latest_firmware_version = file.read().strip(" \n")
    latest_firmware_version = latest_firmware_version.replace(".", "")

bitfile_path = None
tiles = None

if args.aavs:
    bitfile_path = f"/opt/aavs-ci-runner/bitfiles/itpm_v1_5_tpm_test_wrap_sbf{latest_firmware_version}.bit"
    tiles = ["10.132.0.63", "10.132.0.64"]

generate_templates(template_name="ral_ci_runner.yml.template", bitfile_path=bitfile_path, tiles=tiles)

print("AAVS CI config produced")
