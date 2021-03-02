#!/usr/bin/env python3
import argparse
import json
from pprint import PrettyPrinter
from time import sleep
from typing import List, Dict, Tuple


def add_to_index(node_a_id: str, node_b_id: str, node_b_categories: List[str], predicate: str, edge_id: str,
                 main_index: Dict[str, Dict[str, Dict[str, Dict[str, str]]]]):
    if node_a_id not in main_index:
        main_index[node_a_id] = dict()
    if predicate not in main_index[node_a_id]:
        main_index[node_a_id][predicate] = dict()
    for category in node_b_categories:
        if category not in main_index[node_a_id][predicate]:
            main_index[node_a_id][predicate][category] = dict()
        main_index[node_a_id][predicate][category][node_b_id] = edge_id


def build_indexes(is_test: bool):
    kg2c_file_name = "kg2c.json" if not is_test else "kg2c_test.json"
    with open(kg2c_file_name, "r") as nodes_file:
        kg2c_dict = json.load(nodes_file)
    node_lookup_map = {node["id"]: node for node in kg2c_dict["nodes"]}
    edge_lookup_map = {edge["id"]: edge for edge in kg2c_dict["edges"]}

    if is_test:
        # Narrow down our test JSON file to make sure all node IDs used by edges appear in our node_lookup_map
        node_ids_used_by_edges = {edge["subject"] for edge in edge_lookup_map.values()}.union(edge["object"] for edge in edge_lookup_map.values())
        node_lookup_map_trimmed = {node_id: node_lookup_map[node_id] for node_id in node_ids_used_by_edges if node_id in node_lookup_map}
        node_lookup_map = node_lookup_map_trimmed
        edge_lookup_map_trimmed = {edge_id: edge for edge_id, edge in edge_lookup_map.items() if edge["subject"] in node_lookup_map and edge["object"] in node_lookup_map}
        edge_lookup_map = edge_lookup_map_trimmed

    # Then build the main index
    main_index = dict()
    for edge_id, edge in edge_lookup_map.items():
        subject_id = edge["subject"]
        object_id = edge["object"]
        predicate = edge["simplified_edge_label"]
        subject_categories = node_lookup_map[subject_id]["types"]
        object_categories = node_lookup_map[object_id]["types"]
        # Record this edge in both the forwards and backwards direction (we only support undirected queries)
        add_to_index(subject_id, object_id, object_categories, predicate, edge_id, main_index)
        add_to_index(object_id, subject_id, subject_categories, predicate, edge_id, main_index)

    return main_index, node_lookup_map, edge_lookup_map


def answer_query(json_file_name, main_index, node_lookup_map, edge_lookup_map) -> Tuple[Dict[str, Dict[str, Dict[str, any]]], List[List[str]]]:
    # Load the query and grab the relevant pieces of it
    with open(json_file_name, "r") as query_file:
        trapi_query = json.load(query_file)
    qnodes_with_curies = [qnode_key for qnode_key in trapi_query["nodes"] if trapi_query["nodes"][qnode_key].get("id")]
    input_qnode_key = qnodes_with_curies[0]
    output_qnode_key = list(set(trapi_query["nodes"]).difference({input_qnode_key}))[0]
    qedge = next(qedge for qedge in trapi_query["edges"].values())
    # TODO: also support curie--curie queries, and curie lists, and multiple categories
    input_curie = trapi_query["nodes"][input_qnode_key]["id"]
    output_category = trapi_query["nodes"][output_qnode_key]["category"]
    predicate = qedge["predicate"]
    print(f"Query to answer is: {input_curie}--{predicate}--{output_category}")

    # Figure out if this curie has any edges
    answer_edge_ids = []
    if input_curie in main_index:
        if predicate in main_index[input_curie]:
            if output_category in main_index[input_curie][predicate]:
                answer_edge_ids += list(main_index[input_curie][predicate][output_category].values())

    answer_kg = {"nodes": {}, "edges": {}}
    results = []
    unique_answer_edge_ids = set(answer_edge_ids)
    for answer_edge_id in unique_answer_edge_ids:
        edge = edge_lookup_map[answer_edge_id]
        subject_curie = edge["subject"]
        object_curie = edge["object"]
        answer_kg["edges"][answer_edge_id] = edge
        answer_kg["nodes"][subject_curie] = node_lookup_map[subject_curie]
        answer_kg["nodes"][object_curie] = node_lookup_map[object_curie]
        results.append([subject_curie, answer_edge_id, object_curie])  # TODO: make these actual results...

    return answer_kg, results


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--test', dest='test', action='store_true', default=False)
    args = arg_parser.parse_args()

    # Create our indexes
    main_index, node_lookup_map, edge_lookup_map = build_indexes(args.test)

    # Wait for and run queries (have menu option for now? queries could be in JSON files to start)
    answer_kg, results = answer_query("test_query.json", main_index, node_lookup_map, edge_lookup_map)
    print(answer_kg)
    print(results)


if __name__ == "__main__":
    main()
