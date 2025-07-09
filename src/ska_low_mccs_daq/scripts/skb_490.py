#!/usr/bin/env python3
"""
HDF5 File Analyzer.

A command-line script to recursively analyze HDF5 files and print group names
and data samples.

Usage:
    python skb_490.py filename.hdf5
    python skb_490.py filename.hdf5 --group /path/to/group
    python skb_490.py filename.hdf5 --samples 20
"""

import argparse
import sys
from typing import Optional, Union

import h5py


def print_dataset_info(dataset: h5py.Dataset, name: str, num_samples: int = 10) -> None:
    """
    Print information about a dataset including samples.

    :param dataset: The HDF5 dataset to analyze.
    :param name: The name of the dataset.
    :param num_samples: The number of samples to display from the dataset.
    """
    print(f"Dataset: {name}")
    print(f"  Shape: {dataset.shape}")
    print(f"  Dtype: {dataset.dtype}")

    if dataset.size == 0:
        print("  Data: [empty dataset]")
        return

    # Handle different dimensionalities
    samples_to_show: int
    if len(dataset.shape) == 0:
        # Scalar dataset
        print(f"  Data: {dataset[()]}")
    elif len(dataset.shape) == 1:
        # 1D dataset
        samples_to_show = min(num_samples, dataset.shape[0])
        if samples_to_show < dataset.shape[0]:
            print(
                f"  Data (first {samples_to_show} samples): {dataset[:samples_to_show]}"
            )
        else:
            print(f"  Data: {dataset[:]}")
    else:
        # Multi-dimensional dataset
        samples_to_show = min(num_samples, dataset.shape[0])
        if samples_to_show < dataset.shape[0]:
            print(f"  Data (first {samples_to_show} rows): ")
            for i in range(samples_to_show):
                print(f"    [{i}]: {dataset[i]}")
        else:
            print("  Data: ")
            for i in range(dataset.shape[0]):
                print(f"    [{i}]: {dataset[i]}")

    # Print attributes if any
    if dataset.attrs:
        print("  Attributes:")
        for attr_name, attr_value in dataset.attrs.items():
            print(f"    {attr_name}: {attr_value}")

    print()


def print_group_info(group: h5py.Group, name: str) -> None:
    """
    Print information about a group.

    :param group: The HDF5 group to analyze.
    :param name: The name of the group.
    """
    print(f"Group: {name}")
    if group.attrs:
        print("  Attributes:")
        for attr_name, attr_value in group.attrs.items():
            print(f"    {attr_name}: {attr_value}")
    print()


def recursive_print(
    item: Union[h5py.Group, h5py.Dataset], name: str, num_samples: int = 10
) -> None:
    """
    Recursively print information about HDF5 groups and datasets.

    :param item: The HDF5 group or dataset to analyze.
    :param name: The name of the current item (group or dataset).
    :param num_samples: The number of data samples to display from datasets.
    """
    if isinstance(item, h5py.Group):
        print_group_info(item, name)

        # Process all items in the group
        for key in item.keys():
            full_path: str = f"{name}/{key}" if name != "/" else f"/{key}"
            recursive_print(item[key], full_path, num_samples)

    elif isinstance(item, h5py.Dataset):
        print_dataset_info(item, name, num_samples)


def analyze_hdf5_file(
    filename: str, target_group: Optional[str] = None, num_samples: int = 10
) -> bool:
    """
    Analyze an HDF5 file.

    :param filename: Path to the HDF5 file to analyze.
    :param target_group: Specific group to analyze (optional).
    :param num_samples: Number of data samples to display from datasets.
    :return: True if analysis was successful, False otherwise.
    """
    try:
        with h5py.File(filename, "r") as f:
            print(f"Analyzing HDF5 file: {filename}")
            print("=" * 50)

            if target_group:
                # Print only the specified group
                if target_group in f:
                    print(f"Analyzing specific group: {target_group}")
                    print("-" * 30)
                    recursive_print(f[target_group], target_group, num_samples)
                else:
                    print(f"Error: Group '{target_group}' not found in the file.")
                    print("Available groups:")

                    def list_groups(
                        name: str, obj: Union[h5py.Group, h5py.Dataset]
                    ) -> None:
                        if isinstance(obj, h5py.Group):
                            print(f"  {name}")

                    f.visititems(list_groups)
                    return False
            else:
                # Print all groups and datasets recursively
                recursive_print(f, "/", num_samples)

            return True

    except OSError as e:
        print(f"Error opening file '{filename}': {e}")
        return False

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Unexpected error: {e}")
        return False


def main() -> None:
    """Run script."""
    parser = argparse.ArgumentParser(
        description="Analyze HDF5 files and print group names and data samples",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python skb_490.py data.hdf5
  python skb_490.py data.hdf5 --group /measurement/data
  python skb_490.py data.hdf5 --samples 20
  python skb_490.py data.hdf5 --group /results --samples 5
        """,
    )

    parser.add_argument("filename", help="Path to the HDF5 file to analyze")

    parser.add_argument(
        "--group",
        help="Specific group to analyze (e.g., /measurement/data)",
        default=None,
    )

    parser.add_argument(
        "--samples",
        type=int,
        default=10,
        help="Number of data samples to display (default: 10)",
    )

    args: argparse.Namespace = parser.parse_args()

    # Validate samples parameter
    if args.samples < 1:
        print("Error: Number of samples must be at least 1")
        sys.exit(1)

    # Analyze the file
    success: bool = analyze_hdf5_file(args.filename, args.group, args.samples)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
