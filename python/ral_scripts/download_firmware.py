import argparse
import tarfile
from pathlib import Path
import re
import shutil
import requests
import os


class FirmwareManager:

    def __init__(self, bitfile_location="bitfiles", bitfile_pattern="tpm_firmware_*.bit",
                 temp_path="temp_firmware", repo_root=None):

        self.firmware_versions = []
        self.downloaded_firmware_versions = []
        self.not_downloaded_firmware_versions = []
        self.latest_firmware_version = None
        if repo_root is None:
            self.root_path = Path(__file__).resolve().parents[2]
        else:
            self.repo_root = repo_root
        self.bitfiles_path = self.root_path / bitfile_location
        self.temp_path = self.root_path / temp_path
        self.bitfile_pattern = bitfile_pattern

    def file_to_version(self, file_path):
        """
        Converts a file path to a version in the format x.y.z

        This searches the file path for the number based on self.bitfile_pattern
        It then removes any _, and the adds the .s
        """
        try:
            search_pattern = self.bitfile_pattern.replace('.', '\.')
            search_pattern = search_pattern.replace('*', '(.*)')
            version_num = re.search(search_pattern, str(file_path)).group(1)
            version_num_list = list(version_num.replace("_", ""))
            version_num_list.insert(1, '.')
            version_num_list.insert(3, '.')
            return ''.join(version_num_list)
        except AttributeError:
            return None

    def version_to_file(self, version, extension=".bit"):
        """
        Converts a version number, to a file path based on
        self.bitfiles_path, self.bitfile_pattern and the extension argument

        The version nuber is converted from the format x.y.z to x_y_z
        """
        bitfile_path = self.bitfiles_path / self.bitfile_pattern
        version_underscore = version.replace(".", "_")
        bitfile_path = str(bitfile_path).replace("*", version_underscore)
        file_path = bitfile_path.replace(".bit", extension)
        return Path(file_path)

    def get_available_firmware_versions(self):
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
        artifact_repo_url = "https://artefact.skao.int/service/rest/repository/browse/raw-internal/"

        try:
            response = requests.get(artifact_repo_url)
            response.raise_for_status()  # Raises an error for bad responses
            html_content = response.text
        except requests.exceptions.HTTPError:
            raise Exception("ERROR: Can't reach artifact repository")

        try:
            version_num_list = re.findall('>ska-low-sps-tpm-fpga-(.*)\.tar\.gz', html_content)
        except AttributeError:
            raise Exception("ERROR: in processing the artifact repository")

        self.firmware_versions = version_num_list
        self.firmware_versions = sorted(self.firmware_versions, key=self.split_version_num)
        self.latest_firmware_version = self.firmware_versions[-1]
        self.downloaded_firmware_versions = self.get_downloaded_firmware_versions()
        self.not_downloaded_firmware_versions = [firmware_version for firmware_version in self.firmware_versions
                                                 if firmware_version not in self.downloaded_firmware_versions]
        shutil.rmtree(self.temp_path)
        return self.firmware_versions

    def get_downloaded_firmware_versions(self):
        """
        Search self.bitfiles_path folder for self.bitfile_pattern, then converts them into version numbers

        Returns a list of version numbers
        """
        file_list = list(self.bitfiles_path.glob(self.bitfile_pattern))
        return [self.file_to_version(file) for file in file_list if self.file_to_version(file) is not None]

    @staticmethod
    def split_version_num(version):
        """
        Splits a version number of x.y.z into a tuple
        """
        return tuple(map(int, version.split('.')))

    def download_firmware(self, include_ltx=False):
        """
        Gets the available firmware from the car, and downloads any that aren't already downloaded.
        """

        self.get_available_firmware_versions()
        firmware_to_download_list = self.not_downloaded_firmware_versions

        for firmware_version in firmware_to_download_list:
            firmware_bitstream_path = Path(str(self.version_to_file(firmware_version)))
            self.download_firmware_single(firmware_version, firmware_bitstream_path, include_ltx)

        if not firmware_to_download_list:
            print("Firmware is all up to date")
        else:
            print(f"The following firmware has been downloaded: {', '.join(firmware_to_download_list)}")

    def download_firmware_single(self, firmware_version, bitstream_path, include_ltx=False):
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

        shutil.copy(self.temp_path/"tpm_firmware.bit", f"{bitstream_path}")

        if include_ltx:
            shutil.copy(self.temp_path/"tpm_firmware.bit", f"{str(bitstream_path).replace('.bit', '')}.ltx")

        shutil.rmtree(self.temp_path)

    def get_latest_firmware_version(self):
        """
        Returns the latest available firmware version on the car
        """
        self.get_available_firmware_versions()
        return self.latest_firmware_version


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-b', '--bitfile_location', default='bitfiles')
    parser.add_argument('-r', '--repo_root', default=None)
    parser.add_argument('-p', '--bitfile_pattern', default='tpm_firmware_*.bit')
    parser.add_argument('-t', '--temp_path', default='temp_firmware')
    parser.add_argument('-l', '--include_ltx', action='store_true')

    args = parser.parse_args()

    fm = FirmwareManager(bitfile_location=args.bitfile_location, bitfile_pattern=args.bitfile_pattern,
                         temp_path=args.temp_path, repo_root=args.repo_root)

    fm.download_firmware(include_ltx=args.include_ltx)
