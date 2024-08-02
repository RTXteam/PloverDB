#!/usr/bin/env python3
import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover import PloverDB

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('nodes_url', nargs='?', default=None)
arg_parser.add_argument('edges_url', nargs='?', default=None)
args = arg_parser.parse_args()

plover = PloverDB()
plover.build_indexes(nodes_file_url=args.nodes_url, edges_file_url=args.edges_url)


