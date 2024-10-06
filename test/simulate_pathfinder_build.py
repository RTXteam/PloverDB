"""
This script simulates Pathfinder's build by querying Plover's /get_neighbors endpoint for all nodes in your graph,
divided into batches of 100. Pass in the path to your local nodes jsonlines file to get node IDs from.
Usage: python simulate_pathfinder_build.py <plover endpoint> <path to nodes jsonl file>
Example: python simulate_pathfinder_build.py https://kg2cplover.rtx.ai:9990 kg2c-2.10.1-v1.0-nodes.jsonl
"""

import argparse
import time
from collections import Counter
from typing import Set, Tuple, List

import jsonlines
import requests


def do_get_neighbors_request(node_ids: List[str], plover_endpoint: str) -> Tuple[any, Set[str]]:
    query = {"node_ids": node_ids}
    response = requests.post(f"{plover_endpoint}/get_neighbors", json=query,
                             headers={'content-type': 'application/json'})
    neighbor_ids = {neighbor for neighbors_list in response.json().values()
                    for neighbor in neighbors_list} if response.ok else set()
    return response, neighbor_ids


def split_into_chunks(input_list: List[any], chunk_size: int) -> List[List[any]]:
    num_chunks = len(input_list) // chunk_size if len(input_list) % chunk_size == 0 else (len(input_list) // chunk_size) + 1
    start_index = 0
    stop_index = chunk_size
    all_chunks = []
    for num in range(num_chunks):
        chunk = input_list[start_index:stop_index] if stop_index <= len(input_list) else input_list[start_index:]
        all_chunks.append(chunk)
        start_index += chunk_size
        stop_index += chunk_size
    return all_chunks


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("plover_endpoint")
    arg_parser.add_argument("nodes_jsonl_file")
    args = arg_parser.parse_args()
    start = time.time()

    print(f"Loading all node IDs from {args.nodes_jsonl_file}..")
    with jsonlines.open(args.nodes_jsonl_file) as reader:
        node_ids = [row["id"] for row in reader]
    print(f"Nodes file ({args.nodes_jsonl_file}) contains {len(node_ids)} nodes")

    node_id_batches = split_into_chunks(node_ids, 100)
    print(f"Will send {len(node_id_batches)} sequential batches of 100 node IDs to {args.plover_endpoint}")

    print("query", "status", "duration", "neighbors")
    elapsed_times = []
    status_codes = []
    for index, node_id_batch in enumerate(node_id_batches):
        response, neighbors = do_get_neighbors_request(node_id_batch, args.plover_endpoint)
        print(index + 1, response.status_code, response.elapsed, len(neighbors))
        elapsed_times.append(response.elapsed.total_seconds())
        status_codes.append(response.status_code)

    print(f"Took {round((time.time() - start) / 60, 2)} minutes to send {len(node_ids)} node IDs to get_neighbors in "
          f"batches of 100.")
    print(f"Average query elapsed time: {round(sum(elapsed_times) / float(len(elapsed_times)), 2)} seconds.")
    print(f"Status code counts: {dict(Counter(status_codes))}")


if __name__ == "__main__":
    main()
