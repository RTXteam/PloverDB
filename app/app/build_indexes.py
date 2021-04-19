#!/usr/bin/env python3
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover import PloverDB

plover = PloverDB()
plover.build_indexes()
