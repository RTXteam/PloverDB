"""
This script does sequential testing of Plover endpoints. Pass in the Plover endpoint you want to test,
the ID of a node in the graph that has neighbors (ideally quite a few), how many queries you want to run, and the
batch size for each query (call that N).
The script randomly selects N node IDs for each query from a pool of node IDs. That pool of node IDs begins
by containing only your starting node ID, but the neighbors returned from each query are added to that pool, so it
quickly grows (and is capped at 1,000,000 node IDs). This (essentially) allows each query to be different.
Usage: python simulate_sequential.py <plover endpoint> <query endpoint> <start node ID> <number of queries> <batch size>
Example: python simulate_sequential.py https://kg2cplover.rtx.ai:9990 get_neighbors CHEMBL.COMPOUND:CHEMBL112 1000 100
"""

import argparse
import os
import random
import time
from collections import Counter
from typing import Set, Tuple

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def do_get_neighbors_request(node_ids: Set[str], plover_endpoint: str) -> Tuple[any, Set[str]]:
    query = {"node_ids": node_ids}
    response = requests.post(f"{plover_endpoint}/get_neighbors", json=query,
                             headers={'content-type': 'application/json'})
    neighbor_ids = {neighbor for neighbors_list in response.json().values()
                    for neighbor in neighbors_list} if response.ok else set()
    return response, neighbor_ids


def do_query_request(node_ids: Set[str], plover_endpoint: str) -> Tuple[any, Set[str]]:
    qg = {"nodes": {"n00": {"ids": list(node_ids)}, "n01": {"categories": ["biolink:NamedThing"]}},
          "edges": {"e00": {"subject": "n00", "object": "n01"}}}
    query = {"message": {"query_graph": qg}}
    response = requests.post(f"{plover_endpoint}/query", json=query,
                             headers={'content-type': 'application/json'})
    neighbor_ids = set(response.json().get("message", dict()).get("knowledge_graph", dict()).get("nodes", dict())) if response.ok else set()
    return response, neighbor_ids


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("plover_endpoint")
    arg_parser.add_argument("query_endpoint")
    arg_parser.add_argument("start_node")
    arg_parser.add_argument("num_queries")
    arg_parser.add_argument("batch_size")
    args = arg_parser.parse_args()
    start = time.time()

    random.seed(21)

    query_endpoint = args.query_endpoint.strip("/").lower()
    print(f"Will do {args.num_queries} queries to /{query_endpoint}, with {args.batch_size} random IDs in "
          f"each query (except for the first few queries, while the pool of node IDs is being built up).")
    print(f"Starting node is {args.start_node}.")
    print("query", "status", "duration", "batch_size", "neighbors")
    all_node_ids = {args.start_node}
    elapsed_times = []
    status_codes = []
    for query_num in range(int(args.num_queries)):
        random_node_ids = random.sample(list(all_node_ids), min(int(args.batch_size), len(all_node_ids)))
        if query_endpoint == "get_neighbors":
            response, neighbor_ids = do_get_neighbors_request(random_node_ids, args.plover_endpoint)
        elif query_endpoint == "query":
            response, neighbor_ids = do_query_request(random_node_ids, args.plover_endpoint)
        else:
            raise ValueError(f"Invalid query endpoint. Choices are: 'get_neighbors', 'query'")
        if len(all_node_ids) < 1000000:
            all_node_ids |= neighbor_ids
        print(query_num, response.status_code, response.elapsed, len(random_node_ids), len(neighbor_ids))
        elapsed_times.append(response.elapsed.total_seconds())
        status_codes.append(response.status_code)

    print(f"Finished with {len(all_node_ids)} unique node ids.")
    print(f"Took {round((time.time() - start) / 60, 2)} minutes to do {args.num_queries} /{query_endpoint} "
          f"queries with a batch size of {args.batch_size}.")
    print(f"Average query elapsed time: {round(sum(elapsed_times) / float(len(elapsed_times)), 2)} seconds.")
    print(f"Status code counts: {dict(Counter(status_codes))}")


if __name__ == "__main__":
    main()
