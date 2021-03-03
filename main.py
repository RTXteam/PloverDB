#!/usr/bin/env python3
import argparse
import json
from pprint import PrettyPrinter
from typing import List, Dict, Tuple, Union


def add_to_index(node_a_id: str, node_b_id: str, node_b_categories: List[str], predicate: str, edge_id: str,
                 main_index: Dict[str, Dict[str, Dict[str, Dict[str, str]]]]):
    if node_a_id not in main_index:
        main_index[node_a_id] = dict()
    for category in node_b_categories:
        if category not in main_index[node_a_id]:
            main_index[node_a_id][category] = dict()
        if predicate not in main_index[node_a_id][category]:
            main_index[node_a_id][category][predicate] = dict()
        main_index[node_a_id][category][predicate][node_b_id] = edge_id


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


def convert_to_list(input_item: Union[List[str], str, None]):
    if isinstance(input_item, str):
        return [input_item]
    elif isinstance(input_item, list):
        return input_item
    else:
        return []


def answer_query(json_file_name, main_index, node_lookup_map, edge_lookup_map) -> Tuple[Dict[str, Dict[str, Dict[str, any]]], List[Dict[str, any]]]:
    # Load the query and grab the relevant pieces of it
    with open(json_file_name, "r") as query_file:
        trapi_query = json.load(query_file)
    qnodes_with_curies = [qnode_key for qnode_key in trapi_query["nodes"] if trapi_query["nodes"][qnode_key].get("id")]
    input_qnode_key = qnodes_with_curies[0]
    output_qnode_key = list(set(trapi_query["nodes"]).difference({input_qnode_key}))[0]
    qedge_key = next(qedge_key for qedge_key in trapi_query["edges"])
    qedge = trapi_query["edges"][qedge_key]
    input_curies = convert_to_list(trapi_query["nodes"][input_qnode_key]["id"])
    output_categories = convert_to_list(trapi_query["nodes"][output_qnode_key].get("category"))
    predicates = convert_to_list(qedge.get("predicate"))
    print(f"Query to answer is: {input_curies}--{predicates}--{output_categories}")
    answer_kg = {"nodes": {}, "edges": {}}
    results_dict = {}

    for input_curie in input_curies:
        # Use our main index to find results to the query
        answer_edge_ids = []
        if input_curie in main_index:
            categories_present = set(main_index[input_curie])
            categories_to_inspect = set(output_categories).intersection(categories_present) if output_categories else categories_present
            for output_category in categories_to_inspect:
                if output_category in main_index[input_curie]:
                    # Consider ALL predicates if none were specified in the QG
                    predicates_present = set(main_index[input_curie][output_category])
                    predicates_to_inspect = set(predicates).intersection(predicates_present) if predicates else predicates_present
                    for predicate in predicates_to_inspect:
                        answer_edge_ids += list(main_index[input_curie][output_category][predicate].values())

        unique_answer_edge_ids = set(answer_edge_ids)
        for answer_edge_id in unique_answer_edge_ids:
            edge = edge_lookup_map[answer_edge_id]
            subject_curie = edge["subject"]
            object_curie = edge["object"]
            # Add this edge and its nodes to our answer KG
            answer_kg["edges"][answer_edge_id] = edge
            answer_kg["nodes"][subject_curie] = node_lookup_map[subject_curie]
            answer_kg["nodes"][object_curie] = node_lookup_map[object_curie]

            # Capture this edge and its nodes in a result object
            result_key = "--".join(sorted([subject_curie, object_curie]))
            output_curie = object_curie if object_curie != input_curie else subject_curie
            if result_key not in results_dict:
                results_dict[result_key] = {"node_bindings": {input_qnode_key: [{"id": input_curie}],
                                                              output_qnode_key: [{"id": output_curie}]},
                                            "edge_bindings": {qedge_key: [{"id": answer_edge_id}]}}
            else:
                # If a result has already been created between these two nodes, add this edge ID to it
                edge_bindings = results_dict[result_key]["edge_bindings"][qedge_key]
                if not any(edge_binding for edge_binding in edge_bindings if edge_binding["id"] == answer_edge_id):
                    edge_bindings.append({"id": answer_edge_id})

    return answer_kg, list(results_dict.values())


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--test', dest='test', action='store_true', default=False)
    args = arg_parser.parse_args()

    # Create our indexes
    main_index, node_lookup_map, edge_lookup_map = build_indexes(args.test)

    pp = PrettyPrinter()
    # Wait for and run queries (have menu option for now? queries could be in JSON files to start)
    test_file_names = ["test_query1.json", "test_query2.json", "test_query3.json", "test_query4.json", "test_query.json"]
    for test_file_name in test_file_names:
        answer_kg, results = answer_query(test_file_name, main_index, node_lookup_map, edge_lookup_map)
        pp.pprint(results)
        print()

    pp.pprint(main_index["CHEMBL.COMPOUND:CHEMBL833"])
    pp.pprint(main_index["CHEBI:51173"])


if __name__ == "__main__":
    main()
