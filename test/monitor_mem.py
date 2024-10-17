"""
This script measures memory usage stats on the running instance and records the data to a CSV. It will run
perpetually until you terminate it.
Usage: python monitor_mem.py <interval to measure memory, in seconds> <path to csv file to record data in>
Example: python monitor_mem.py 5 mem_usage.csv
"""

import argparse
import csv
import os
import time
from datetime import datetime

import psutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_current_memory_usage():
    # Thanks https://www.geeksforgeeks.org/how-to-get-current-cpu-and-ram-usage-in-python/
    virtual_mem_usage_info = psutil.virtual_memory()
    memory_percent_used = virtual_mem_usage_info[2]
    memory_used_in_gb = virtual_mem_usage_info[3] / 10 ** 9
    return round(memory_used_in_gb, 1), memory_percent_used


def record_data(timestamp, memory_used, percent_used, file_path):
    with open(file_path, "a") as mem_file:
        writer = csv.writer(mem_file, delimiter="\t")
        writer.writerow([timestamp, memory_used, percent_used])


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("interval")
    arg_parser.add_argument("file_name")
    args = arg_parser.parse_args()
    file_path = f"{SCRIPT_DIR}/{args.file_name}"

    # Initiate the file to save data to
    if not os.path.exists(file_path):
        with open(file_path, "w+") as mem_file:
            writer = csv.writer(mem_file, delimiter="\t")
            writer.writerow(["timestamp", "memory_used_gb", "percent_mem_used"])

    # Record mem usage level every 5 seconds
    while True:
        time.sleep(int(args.interval))
        utc_timestamp = datetime.utcnow()
        memory_used, percent_used = get_current_memory_usage()
        record_data(utc_timestamp, memory_used, percent_used, file_path)


if __name__ == "__main__":
    main()
