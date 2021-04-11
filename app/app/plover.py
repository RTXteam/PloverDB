#!/usr/bin/env python3
import json
import time

import requests
from collections import defaultdict
from typing import List, Dict, Union, Set

from treelib import Tree
import yaml


class PloverDB:

    def __init__(self):
        with open("kg_config.json") as config_file:
            self.kg_config = json.load(config_file)
        self.predicate_property = self.kg_config["labels"]["edges"]
        self.categories_property = self.kg_config["labels"]["nodes"]
        self.is_test = self.kg_config["is_test"]
        self.node_lookup_map = dict()
        self.edge_lookup_map = dict()
        self.all_node_ids = set()
        self.main_index = dict()
        self.predicate_descendants_lookup = None
        self.predicate_inverse_lookup = dict()
        self.subclass_lookup = dict()
        self._build_indexes()

    # METHODS FOR ANSWERING QUERIES

    def answer_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, List[Union[str, int]]]]:
        # Make sure this is a query we can answer
        if len(trapi_query["edges"]) > 1:
            raise ValueError(
                f"Can only answer single-hop or single-node queries. Your QG has {len(trapi_query['edges'])} edges.")
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
        qg_predicates_raw = self._convert_to_set(qedge.get("predicate"))
        qg_predicates = self._get_expanded_predicates(qg_predicates_raw)
        print(f"Query to answer is: ({len(input_curies)} curies)--{list(qg_predicates)}--({len(output_curies)} "
              f"curies, {output_categories if output_categories else 'no categories'})")

        # Use our main index to find results to the query
        final_qedge_answers = set()
        final_input_qnode_answers = set()
        final_output_qnode_answers = set()
        main_index = self.main_index
        for input_curie in input_curies:
            answer_edge_ids = []
            if input_curie in main_index:
                categories_present = set(main_index[input_curie])
                # Consider all output categories if none were provided or if output curies were specified
                categories_to_inspect = output_categories.intersection(
                    categories_present) if output_categories and not output_curies else categories_present
                for output_category in categories_to_inspect:
                    if output_category in main_index[input_curie]:
                        # Consider ALL predicates if none were specified in the QG
                        predicates_present = set(main_index[input_curie][output_category])
                        predicates_to_inspect = qg_predicates.intersection(
                            predicates_present) if qg_predicates else predicates_present
                        for predicate in predicates_to_inspect:
                            if output_curies:
                                # We need to look for the matching output node(s)
                                for direction in {1, 0}:  # Always do query undirected for now (1 means forwards)
                                    curies_present = set(
                                        main_index[input_curie][output_category][predicate][direction])
                                    matching_output_curies = output_curies.intersection(curies_present)
                                    for output_curie in matching_output_curies:
                                        answer_edge_ids.append(
                                            main_index[input_curie][output_category][predicate][direction][
                                                output_curie])
                            else:
                                # Grab both forwards and backwards edges (we only do undirected queries currently)
                                answer_edge_ids += list(
                                    main_index[input_curie][output_category][predicate][1].values())
                                answer_edge_ids += list(
                                    main_index[input_curie][output_category][predicate][0].values())

            # Add everything we found for this input curie to our answers so far
            for answer_edge_id in answer_edge_ids:
                edge = self.edge_lookup_map[answer_edge_id]
                subject_curie = edge["subject"]
                object_curie = edge["object"]
                output_curie = object_curie if object_curie != input_curie else subject_curie
                # Add this edge and its nodes to our answer KG
                final_qedge_answers.add(answer_edge_id)
                final_input_qnode_answers.add(input_curie)
                final_output_qnode_answers.add(output_curie)

        # Form final response and convert our sets to lists so that they're JSON serializable
        answer_kg = {"nodes": {input_qnode_key: list(final_input_qnode_answers),
                               output_qnode_key: list(final_output_qnode_answers)},
                     "edges": {qedge_key: list(final_qedge_answers)}}
        return answer_kg

    def _answer_edgeless_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, List[Union[str, int]]]]:
        # When no qedges are involved, we only fulfill qnodes that have a curie
        qnode_keys_with_curies = {qnode_key for qnode_key, qnode in trapi_query["nodes"].items() if qnode.get("id")}
        answer_kg = {"nodes": {qnode_key: [] for qnode_key in qnode_keys_with_curies},
                     "edges": dict()}
        for qnode_key in qnode_keys_with_curies:
            input_curies = self._convert_to_set(trapi_query["nodes"][qnode_key]["id"])
            for input_curie in input_curies:
                if input_curie in self.all_node_ids:
                    answer_kg["nodes"][qnode_key].append(input_curie)
        # Make sure we return only distinct nodes
        for qnode_key in qnode_keys_with_curies:
            answer_kg["nodes"][qnode_key] = list(set(answer_kg["nodes"][qnode_key]))
        return answer_kg

    def _get_expanded_predicates(self, qedge_predicates: Set[str]) -> Set[str]:
        # First grab any inverses for these predicates
        inverse_predicates = {self.predicate_inverse_lookup[predicate] for predicate in qedge_predicates
                              if predicate in self.predicate_inverse_lookup}
        expanded_predicates = qedge_predicates.union(inverse_predicates)
        if expanded_predicates == {"biolink:related_to"}:
            # More efficient to just clear the predicate in this case, since any are allowed
            return set()
        else:
            # Then look for any descendants of our predicates
            for predicate in expanded_predicates:
                sub_tree = self.predicate_tree.subtree(predicate)
                descendant_predicates = {node.identifier for node in sub_tree.all_nodes()}
                expanded_predicates = expanded_predicates.union(descendant_predicates)
            return expanded_predicates

    def _add_descendant_curies(self, node_ids: Set[str]) -> Set[str]:
        all_node_ids = list(node_ids)
        for node_id in node_ids:
            descendants = self.subclass_lookup.get(node_id, [])
            all_node_ids += descendants
        return set(all_node_ids)

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

    # METHODS FOR BUILDING INDEXES

    def _build_indexes(self):
        # Build simple node and edge lookup maps for storing the node/edge objects
        with open(self.kg_config["file_name"], "r") as kg2c_file:
            kg2c_dict = json.load(kg2c_file)
        self.node_lookup_map = {node["id"]: node for node in kg2c_dict["nodes"]}
        self.edge_lookup_map = {edge["id"]: edge for edge in kg2c_dict["edges"]}

        if self.is_test:
            # Narrow down our test JSON file to make sure all node IDs used by edges appear in our node_lookup_map
            node_ids_used_by_edges = {edge["subject"] for edge in self.edge_lookup_map.values()}.union(edge["object"] for edge in self.edge_lookup_map.values())
            node_lookup_map_trimmed = {node_id: self.node_lookup_map[node_id] for node_id in node_ids_used_by_edges
                                       if node_id in self.node_lookup_map}
            self.node_lookup_map = node_lookup_map_trimmed
            edge_lookup_map_trimmed = {edge_id: edge for edge_id, edge in self.edge_lookup_map.items() if
                                       edge["subject"] in self.node_lookup_map and edge["object"] in self.node_lookup_map}
            self.edge_lookup_map = edge_lookup_map_trimmed

        # Build our main index (modified/nested adjacency list kind of structure)
        print(f"  Building main index..")
        start = time.time()
        for edge_id, edge in self.edge_lookup_map.items():
            subject_id = edge["subject"]
            object_id = edge["object"]
            predicate = edge[self.predicate_property]
            subject_categories = self.node_lookup_map[subject_id][self.categories_property]
            object_categories = self.node_lookup_map[object_id][self.categories_property]
            # Record this edge in both the forwards and backwards direction (we only support undirected queries)
            self._add_to_main_index(subject_id, object_id, object_categories, predicate, edge_id, 1)
            self._add_to_main_index(object_id, subject_id, subject_categories, predicate, edge_id, 0)
        print(f"  Building main index took {round((time.time() - start) / 60, 2)} minutes.")

        # Remove our node lookup map and instead simply store a set of all node IDs in the KG
        self.all_node_ids = set(self.node_lookup_map)
        del self.node_lookup_map
        # Remove properties from edges that we don't need stored there anymore
        for edge in self.edge_lookup_map.values():
            properties_to_remove = set(edge).difference({"subject", "object", self.predicate_property})
            for property_name in properties_to_remove:
                del edge[property_name]

        # Build indexes needed for KP 'reasoning'
        self._build_predicate_lookups()

    def _add_to_main_index(self, node_a_id: str, node_b_id: str, node_b_categories: Set[str], predicate: str,
                           edge_id: str, direction: int):
        # Note: A direction of 1 means forwards, 0 means backwards
        main_index = self.main_index
        if node_a_id not in main_index:
            main_index[node_a_id] = dict()
        for category in node_b_categories:
            if category not in main_index[node_a_id]:
                main_index[node_a_id][category] = dict()
            if predicate not in main_index[node_a_id][category]:
                main_index[node_a_id][category][predicate] = [dict(), dict()]
            main_index[node_a_id][category][predicate][direction][node_b_id] = edge_id

    def _build_predicate_lookups(self):
        print(f"  Building predicate indexes (predicate tree and inverses)..")
        start = time.time()

        def _create_children_recursive(predicate: str, parent_to_child_map: Dict[str, Set[str]], tree: Tree):
            for child_predicate in parent_to_child_map.get(predicate, []):
                tree.create_node(child_predicate, child_predicate, parent=predicate)
                _create_children_recursive(child_predicate, parent_to_child_map, tree)

        def _convert_to_trapi_predicate_format(english_predicate: str) -> str:
            # Converts a string like "treated by" to "biolink:treated_by"
            return f"biolink:{english_predicate.replace(' ', '_')}"

        # Load all predicates from the Biolink model into a tree
        response = requests.get("https://raw.githubusercontent.com/biolink/biolink-model/master/biolink-model.yaml", timeout=10)
        if response.status_code == 200:
            # Build little helper maps of slot names to their direct children/inverses
            biolink_model = yaml.safe_load(response.text)
            parent_to_child_dict = defaultdict(set)
            inverses_dict = dict()
            for slot_name_english, info in biolink_model["slots"].items():
                slot_name = _convert_to_trapi_predicate_format(slot_name_english)
                parent_name_english = info.get("is_a")
                if parent_name_english:
                    parent_name = _convert_to_trapi_predicate_format(parent_name_english)
                    parent_to_child_dict[parent_name].add(slot_name)
                inverse_name = info.get("inverse")
                if inverse_name:
                    inverse_name_formatted = _convert_to_trapi_predicate_format(inverse_name)
                    inverses_dict[slot_name] = inverse_name_formatted
            # Recursively build the predicates tree starting with the root
            root = "biolink:related_to"
            biolink_tree = Tree()
            biolink_tree.create_node(root, root)
            _create_children_recursive(root, parent_to_child_dict, biolink_tree)
            biolink_tree.show()
            self.predicate_tree = biolink_tree
            self.predicate_inverse_lookup = inverses_dict
        else:
            print(f"WARNING: Unable to load Biolink yaml file. Will not be able to consider Biolink predicate "
                  f"inverses or descendants when answering queries.")

        print(f"  Building predicate indexes took {round((time.time() - start) / 60, 2)} minutes.")

    def _build_subclass_lookup(self):
        # TODO: Address problem of cycles of subclass_of relationships before we can utilize this
        print(f"  Building subclass_of index (node descendants)..")
        start = time.time()

        def _get_descendants(node_id: str, parent_to_child_map: Dict[str, Set[str]],
                             parent_to_descendants_map: Dict[str, Set[str]]):
            if node_id not in parent_to_descendants_map:
                for child_id in parent_to_child_map.get(node_id, []):
                    child_descendants = _get_descendants(child_id, parent_to_child_map, parent_to_descendants_map)
                    parent_to_descendants_map[node_id] = parent_to_descendants_map[node_id].union({child_id}, child_descendants)
            return parent_to_descendants_map.get(node_id, set())

        # Build a map of nodes to their direct 'subclass_of' children
        parent_to_child_dict = defaultdict(set)
        for edge_id, edge in self.edge_lookup_map.items():
            if edge[self.predicate_property] == "biolink:subclass_of":
                parent_node_id = edge["object"]
                child_node_id = edge["subject"]
                parent_to_child_dict[parent_node_id].add(child_node_id)
            elif edge[self.predicate_property] == "biolink:superclass_of":
                parent_node_id = edge["subject"]
                child_node_id = edge["object"]
                parent_to_child_dict[parent_node_id].add(child_node_id)

        # Then recursively derive all 'subclass_of' descendants for each node
        root = "root"  # Need something to act as a parent to all other parents, as a starting point
        parent_to_child_dict[root] = set(parent_to_child_dict)
        parent_to_descendants_dict = defaultdict(set)
        _ = _get_descendants(root, parent_to_child_dict, parent_to_descendants_dict)
        del parent_to_descendants_dict[root]  # No longer need this entry in our flat map

        self.subclass_lookup = parent_to_descendants_dict

        print(f"  Building subclass_of index took {round((time.time() - start) / 60, 2)} minutes.")

    # GENERAL HELPER METHODS

    @staticmethod
    def _convert_to_set(input_item: Union[Set[str], str, None]) -> Set[str]:
        if isinstance(input_item, str):
            return {input_item}
        elif isinstance(input_item, list):
            return set(input_item)
        else:
            return set()


def main():
    plover = PloverDB()


if __name__ == "__main__":
    main()
