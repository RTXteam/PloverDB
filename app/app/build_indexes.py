#!/usr/bin/env python3
import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover import PloverDB

arg_parser = argparse.ArgumentParser()
args = arg_parser.parse_args()

plover = PloverDB()
plover.build_indexes()


