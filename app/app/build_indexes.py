"""
Build PloverDB indexes for all configured knowledge-provider endpoints.

This module scans the project root directory for configuration files
named ``config*.json`` and, for each one found, instantiates a
:class:`PloverDB` object and builds its associated database indexes.

The module is designed to be executed as part of the ``app`` package
using Python's module execution mechanism:

    python -m app.build_indexes

It must NOT be run directly as a standalone script (e.g.,
``python build_indexes.py``), because it relies on package-relative
imports. Running it outside of a package context will result in
import errors.

Typical usage::

    cd <PLOVERROOT>/PloverDB/app
    python -m app.build_indexes

This entry point is primarily intended for use during container
builds and deployment workflows to precompute and initialize
database indexes.
"""
import os

# pylint: disable=wrong-import-position
if __name__ == "__main__" and __package__ is None:
    raise SystemExit("ERROR:  Run with: python -m app.build_indexes")
from .plover import PloverDB


def main() -> None:
    """
    Build database indexes for all configured PloverDB endpoints.
    """

    # rest of your logic here
    script_dir = f"{os.path.dirname(os.path.abspath(__file__))}"

    # Build a Plover per KP endpoint (each represented by a separate config file)
    config_files = {file_name for file_name in os.listdir(f"{script_dir}/../")
                    if file_name.startswith("config") and file_name.endswith(".json")}
    for config_file in config_files:
        print(f"Building indexes for {config_file} Plover..")
        plover = PloverDB(config_file_name=config_file)
        plover.build_indexes()


if __name__ == "__main__":
    main()
