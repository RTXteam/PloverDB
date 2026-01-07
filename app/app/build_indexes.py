#!/usr/bin/env python3
import argparse
import os
import sys
# adding this comment to trigger a rebuild 
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover import PloverDB

SCRIPT_DIR = f"{os.path.dirname(os.path.abspath(__file__))}"

arg_parser = argparse.ArgumentParser()
args = arg_parser.parse_args()

# Build a Plover per KP endpoint (each represented by a separate config file)
config_files = {file_name for file_name in os.listdir(f"{SCRIPT_DIR}/../")
                if file_name.startswith("config") and file_name.endswith(".json")}
for config_file in config_files:
    print(f"Building indexes for {config_file} Plover..")
    plover = PloverDB(config_file_name=config_file)
    plover.build_indexes()
