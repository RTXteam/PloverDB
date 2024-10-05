"""
This script does sequential testing of the /get_neighbors endpoint. Pass in the Plover endpoint you want to test,
the ID of a node in the graph that has neighbors (ideally quite a few), how many queries you want to run, and the
batch size for each query (call that N).
The script randomly selects N node IDs for each query from a pool of node IDs. That pool of node IDs begins
by containing only your starting node ID, but the neighbors returned from each query are added to that pool, so it
quickly grows (and is capped at 1,000,000 node IDs). This (essentially) allows each query to be different.
Usage: python test_get_neighbors_sequential.py <plover endpoint> <start node ID> <number of queries> <batch size>
Example: python test_get_neighbors_sequential.py https://kg2cplover.rtx.ai:9990 CHEMBL.COMPOUND:CHEMBL112 1000 100
"""

import argparse
import os
import random
import time
from collections import Counter

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


arg_parser = argparse.ArgumentParser()
arg_parser.add_argument("plover_endpoint")
arg_parser.add_argument("start_node")
arg_parser.add_argument("num_queries")
arg_parser.add_argument("batch_size")
args = arg_parser.parse_args()


start = time.time()

random.seed(21)

print(f"Will do {args.num_queries} queries, with {args.batch_size} random IDs in "
      f"each query (except for the first few queries, while the pool of node IDs is being built up). "
      f"Starting node is {args.start_node}.")
all_node_ids = {args.start_node}
elapsed_times = []
status_codes = []
for query_num in range(int(args.num_queries)):
    random_node_ids = random.sample(list(all_node_ids), min(int(args.batch_size), len(all_node_ids)))
    query = {"node_ids": random_node_ids}
    response = requests.post(f"{args.plover_endpoint}/get_neighbors", json=query,
                             headers={'content-type': 'application/json'})
    all_neighbors = {neighbor for neighbors_list in response.json().values()
                     for neighbor in neighbors_list} if response.ok else set()
    if len(all_node_ids) < 1000000:
        all_node_ids |= all_neighbors
    print(query_num, response.status_code, response.elapsed, f"neighbors total: {len(all_neighbors)}")
    elapsed_times.append(response.elapsed.total_seconds())
    status_codes.append(response.status_code)

print(f"Finished with {len(all_node_ids)} unique node ids.")
print(f"Took {round((time.time() - start) / 60, 2)} minutes to do {args.num_queries} queries with a "
      f"batch size of {args.batch_size}.")
print(f"Average query elapsed time: {round(sum(elapsed_times) / float(len(elapsed_times)), 2)} seconds.")
print(f"Status code counts: {dict(Counter(status_codes))}")
