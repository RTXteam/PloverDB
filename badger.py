#!/usr/bin/env python3
import argparse
import json
from typing import List, Dict, Union, Set


class BadgerDB:

    def __init__(self, is_test: bool = False):
        self.is_test = is_test
        self.kg2c_file_name = "kg2c.json" if not is_test else "kg2c_test.json"
        self.node_lookup_map = dict()
        self.edge_lookup_map = dict()
        self.main_index = dict()
        self._build_indexes()

    def _build_indexes(self):
        if self.is_test:
            # In test mode, building indexes is a little less efficient, so that's separated out to keep things clean
            self._build_test_indexes()
        else:
            # Build simple node lookup map for storing node objects
            with open(self.kg2c_file_name, "r") as nodes_file:
                kg2c_dict = json.load(nodes_file)
            for node in kg2c_dict["nodes"]:
                self.node_lookup_map[node["id"]] = node
                del node["id"]  # TRAPI doesn't want IDs stored as properties on nodes

            # Build our edge lookup map and main index (modified adjacency list kind of structure)
            for edge in kg2c_dict["edges"]:
                edge_id = edge["id"]
                self.edge_lookup_map[edge_id] = edge
                del edge["id"]  # TRAPI doesn't want IDs stored as properties on edges
                subject_id = edge["subject"]
                object_id = edge["object"]
                predicate = edge["simplified_edge_label"]
                subject_categories = self.node_lookup_map[subject_id]["types"]
                object_categories = self.node_lookup_map[object_id]["types"]
                # Record this edge in both the forwards and backwards direction (we only support undirected queries)
                self._add_to_main_index(subject_id, object_id, object_categories, predicate, edge_id, "-->")
                self._add_to_main_index(object_id, subject_id, subject_categories, predicate, edge_id, "<--")

    def _build_test_indexes(self):
        # Build simple node and edge lookup maps for storing the node/edge objects
        with open(self.kg2c_file_name, "r") as nodes_file:
            kg2c_dict = json.load(nodes_file)
        self.node_lookup_map = {node["id"]: node for node in kg2c_dict["nodes"]}
        self.edge_lookup_map = {edge["id"]: edge for edge in kg2c_dict["edges"]}
        # Remove node/edge ID properties from actual node/edge objects (TRAPI doesn't want those)
        for node in self.node_lookup_map.values():
            del node["id"]
        for edge in self.edge_lookup_map.values():
            del edge["id"]

        # Narrow down our test JSON file to make sure all node IDs used by edges appear in our node_lookup_map
        node_ids_used_by_edges = {edge["subject"] for edge in self.edge_lookup_map.values()}.union(edge["object"] for edge in self.edge_lookup_map.values())
        node_lookup_map_trimmed = {node_id: self.node_lookup_map[node_id] for node_id in node_ids_used_by_edges
                                   if node_id in self.node_lookup_map}
        self.node_lookup_map = node_lookup_map_trimmed
        edge_lookup_map_trimmed = {edge_id: edge for edge_id, edge in self.edge_lookup_map.items() if
                                   edge["subject"] in self.node_lookup_map and edge["object"] in self.node_lookup_map}
        self.edge_lookup_map = edge_lookup_map_trimmed

        # Build our main index (modified adjacency list kind of structure)
        for edge_id, edge in self.edge_lookup_map.items():
            subject_id = edge["subject"]
            object_id = edge["object"]
            predicate = edge["simplified_edge_label"]
            subject_categories = self.node_lookup_map[subject_id]["types"]
            object_categories = self.node_lookup_map[object_id]["types"]
            # Record this edge in both the forwards and backwards direction (we only support undirected queries)
            self._add_to_main_index(subject_id, object_id, object_categories, predicate, edge_id, "-->")
            self._add_to_main_index(object_id, subject_id, subject_categories, predicate, edge_id, "<--")

    def _add_to_main_index(self, node_a_id: str, node_b_id: str, node_b_categories: List[str], predicate: str,
                           edge_id: str, direction: str):
        main_index = self.main_index
        if node_a_id not in main_index:
            main_index[node_a_id] = dict()
        for category in node_b_categories:
            if category not in main_index[node_a_id]:
                main_index[node_a_id][category] = dict()
            if predicate not in main_index[node_a_id][category]:
                main_index[node_a_id][category][predicate] = {"-->": dict(), "<--": dict()}
            main_index[node_a_id][category][predicate][direction][node_b_id] = edge_id

    @staticmethod
    def _convert_to_set(input_item: Union[Set[str], str, None]) -> Set[str]:
        if isinstance(input_item, str):
            return {input_item}
        elif isinstance(input_item, list):
            return set(input_item)
        else:
            return set()

    @staticmethod
    def _determine_input_qnode_key(qnodes: Dict[str, Dict[str, Union[str, List[str], None]]]) -> str:
        # The input qnode should be the one with the larger number of curies (way more efficient for our purposes)
        qnode_key_with_most_curies = ""
        most_curies = 0
        for qnode_key, qnode in qnodes.items():
            if qnode.get("id") and len(qnode["id"]) > most_curies:
                most_curies = len(qnode["id"])
                qnode_key_with_most_curies = qnode_key
        return qnode_key_with_most_curies

    def _answer_edgeless_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]]:
        # When no qedges are involved, we only fulfill qnodes that have a curie
        qnode_keys_with_curies = {qnode_key for qnode_key, qnode in trapi_query["nodes"].items() if qnode.get("id")}
        answer_kg = {"nodes": {qnode_key: dict() for qnode_key in qnode_keys_with_curies},
                     "edges": {}}
        for qnode_key in qnode_keys_with_curies:
            input_curies = self._convert_to_set(trapi_query["nodes"][qnode_key]["id"])
            for input_curie in input_curies:
                if input_curie in self.node_lookup_map:
                    answer_kg["nodes"][qnode_key][input_curie] = self.node_lookup_map[input_curie]
        return answer_kg

    def answer_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]]:
        # Make sure this is a query we can answer
        if len(trapi_query["edges"]) > 1:
            raise ValueError(f"Can only answer single-hop or single-node queries. Your QG has {len(trapi_query['edges'])} edges.")
        # Handle edgeless queries
        if not trapi_query["edges"]:
            return self._answer_edgeless_query(trapi_query)

        # Load the query and grab the relevant pieces of it
        input_qnode_key = self._determine_input_qnode_key(trapi_query["nodes"])
        output_qnode_key = list(set(trapi_query["nodes"]).difference({input_qnode_key}))[0]
        qedge_key = next(qedge_key for qedge_key in trapi_query["edges"])
        qedge = trapi_query["edges"][qedge_key]
        input_curies = self._convert_to_set(trapi_query["nodes"][input_qnode_key]["id"])
        output_categories = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get("category"))
        output_curies = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get("id"))
        predicates = self._convert_to_set(qedge.get("predicate"))
        print(f"Query to answer is: {input_curies}--{predicates}--{output_curies if output_curies else ''}{output_categories}")

        # Use our main index to find results to the query
        answer_kg = {"nodes": {input_qnode_key: dict(), output_qnode_key: dict()},
                     "edges": {qedge_key: dict()}}
        main_index = self.main_index
        for input_curie in input_curies:
            answer_edge_ids = []
            if input_curie in main_index:
                categories_present = set(main_index[input_curie])
                # Consider all output categories if none were provided or if output curies were specified
                categories_to_inspect = output_categories.intersection(categories_present) if output_categories and not output_curies else categories_present
                for output_category in categories_to_inspect:
                    if output_category in main_index[input_curie]:
                        # Consider ALL predicates if none were specified in the QG
                        predicates_present = set(main_index[input_curie][output_category])
                        predicates_to_inspect = predicates.intersection(predicates_present) if predicates else predicates_present
                        for predicate in predicates_to_inspect:
                            if output_curies:
                                # We need to look for the matching output node(s)
                                for direction in {"-->", "<--"}:  # Always do query undirected for now
                                    curies_present = set(main_index[input_curie][output_category][predicate][direction])
                                    matching_output_curies = output_curies.intersection(curies_present)
                                    for output_curie in matching_output_curies:
                                        answer_edge_ids.append(main_index[input_curie][output_category][predicate][direction][output_curie])
                            else:
                                # Grab both forwards and backwards edges (we only do undirected queries currently)
                                answer_edge_ids += list(main_index[input_curie][output_category][predicate]["-->"].values())
                                answer_edge_ids += list(main_index[input_curie][output_category][predicate]["<--"].values())

            for answer_edge_id in answer_edge_ids:
                edge = self.edge_lookup_map[answer_edge_id]
                subject_curie = edge["subject"]
                object_curie = edge["object"]
                output_curie = object_curie if object_curie != input_curie else subject_curie
                # Add this edge and its nodes to our answer KG
                if answer_edge_id not in answer_kg["edges"][qedge_key]:
                    answer_kg["edges"][qedge_key][answer_edge_id] = edge
                    answer_kg["nodes"][input_qnode_key][input_curie] = self.node_lookup_map[input_curie]
                    answer_kg["nodes"][output_qnode_key][output_curie] = self.node_lookup_map[output_curie]

        return answer_kg


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--test', dest='test', action='store_true', default=False)
    args = arg_parser.parse_args()

    # Create our indexes
    badger_db = BadgerDB(is_test=True)


if __name__ == "__main__":
    main()
