import argparse
import tarfile
from pathlib import Path
import re
import shutil
import requests
import os
import semver


class FirmwareManager:

    def __init__(self, bitfile_location="bitfiles", bitfile_pattern="tpm_firmware_*", repo_root=None,
                 remove_firmware=False):

        self.firmware_versions = []
        self.downloaded_firmware_versions = []
        self.not_downloaded_firmware_versions = []
        self.latest_firmware_version = None
        self.root_path = repo_root or Path(__file__).resolve().parents[2]
        wildcard_count = bitfile_pattern.count("*")
        if wildcard_count != 1:
            raise Exception(f"ERROR: bitfile_pattern must have only one wildcard in it, currently has: {wildcard_count}")

        # bitfile_pattern must only contain upper, lower, -, _ or *
        if not re.match(r"^[a-zA-Z\-_*]+$", bitfile_pattern):
            raise Exception(f"ERROR: bitfile_pattern must have only contain Uppercase, Lowercase, _, - or *")

        self.bitfiles_path = self.root_path / bitfile_location
        self.temp_path = self.root_path / "temp_firmware"
        self.bitfile_pattern = bitfile_pattern
        self.artifact_repo_url = "https://artefact.skao.int/service/rest/repository/browse/raw-internal/"

        if remove_firmware:
            print(f"Cleaning {bitfile_location} directory of previous CAR downloads...")
            for version in self.get_local_firmware_list():
                Path(f"{self.version_to_file(version)}.bit").unlink()
                Path(f"{self.version_to_file(version)}.ltx").unlink(missing_ok=True)

    def file_to_version(self, file_path):
        """
        Converts a file path in the format to a version in the format major.minor.patch
        This is stored as a semver object.

        This searches the file path for the number based on self.bitfile_pattern
        It then removes any _, and the adds the .s
        """
        try:
            # replace * with (.*) to match any character, any amount of times
            search_pattern = self.bitfile_pattern.replace('*', '(.*)')
            # Search file path for it, it will be in the format x.y.z
            version_num = re.search(f"{search_pattern}.bit", str(file_path)).group(1)
            # Return semver object of the version
            return semver.VersionInfo.parse(version_num.replace("_", "."))
        except AttributeError:
            return None

    def version_to_file(self, version):
        """
        Converts a version number, to a file path based on
        self.bitfiles_path, self.bitfile_pattern and the extension argument

        The version nuber is converted from the format x.y.z to x_y_z
        """
        bitfile_path = self.bitfiles_path / self.bitfile_pattern
        version_underscore = self.semver_to_underscore(version)
        bitfile_path = str(bitfile_path).replace("*", version_underscore)
        return Path(bitfile_path)

    @staticmethod
    def semver_to_underscore(version):
        """
        converts semver version number to the format x_y_z
        """

        return f"{version.major}_{version.minor}_{version.patch}"

    def get_car_firmware_list(self):
        """
        Gets a list of all firmware available in the car,
        and updates the variables:

        self.firmware_versions
        self.latest_firmware_version
        self.downloaded_firmware_versions
        self.not_downloaded_firmware_versions
        """

        shutil.rmtree(self.temp_path, ignore_errors=True)
        self.temp_path.mkdir()

        try:
            response = requests.get(self.artifact_repo_url)
            response.raise_for_status()  # Raises an error for bad responses
            html_content = response.text
        except requests.exceptions.HTTPError as http_error:
            raise Exception(f"ERROR: Can't reach artifact repository: {http_error}")

        try:
            version_num_list_car = re.findall('>ska-low-sps-tpm-fpga-(.*)\.tar\.gz', html_content)
            version_num_list = [semver.VersionInfo.parse(v_num) for v_num in version_num_list_car]
        except AttributeError:
            raise Exception("ERROR: in processing the artifact repository")

        self.firmware_versions = version_num_list
        self.firmware_versions = sorted(self.firmware_versions)
        self.latest_firmware_version = self.firmware_versions[-1]
        self.downloaded_firmware_versions = self.get_local_firmware_list()
        self.not_downloaded_firmware_versions = [firmware_version for firmware_version in self.firmware_versions
                                                 if firmware_version not in self.downloaded_firmware_versions]
        shutil.rmtree(self.temp_path)
        return self.firmware_versions

    def get_local_firmware_list(self):
        """
        Search self.bitfiles_path folder for self.bitfile_pattern, then converts them into version numbers

        Returns a list of versions
        """
        file_list = list(self.bitfiles_path.glob(self.bitfile_pattern))
        return [self.file_to_version(file) for file in file_list if self.file_to_version(file) is not None]

    def download_firmware_from_car(self, include_ltx=False, nof_downloads=-1):
        """
        Gets the available firmware from the car, and downloads any that aren't already downloaded.

        If nof_downloads is -1 all firmware is downloaded, else the nof_downloads specifies
        the number of latest firmware that is downloaded
        """

        self.get_car_firmware_list()

        if nof_downloads <= -1 or nof_downloads > len(self.not_downloaded_firmware_versions):
            firmware_to_download_list = self.not_downloaded_firmware_versions
        elif nof_downloads != 0:
            firmware_to_download_list = self.not_downloaded_firmware_versions[-nof_downloads:]
        else:
            firmware_to_download_list = []

        for firmware_version in firmware_to_download_list:
            firmware_bitstream_path = Path(str(self.version_to_file(firmware_version)))
            self.download_release(firmware_version, firmware_bitstream_path, include_ltx)


        if nof_downloads == 0:
            print("no FPGA firmware releases have been downloaded")
        elif not firmware_to_download_list:
            print("FPGA Firmware releases are already downloaded")
        else:
            string_firmware_list = [str(ver) for ver in firmware_to_download_list]
            print(f"The following FPGA firmware releases have been downloaded: {', '.join(string_firmware_list)}")

    def download_release(self, firmware_version, bitstream_path, include_ltx=False):
        """
        Downloads an individual version of the firmware from the car

        First a temp directory is made using the path self.temp_path
        The correct tar.gz file is then extracted and then the correct files are copied to their final place
        Then the temp directory is removed
        """

        shutil.rmtree(self.temp_path, ignore_errors=True)
        self.temp_path.mkdir()
        url = f"https://artefact.skao.int/repository/raw-internal/ska-low-sps-tpm-fpga-{firmware_version}.tar.gz"
        response = requests.get(url, timeout=15, stream=True)
        response.raise_for_status()  # Check if the download was successful

        with open(os.path.join(self.temp_path, f"firmware_{firmware_version}.tar.gz"), "wb") as f:
            f.write(response.content)

        with tarfile.open(os.path.join(self.temp_path, f"firmware_{firmware_version}.tar.gz"), "r:gz") as tar:
            tar.extractall(self.temp_path)

        shutil.copy(self.temp_path / "tpm_firmware.bit", f"{bitstream_path}.bit")

        if include_ltx:
            ltx_file_path = self.temp_path / "tpm_firmware.ltx"
            if ltx_file_path.exists():
                shutil.copy(ltx_file_path, f"{str(bitstream_path)}.ltx")

        shutil.rmtree(self.temp_path)

    def get_latest_firmware_version(self):
        """
        Returns the latest available firmware version on the car
        """
        self.get_car_firmware_list()
        return self.latest_firmware_version


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-b', '--bitfile_location', default='bitfiles')
    parser.add_argument('-r', '--repo_root', default=None)
    parser.add_argument('-p', '--bitfile_pattern', default='tpm_firmware_*')
    parser.add_argument('-t', '--temp_path', default='temp_firmware')
    parser.add_argument('-l', '--include_ltx', action='store_true')
    parser.add_argument('-n', '--nof_downloads', default=-1)
    parser.add_argument('-c', '--clean',  action='store_true')

    args = parser.parse_args()

    fm = FirmwareManager(bitfile_location=args.bitfile_location, bitfile_pattern=args.bitfile_pattern,
                         repo_root=args.repo_root, remove_firmware=args.clean)

    fm.download_firmware_from_car(include_ltx=args.include_ltx, nof_downloads=int(args.nof_downloads))
