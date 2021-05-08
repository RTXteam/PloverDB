#!/usr/bin/env python3
import json
import logging
import os
import pathlib
import pickle
import time
import requests
from collections import defaultdict
from typing import List, Dict, Union, Set

from treelib import Tree
import yaml

SCRIPT_DIR = f"{os.path.dirname(os.path.abspath(__file__))}"


class PloverDB:

    def __init__(self):
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s %(levelname)s: %(message)s',
                            handlers=[logging.StreamHandler()])
        self.config_file_path = f"{SCRIPT_DIR}/../kg_config.json"
        with open(self.config_file_path) as config_file:
            self.kg_config = json.load(config_file)
        self.pickle_index_path = f"{SCRIPT_DIR}/../plover_indexes.pickle"
        self.kg_json_path = f"{SCRIPT_DIR}/../{self.kg_config['kg_file_name']}"
        self.predicate_property = self.kg_config["labels"]["edges"]
        self.categories_property = self.kg_config["labels"]["nodes"]
        self.biolink_version = self.kg_config["biolink_version"]
        self.root_category_name = "biolink:NamedThing"
        self.root_predicate_name = "biolink:related_to"
        self.core_node_properties = {"name", "category"}
        self.category_map = dict()
        self.predicate_map = dict()
        self.is_test = self.kg_config["is_test"]
        self.node_lookup_map = dict()
        self.edge_lookup_map = dict()
        self.main_index = dict()
        self.expanded_predicates_map = dict()
        self.subclass_lookup = dict()

    # METHODS FOR ANSWERING QUERIES

    def answer_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, Union[set, dict]]]:
        # Make sure this is a query we can answer
        if len(trapi_query["edges"]) > 1:
            raise ValueError(f"Can only answer single-hop or single-node queries. Your QG has "
                             f"{len(trapi_query['edges'])} edges.")
        # Handle edgeless queries
        if not trapi_query["edges"]:
            return self._answer_edgeless_query(trapi_query)
        # Make sure at least one qnode has a curie
        qedge_key = next(qedge_key for qedge_key in trapi_query["edges"])
        qedge = trapi_query["edges"][qedge_key]
        subject_qnode = trapi_query["nodes"][qedge["subject"]]
        object_qnode = trapi_query["nodes"][qedge["object"]]
        if not {"id", "ids"}.intersection(set(subject_qnode)) and not {"id", "ids"}.intersection(set(object_qnode)):
            raise ValueError(f"Can only answer queries where at least one QNode has a curie ('ids') specified.")

        # Load the query and grab the relevant pieces of it
        input_qnode_key = self._determine_input_qnode_key(trapi_query["nodes"])
        output_qnode_key = list(set(trapi_query["nodes"]).difference({input_qnode_key}))[0]
        # Figure out which directions we need to inspect based on the QG
        enforce_directionality = trapi_query.get("enforce_directionality")
        if enforce_directionality:
            # 1 means we'll look for edges recorded in the 'forwards' direction, 0 means 'backwards'
            directions = {1} if input_qnode_key == qedge["subject"] else {0}
        else:
            directions = {0, 1}
        qnode_properties = set(trapi_query["nodes"][input_qnode_key])
        qedge_properties = set(trapi_query["edges"][qedge_key])
        qg_ids_property = "ids" if "ids" in qnode_properties else "id"
        qg_categories_property = "categories" if "categories" in qnode_properties else "category"
        qg_predicates_property = "predicates" if "predicates" in qedge_properties else "predicate"
        input_curies = self._convert_to_set(trapi_query["nodes"][input_qnode_key][qg_ids_property])
        output_category_names = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get(qg_categories_property))
        output_curies = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get(qg_ids_property))
        qg_predicate_names_raw = self._convert_to_set(qedge.get(qg_predicates_property))
        # Use 'expanded' predicates so that we incorporate the biolink predicate hierarchy/inverses into our answer
        qg_predicate_names = {predicate for qg_predicate in qg_predicate_names_raw
                              for predicate in self.expanded_predicates_map.get(qg_predicate, {qg_predicate})}
        print(f"Query to answer is: ({len(input_curies)} curies)--{list(qg_predicate_names)}--({len(output_curies)} "
              f"curies, {output_category_names if output_category_names else 'no categories'})")
        # Convert the string/english versions of categories/predicates into integer IDs (helps save space)
        output_categories = {self.category_map.get(category, 9999) for category in output_category_names}
        qg_predicates = {self.predicate_map.get(predicate, 9999) for predicate in qg_predicate_names}

        # Use our main index to find results to the query
        final_qedge_answers = set()
        final_input_qnode_answers = set()
        final_output_qnode_answers = set()
        main_index = self.main_index
        for input_curie in input_curies:
            answer_edge_ids = []
            if input_curie in main_index:
                # Consider ALL output categories if none were provided or if output curies were specified
                categories_present = set(main_index[input_curie])
                categories_to_inspect = output_categories.intersection(categories_present) if output_categories and not output_curies else categories_present
                for output_category in categories_to_inspect:
                    if output_category in main_index[input_curie]:
                        # Consider ALL predicates if none were specified in the QG
                        predicates_present = set(main_index[input_curie][output_category])
                        predicates_to_inspect = qg_predicates.intersection(predicates_present) if qg_predicates else predicates_present
                        for predicate in predicates_to_inspect:
                            if output_curies:
                                # We need to look for the matching output node(s)
                                for direction in directions:
                                    curies_present = set(main_index[input_curie][output_category][predicate][direction])
                                    matching_output_curies = output_curies.intersection(curies_present)
                                    for output_curie in matching_output_curies:
                                        answer_edge_ids.append(main_index[input_curie][output_category][predicate][direction][output_curie])
                            else:
                                # Grab both forwards and backwards edges (we only do undirected queries currently)
                                for direction in directions:
                                    answer_edge_ids += list(main_index[input_curie][output_category][predicate][direction].values())

            # Add everything we found for this input curie to our answers so far
            for answer_edge_id in answer_edge_ids:
                edge = self.edge_lookup_map[answer_edge_id]
                subject_curie = edge[0]
                object_curie = edge[1]
                output_curie = object_curie if object_curie != input_curie else subject_curie
                # Add this edge and its nodes to our answer KG
                final_qedge_answers.add(answer_edge_id)
                final_input_qnode_answers.add(input_curie)
                final_output_qnode_answers.add(output_curie)

        # Form final response according to parameter passed in query
        if trapi_query.get("include_metadata"):
            nodes = {input_qnode_key: {node_id: self.node_lookup_map[node_id] for node_id in final_input_qnode_answers},
                     output_qnode_key: {node_id: self.node_lookup_map[node_id] for node_id in final_output_qnode_answers}}
            edges = {qedge_key: {edge_id: self.edge_lookup_map[edge_id] for edge_id in final_qedge_answers}}
        else:
            nodes = {input_qnode_key: list(final_input_qnode_answers),
                     output_qnode_key: list(final_output_qnode_answers)}
            edges = {qedge_key: list(final_qedge_answers)}
        answer_kg = {"nodes": nodes, "edges": edges}
        return answer_kg

    def _answer_edgeless_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, Union[set, dict]]]:
        # When no qedges are involved, we only fulfill qnodes that have a curie
        qnode_keys_with_curies = {qnode_key for qnode_key, qnode in trapi_query["nodes"].items() if qnode.get("id") or qnode.get("ids")}
        answer_kg = {"nodes": {qnode_key: [] for qnode_key in qnode_keys_with_curies},
                     "edges": dict()}
        for qnode_key in qnode_keys_with_curies:
            qnode = trapi_query["nodes"][qnode_key]
            ids_property = "ids" if "ids" in qnode else "id"
            input_curies = self._convert_to_set(qnode[ids_property])
            for input_curie in input_curies:
                if input_curie in self.node_lookup_map:
                    answer_kg["nodes"][qnode_key].append(input_curie)
        # Make sure we return only distinct nodes
        for qnode_key in qnode_keys_with_curies:
            answer_kg["nodes"][qnode_key] = list(set(answer_kg["nodes"][qnode_key]))
        return answer_kg

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
            ids_property = "ids" if "ids" in qnode else "id"
            if qnode.get(ids_property) and len(qnode[ids_property]) > most_curies:
                most_curies = len(qnode[ids_property])
                qnode_key_with_most_curies = qnode_key
        return qnode_key_with_most_curies

    # METHODS FOR BUILDING INDEXES

    def build_indexes(self):
        logging.info("Starting to build indexes..")
        start = time.time()
        # Load our KG file and build simple node and edge lookup maps for storing the node/edge objects by ID
        with open(self.kg_json_path, "r") as kg2c_file:
            logging.info("  Loading KG JSON file..")
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
        logging.info("  Building main index..")
        for edge_id, edge in self.edge_lookup_map.items():
            subject_id = edge["subject"]
            object_id = edge["object"]
            predicate = self._get_predicate_id(edge[self.predicate_property])
            subject_category_names = self.node_lookup_map[subject_id][self.categories_property]
            subject_categories = {self._get_category_id(category) for category in subject_category_names}
            object_category_names = self.node_lookup_map[object_id][self.categories_property]
            object_categories = {self._get_category_id(category) for category in object_category_names}
            # Record this edge in both the forwards and backwards direction (we only support undirected queries)
            self._add_to_main_index(subject_id, object_id, object_categories, predicate, edge_id, 1)
            self._add_to_main_index(object_id, subject_id, subject_categories, predicate, edge_id, 0)

        logging.info("  Converting node/edge objects to tuple form..")
        # Convert node/edge lookup maps into tuple forms (and get rid of extra properties) to save space
        node_properties = ("name", "category")
        edge_properties = ("subject", "object", "predicate", "provided_by", "publications")
        node_ids = set(self.node_lookup_map)
        for node_id in node_ids:
            node = self.node_lookup_map[node_id]
            node_tuple = tuple([node[property_name] for property_name in node_properties])
            self.node_lookup_map[node_id] = node_tuple
        edge_ids = set(self.edge_lookup_map)
        for edge_id in edge_ids:
            edge = self.edge_lookup_map[edge_id]
            edge_tuple = tuple([edge[property_name] for property_name in edge_properties])
            self.edge_lookup_map[edge_id] = edge_tuple

        # Save all indexes to a big json file here
        logging.info("  Saving indexes in pickle..")
        all_indexes = {"node_lookup_map": self.node_lookup_map,
                       "edge_lookup_map": self.edge_lookup_map,
                       "node_headers": node_properties,
                       "edge_headers": edge_properties,
                       "main_index": self.main_index,
                       "predicate_map": self.predicate_map,
                       "category_map": self.category_map}
        with open(self.pickle_index_path, "wb") as index_file:
            pickle.dump(all_indexes, index_file, protocol=pickle.HIGHEST_PROTOCOL)

        logging.info(f"Done building indexes! Took {round((time.time() - start) / 60, 2)} minutes.")

    def load_indexes(self):
        logging.info("Starting to load indexes..")
        start = time.time()
        # Build our indexes if they haven't already been built
        pickle_index_file = pathlib.Path(self.pickle_index_path)
        if not pickle_index_file.exists():
            self.build_indexes()

        # Load our pickled indexes into memory
        logging.info("  Loading pickle of indexes..")
        # Load big json index file here
        with open(self.pickle_index_path, "rb") as index_file:
            all_indexes = pickle.load(index_file)
            # Then convert all int IDs back to actual ints
            self.node_lookup_map = all_indexes["node_lookup_map"]
            self.edge_lookup_map = all_indexes["edge_lookup_map"]
            self.main_index = all_indexes["main_index"]
            self.predicate_map = all_indexes["predicate_map"]
            self.category_map = all_indexes["category_map"]

        # Build a map of expanded predicates (descendants and inverses) for easy lookup
        self._build_expanded_predicates_map()
        logging.info(f"Indexes are fully loaded! Took {round((time.time() - start) / 60, 2)} minutes.")

    def _add_to_main_index(self, node_a_id: str, node_b_id: str, node_b_categories: Set[int], predicate: int,
                           edge_id: int, direction: int):
        # Note: A direction of 1 means forwards, 0 means backwards
        main_index = self.main_index
        if node_a_id not in main_index:
            main_index[node_a_id] = dict()
        for category in node_b_categories:
            if category not in main_index[node_a_id]:
                main_index[node_a_id][category] = dict()
            if predicate not in main_index[node_a_id][category]:
                main_index[node_a_id][category][predicate] = (dict(), dict())
            main_index[node_a_id][category][predicate][direction][node_b_id] = edge_id

    def _get_predicate_id(self, predicate_name: str) -> int:
        if predicate_name not in self.predicate_map:
            num_predicates = len(self.predicate_map)
            self.predicate_map[predicate_name] = num_predicates
        return self.predicate_map[predicate_name]

    def _get_category_id(self, category_name: str) -> int:
        if category_name not in self.category_map:
            num_categories = len(self.category_map)
            self.category_map[category_name] = num_categories
        return self.category_map[category_name]

    def _build_expanded_predicates_map(self):
        logging.info("  Building expanded predicates map (descendants and inverses)..")

        # Load all predicates from the Biolink model into a tree
        biolink_tree = Tree()
        inverses_dict = dict()
        response = requests.get(f"https://raw.githubusercontent.com/biolink/biolink-model/{self.biolink_version}/biolink-model.yaml",
                                timeout=10)
        if response.status_code == 200:
            # Build little helper maps of slot names to their direct children/inverses
            biolink_model = yaml.safe_load(response.text)
            parent_to_child_dict = defaultdict(set)
            for slot_name_english, info in biolink_model["slots"].items():
                slot_name = self._convert_to_trapi_predicate_format(slot_name_english)
                parent_name_english = info.get("is_a")
                if parent_name_english:
                    parent_name = self._convert_to_trapi_predicate_format(parent_name_english)
                    parent_to_child_dict[parent_name].add(slot_name)
                inverse_name = info.get("inverse")
                if inverse_name:
                    inverse_name_formatted = self._convert_to_trapi_predicate_format(inverse_name)
                    inverses_dict[slot_name] = inverse_name_formatted
            # Recursively build the predicates tree starting with the root
            biolink_tree.create_node(self.root_predicate_name, self.root_predicate_name)
            self._create_tree_recursive(self.root_predicate_name, parent_to_child_dict, biolink_tree)
        else:
            logging.warning(f"Unable to load Biolink yaml file. Will not be able to consider Biolink predicate "
                            f"inverses or descendants when answering queries.")

        expanded_predicates_map = defaultdict(set)
        for predicate_node in biolink_tree.all_nodes():
            predicate = predicate_node.identifier
            inverse = inverses_dict.get(predicate)
            descendants = self._get_descendants_from_tree(predicate, biolink_tree)
            inverse_descendants = self._get_descendants_from_tree(inverse, biolink_tree) if inverse else set()
            expanded_predicates = descendants.union(inverse_descendants)
            # Continue (recursively) searching for inverses/descendants until we have them all
            found_more = True
            while found_more:
                start_size = len(expanded_predicates)
                updated_inverses = {inverses_dict.get(predicate_a) for predicate_a in expanded_predicates
                                    if inverses_dict.get(predicate_a)}
                expanded_predicates = expanded_predicates.union(updated_inverses)
                updated_descendants = {descendant_predicate for predicate_b in expanded_predicates
                                       for descendant_predicate in self._get_descendants_from_tree(predicate_b, biolink_tree)}
                expanded_predicates = expanded_predicates.union(updated_descendants)
                if len(expanded_predicates) == start_size:
                    found_more = False
            expanded_predicates_map[predicate] = expanded_predicates

        self.expanded_predicates_map = expanded_predicates_map

    def _build_subclass_lookup(self):
        # TODO: Address problem of cycles of subclass_of relationships before we can utilize this
        logging.info(f"  Building subclass_of index (node descendants)..")
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

        logging.info(f"  Building subclass_of index took {round((time.time() - start) / 60, 2)} minutes.")

    # GENERAL HELPER METHODS

    def _create_tree_recursive(self, root_id: str, parent_to_child_map: Dict[str, Set[str]], tree: Tree):
        for child_id in parent_to_child_map.get(root_id, []):
            tree.create_node(child_id, child_id, parent=root_id)
            self._create_tree_recursive(child_id, parent_to_child_map, tree)

    @staticmethod
    def _convert_to_set(input_item: Union[Set[str], str, None]) -> Set[str]:
        if isinstance(input_item, str):
            return {input_item}
        elif isinstance(input_item, list):
            return set(input_item)
        else:
            return set()

    @staticmethod
    def _convert_to_trapi_predicate_format(english_predicate: str) -> str:
        # Converts a string like "treated by" to "biolink:treated_by"
        return f"biolink:{english_predicate.replace(' ', '_')}"

    @staticmethod
    def _get_descendants_from_tree(node_identifier: str, tree: Tree) -> Set[str]:
        sub_tree = tree.subtree(node_identifier)
        descendants = {node.identifier for node in sub_tree.all_nodes()}
        return descendants


def main():
    plover = PloverDB()
    plover.build_indexes()
    plover.load_indexes()


if __name__ == "__main__":
    main()
