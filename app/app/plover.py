#!/usr/bin/env python3
import itertools
import json
import jsonlines
import logging
import os
import pathlib
import pickle
import statistics
import subprocess
import time
from collections import defaultdict
from typing import List, Dict, Union, Set, Optional, Tuple

import psutil

SCRIPT_DIR = f"{os.path.dirname(os.path.abspath(__file__))}"
KG2C_DUMP_URL_BASE = "https://kg2webhost.rtx.ai"
LOG_FILE_PATH = "/var/log/ploverdb.log"


class PloverDB:

    def __init__(self):
        # Set up logging (when run outside of docker, can't write to /var/log - handle that situation)
        try:
            logging.basicConfig(level=logging.INFO,
                                format='%(asctime)s %(levelname)s: %(message)s',
                                handlers=[logging.StreamHandler(),
                                          logging.FileHandler(LOG_FILE_PATH)])
        except Exception:
            logging.basicConfig(level=logging.INFO,
                                format='%(asctime)s %(levelname)s: %(message)s',
                                handlers=[logging.StreamHandler(),
                                          logging.FileHandler(f"{SCRIPT_DIR}/ploverdb.log")])

        self.config_file_path = f"{SCRIPT_DIR}/../kg_config.json"
        with open(self.config_file_path) as config_file:
            self.kg_config = json.load(config_file)

        self.is_test = self.kg_config["is_test"]
        self.biolink_version = self.kg_config["biolink_version"]
        self.num_edges_per_answer_cutoff = self.kg_config["num_edges_per_answer_cutoff"]
        self.remote_edges_file_name = self.kg_config["remote_edges_file_name"]
        self.remote_nodes_file_name = self.kg_config["remote_nodes_file_name"]
        self.local_edges_file_name = self.kg_config["local_edges_file_name"]
        self.local_nodes_file_name = self.kg_config["local_nodes_file_name"]
        self.nodes_file_name_unzipped, self.edges_file_name_unzipped = self._get_file_names_to_use_unzipped()
        self.nodes_path = f"{SCRIPT_DIR}/../{self.nodes_file_name_unzipped}"
        self.edges_path = f"{SCRIPT_DIR}/../{self.edges_file_name_unzipped}"
        self.pickle_index_path = f"{SCRIPT_DIR}/../plover_indexes.pkl"
        self.edge_predicate_property = self.kg_config["labels"]["edges"]
        self.categories_property = self.kg_config["labels"]["nodes"]
        self.kg2_qualified_predicate_property = "qualified_predicate"
        self.kg2_object_direction_property = "qualified_object_direction"  # Later this might use same as qedge?
        self.kg2_object_aspect_property = "qualified_object_aspect"  # Later this might use same as qedge?
        self.qedge_qualified_predicate_property = "biolink:qualified_predicate"
        self.qedge_object_direction_property = "biolink:object_direction_qualifier"
        self.qedge_object_aspect_property = "biolink:object_aspect_qualifier"
        self.bh_branch = self.kg_config["biolink_helper_branch"]  # The RTX branch to download BiolinkHelper from
        self.bh = None  # BiolinkHelper is downloaded later on
        self.non_biolink_item_id = 9999
        self.category_map = dict()  # Maps category english name --> int ID
        self.category_map_reversed = dict()  # Maps category int ID --> english name
        self.predicate_map = dict()  # Maps predicate english name --> int ID
        self.predicate_map_reversed = dict()  # Maps predicate int ID --> english name
        self.node_lookup_map = dict()
        self.edge_lookup_map = dict()
        self.main_index = dict()
        self.subclass_index = dict()
        self.conglomerate_predicate_descendant_index = defaultdict(set)
        self.supported_qualifiers = {self.qedge_qualified_predicate_property, self.qedge_object_direction_property,
                                     self.qedge_object_aspect_property}

    # ------------------------------------------ INDEX BUILDING METHODS --------------------------------------------- #

    def build_indexes(self):
        logging.info("Starting to build indexes..")
        start = time.time()

        # Use local KG files if given, otherwise download remote files
        if self.local_edges_file_name and self.local_nodes_file_name:
            logging.info(f"Will use local KG files {self.local_edges_file_name} and {self.local_nodes_file_name}")
            if self.local_edges_file_name.endswith(".gz"):
                logging.info(f"Unzipping local edges file")
                subprocess.check_call(["gunzip", "-f", f"{self.edges_path}.gz"])
            if self.local_nodes_file_name.endswith(".gz"):
                logging.info(f"Unzipping local nodes file")
                subprocess.check_call(["gunzip", "-f", f"{self.nodes_path}.gz"])
        else:
            self._download_and_unzip_remote_file(self.remote_edges_file_name, self.edges_path)
            self._download_and_unzip_remote_file(self.remote_nodes_file_name, self.nodes_path)

        # Load the json lines files into a KG
        logging.info(f"Loading json lines files into memory as a biolink KG.. ({self.nodes_path}, {self.edges_path})")
        with jsonlines.open(self.nodes_path) as reader:
            nodes = [node_obj for node_obj in reader]
        logging.info(f"Have loaded nodes into memory.. now will load edges..")
        with jsonlines.open(self.edges_path) as reader:
            edges = [edge_obj for edge_obj in reader]
        logging.info(f"Have loaded edges into memory.")
        kg2c_dict = {"nodes": nodes, "edges": edges}

        # Set up BiolinkHelper (download from RTX repo)
        bh_file_name = "biolink_helper.py"
        logging.info(f"Downloading {bh_file_name} from RTX repo")
        local_path = f"{SCRIPT_DIR}/{bh_file_name}"
        remote_path = f"https://github.com/RTXteam/RTX/blob/{self.bh_branch}/code/ARAX/BiolinkHelper/{bh_file_name}?raw=true"
        subprocess.check_call(["curl", "-L", remote_path, "-o", local_path])
        from biolink_helper import BiolinkHelper
        self.bh = BiolinkHelper(biolink_version=self.biolink_version)

        # Create basic node/edge lookup maps
        logging.info(f"Building basic node/edge lookup maps")
        logging.info(f"Loading node lookup map..")
        self.node_lookup_map = {node["id"]: node for node in kg2c_dict["nodes"]}
        # Undo the 'category' property change that Plater requires (has pre-expanded ancestors; we do that on the fly)
        for node in self.node_lookup_map.values():
            node["category"] = node["preferred_category"]
            del node["preferred_category"]
        memory_usage_gb, memory_usage_percent = self._get_current_memory_usage()
        logging.info(f"Done loading node lookup map. Memory usage is currently "
                     f"{memory_usage_percent}% ({memory_usage_gb}G)..")
        logging.info(f"Loading edge lookup map..")
        self.edge_lookup_map = {edge["id"]: edge for edge in kg2c_dict["edges"]}
        memory_usage_gb, memory_usage_percent = self._get_current_memory_usage()
        logging.info(f"Done loading edge lookup map. Memory usage is currently "
                     f"{memory_usage_percent}% ({memory_usage_gb}G)..")
        logging.info(f"node_lookup_map contains {len(self.node_lookup_map)} nodes, "
                     f"edge_lookup_map contains {len(self.edge_lookup_map)} edges")

        # Convert all edges to their canonical predicate form; correct missing biolink prefixes
        logging.info(f"Converting edges to their canonical form")
        for edge_id, edge in self.edge_lookup_map.items():
            predicate = edge[self.edge_predicate_property]
            qualified_predicate = edge.get(self.kg2_qualified_predicate_property)
            canonical_predicate = self.bh.get_canonical_predicates(predicate)[0]
            canonical_qualified_predicate = self.bh.get_canonical_predicates(qualified_predicate)[0] if qualified_predicate else None
            predicate_is_canonical = canonical_predicate == predicate
            qualified_predicate_is_canonical = canonical_qualified_predicate == qualified_predicate
            if qualified_predicate and \
                    ((predicate_is_canonical and not qualified_predicate_is_canonical) or
                     (not predicate_is_canonical and qualified_predicate_is_canonical)):
                logging.error(f"Edge {edge_id} has one of [predicate, qualified_predicate] that is in canonical form "
                              f"and one that is not; cannot reconcile")
                return
            elif canonical_predicate != predicate:  # Both predicate and qualified_pred must be non-canonical
                # Flip the edge (because the original predicate must be the canonical predicate's inverse)
                edge[self.edge_predicate_property] = canonical_predicate
                edge[self.kg2_qualified_predicate_property] = canonical_qualified_predicate
                original_subject = edge["subject"]
                edge["subject"] = edge["object"]
                edge["object"] = original_subject

        if self.is_test:
            # Narrow down our test JSON file to exclude orphan edges
            logging.info(f"Narrowing down test JSON file to make sure node IDs used by edges appear in nodes dict")
            edge_lookup_map_trimmed = {edge_id: edge for edge_id, edge in self.edge_lookup_map.items() if
                                       edge["subject"] in self.node_lookup_map and edge["object"] in self.node_lookup_map}
            self.edge_lookup_map = edge_lookup_map_trimmed
            logging.info(f"After narrowing down test file, node_lookup_map contains {len(self.node_lookup_map)} nodes, "
                         f"edge_lookup_map contains {len(self.edge_lookup_map)} edges")

        # Build a helper map of nodes --> category labels
        logging.info("Determining nodes' category labels (most specific Biolink categories)..")
        node_to_category_labels_map = dict()
        for node_id, node in self.node_lookup_map.items():
            categories = set(node[self.categories_property])
            proper_ancestors_for_each_category = [set(self.bh.get_ancestors(category, include_mixins=False, include_conflations=False)).difference({category})
                                                  for category in categories]
            all_proper_ancestors = set().union(*proper_ancestors_for_each_category)
            most_specific_categories = categories.difference(all_proper_ancestors)
            node_to_category_labels_map[node_id] = {self._get_category_id(category_name)
                                                    for category_name in most_specific_categories}

        # Build our main index (modified/nested adjacency list kind of structure)
        logging.info("Building main index..")
        edges_count = 0
        qualified_edges_count = 0
        total = len(self.edge_lookup_map)
        max_allowed_percent_memory_usage = 90
        for edge_id, edge in self.edge_lookup_map.items():
            subject_id = edge["subject"]
            object_id = edge["object"]
            predicate = edge[self.edge_predicate_property]
            predicate_id = self._get_predicate_id(predicate)
            subject_category_ids = node_to_category_labels_map[subject_id]
            object_category_ids = node_to_category_labels_map[object_id]
            # Record this edge in the forwards and backwards directions
            self._add_to_main_index(subject_id, object_id, object_category_ids, predicate_id, edge_id, 1)
            self._add_to_main_index(object_id, subject_id, subject_category_ids, predicate_id, edge_id, 0)
            # Record this edge under its qualified predicate/other properties, if such info is provided
            if edge.get(self.kg2_qualified_predicate_property) or edge.get(self.kg2_object_direction_property) or edge.get(self.kg2_object_aspect_property):
                conglomerate_predicate_id = self._get_conglomerate_predicate_id_from_edge(edge)
                self._add_to_main_index(subject_id, object_id, object_category_ids, conglomerate_predicate_id, edge_id, 1)
                self._add_to_main_index(object_id, subject_id, subject_category_ids, conglomerate_predicate_id, edge_id, 0)
                qualified_edges_count += 1
            edges_count += 1
            if edges_count % 1000000 == 0:
                memory_usage_gb, memory_usage_percent = self._get_current_memory_usage()
                logging.info(f"  Have processed {edges_count} edges ({round((edges_count / total) * 100)}%), "
                             f"{qualified_edges_count} of which were qualified edges. Memory usage is currently "
                             f"{memory_usage_percent}% ({memory_usage_gb}G)..")
                if memory_usage_percent > max_allowed_percent_memory_usage:
                    raise MemoryError(f"Main index size is greater than {max_allowed_percent_memory_usage}%;"
                                      f" terminating.")
        logging.info(f"Done building main index; there were {edges_count} edges, {qualified_edges_count} of which "
                     f"were qualified.")

        # Record each conglomerate predicate in the KG under its ancestors
        self._build_conglomerate_predicate_descendant_index()

        # Build the subclass_of index as needed
        if self.kg_config.get("subclass_sources"):
            self._build_subclass_index(set(self.kg_config["subclass_sources"]))
        else:
            logging.info(f"Not building subclass_of index since no subclass sources were specified in kg_config.json")

        # Create reversed category/predicate maps now that we're done building those maps
        self.category_map_reversed = self._reverse_dictionary(self.category_map)
        self.predicate_map_reversed = self._reverse_dictionary(self.predicate_map)

        # Save all indexes in a big pickle
        logging.info(f"Saving indexes to {self.pickle_index_path}..")
        all_indexes = {"node_lookup_map": self.node_lookup_map,
                       "edge_lookup_map": self.edge_lookup_map,
                       "main_index": self.main_index,
                       "subclass_index": self.subclass_index,
                       "predicate_map": self.predicate_map,
                       "predicate_map_reversed": self.predicate_map_reversed,
                       "category_map": self.category_map,
                       "category_map_reversed": self.category_map_reversed,
                       "conglomerate_predicate_descendant_index": self.conglomerate_predicate_descendant_index,
                       "biolink_version": self.biolink_version}
        with open(self.pickle_index_path, "wb") as index_file:
            pickle.dump(all_indexes, index_file, protocol=pickle.HIGHEST_PROTOCOL)

        if not self.is_test:
            logging.info(f"Removing local unzipped nodes/edges files from the image now that index building is done")
            subprocess.call(["rm", "-f", self.nodes_path])
            subprocess.call(["rm", "-f", self.edges_path])

        logging.info(f"Done building indexes! Took {round((time.time() - start) / 60, 2)} minutes.")

    def load_indexes(self):
        logging.info(f"Checking whether pickle of indexes ({self.pickle_index_path}) already exists..")
        pickle_index_file = pathlib.Path(self.pickle_index_path)
        if not pickle_index_file.exists():
            logging.info(f"No index pickle exists - will build indexes")
            self.build_indexes()

        # Load our pickled indexes into memory
        logging.info(f"Loading pickle of indexes from {self.pickle_index_path}..")
        start = time.time()
        with open(self.pickle_index_path, "rb") as index_file:
            all_indexes = pickle.load(index_file)
            self.node_lookup_map = all_indexes["node_lookup_map"]
            self.edge_lookup_map = all_indexes["edge_lookup_map"]
            self.main_index = all_indexes["main_index"]
            self.subclass_index = all_indexes["subclass_index"]
            self.predicate_map = all_indexes["predicate_map"]
            self.predicate_map_reversed = all_indexes["predicate_map_reversed"]
            self.category_map = all_indexes["category_map"]
            self.category_map_reversed = all_indexes["category_map_reversed"]
            self.conglomerate_predicate_descendant_index = all_indexes["conglomerate_predicate_descendant_index"]
            biolink_version = all_indexes["biolink_version"]

        # Set up BiolinkHelper
        from biolink_helper import BiolinkHelper
        self.bh = BiolinkHelper(biolink_version=biolink_version)

        logging.info(f"Indexes are fully loaded! Took {round((time.time() - start) / 60, 2)} minutes.")

    def _add_to_main_index(self, node_a_id: str, node_b_id: str, node_b_category_ids: Set[int], predicate_id: int,
                           edge_id: int, direction: int):
        # Note: A direction of 1 means forwards, 0 means backwards
        main_index = self.main_index
        if node_a_id not in main_index:
            main_index[node_a_id] = dict()
        for category_id in node_b_category_ids:
            if category_id not in main_index[node_a_id]:
                main_index[node_a_id][category_id] = dict()
            if predicate_id not in main_index[node_a_id][category_id]:
                main_index[node_a_id][category_id][predicate_id] = (dict(), dict())
            if node_b_id not in main_index[node_a_id][category_id][predicate_id][direction]:
                main_index[node_a_id][category_id][predicate_id][direction][node_b_id] = set()
            main_index[node_a_id][category_id][predicate_id][direction][node_b_id].add(edge_id)

    def _get_conglomerate_predicate_from_edge(self, edge: dict) -> str:
        qualified_predicate = edge.get(self.kg2_qualified_predicate_property)
        object_direction = edge.get(self.kg2_object_direction_property)
        object_aspect = edge.get(self.kg2_object_aspect_property)
        predicate = edge.get(self.edge_predicate_property)
        return self._get_conglomerate_predicate(qualified_predicate=qualified_predicate,
                                                predicate=predicate,
                                                object_direction=object_direction,
                                                object_aspect=object_aspect)

    def _get_predicate_id(self, predicate_name: str) -> int:
        if predicate_name not in self.predicate_map:
            num_predicates = len(self.predicate_map)
            self.predicate_map[predicate_name] = num_predicates
        return self.predicate_map[predicate_name]

    def _get_conglomerate_predicate_id_from_edge(self, edge: dict) -> int:
        conglomerate_predicate = self._get_conglomerate_predicate_from_edge(edge)
        return self._get_predicate_id(conglomerate_predicate)

    @staticmethod
    def _get_conglomerate_predicate(qualified_predicate: Optional[str], predicate: Optional[str],
                                    object_direction: Optional[str], object_aspect: Optional[str]) -> str:
        # If no qualified predicate is provided, use the regular unqualified predicate
        predicate_to_use = qualified_predicate if qualified_predicate else predicate
        return f"{predicate_to_use}--{object_direction}--{object_aspect}"

    def _get_category_id(self, category_name: str) -> int:
        if category_name not in self.category_map:
            num_categories = len(self.category_map)
            self.category_map[category_name] = num_categories
        return self.category_map[category_name]

    @staticmethod
    def _reverse_dictionary(some_dict: dict) -> dict:
        return {value: key for key, value in some_dict.items()}

    def _build_conglomerate_predicate_descendant_index(self):
        # Record each conglomerate predicate in the KG under its ancestors (inc. None and regular predicate variations)
        logging.info("Building conglomerate qualified predicate descendant index..")
        conglomerate_predicates_already_seen = set()
        for edge_id, edge in self.edge_lookup_map.items():
            conglomerate_predicate = self._get_conglomerate_predicate_from_edge(edge)
            qualified_predicate = edge.get(self.kg2_qualified_predicate_property)
            qualified_obj_direction = edge.get(self.kg2_object_direction_property)
            qualified_obj_aspect = edge.get(self.kg2_object_aspect_property)
            if (qualified_predicate or qualified_obj_direction or qualified_obj_aspect) and conglomerate_predicate not in conglomerate_predicates_already_seen:
                predicate_variations = [qualified_predicate, edge.get(self.edge_predicate_property)]
                for predicate in predicate_variations:
                    predicate_ancestors = set(self.bh.get_ancestors(predicate)).union({None})
                    direction_ancestors = set(self.bh.get_ancestors(qualified_obj_direction)).union({None})
                    aspect_ancestors = set(self.bh.get_ancestors(qualified_obj_aspect)).union({None})
                    ancestor_combinations = set(itertools.product(predicate_ancestors, direction_ancestors, aspect_ancestors))
                    ancestor_conglomerate_predicates = {f"{combination[0]}--{combination[1]}--{combination[2]}"
                                                        for combination in ancestor_combinations}.difference({"None--None--None"})
                    for ancestor in ancestor_conglomerate_predicates:
                        self.conglomerate_predicate_descendant_index[ancestor].add(conglomerate_predicate)
                conglomerate_predicates_already_seen.add(conglomerate_predicate)

    def _build_subclass_index(self, subclass_sources: Set[str]):
        logging.info(f"Building subclass_of index using {subclass_sources} edges..")
        start = time.time()

        def _get_descendants(node_id: str, parent_to_child_map: Dict[str, Set[str]],
                             parent_to_descendants_map: Dict[str, Set[str]], recursion_depth: int,
                             problem_nodes: Set[str]):
            if node_id not in parent_to_descendants_map:
                if recursion_depth > 20:
                    logging.info(f"Hit recursion depth of 20 for node {node_id}; discarding this "
                                 f"lineage (will write to problem file)")
                    problem_nodes.add(node_id)
                else:
                    for child_id in parent_to_child_map.get(node_id, []):
                        child_descendants = _get_descendants(child_id, parent_to_child_map, parent_to_descendants_map,
                                                             recursion_depth + 1, problem_nodes)
                        parent_to_descendants_map[node_id] = parent_to_descendants_map[node_id].union({child_id}, child_descendants)
            return parent_to_descendants_map.get(node_id, set())

        # First narrow down the subclass edges we'll use (to reduce inaccuracies/cycles)
        subclass_predicates = {"biolink:subclass_of", "biolink:superclass_of"}
        subclass_edge_ids = {edge_id for edge_id, edge in self.edge_lookup_map.items()
                             if edge[self.edge_predicate_property] in subclass_predicates and
                             edge.get("primary_knowledge_source") in subclass_sources}
        logging.info(f"    Found {len(subclass_edge_ids)} subclass_of edges to consider (from specified sources)")

        # Build a map of nodes to their direct 'subclass_of' children
        parent_to_child_dict = defaultdict(set)
        for edge_id in subclass_edge_ids:
            edge = self.edge_lookup_map[edge_id]
            parent_node_id = edge["object"] if edge[self.edge_predicate_property] == "biolink:subclass_of" else edge["subject"]
            child_node_id = edge["subject"] if edge[self.edge_predicate_property] == "biolink:subclass_of" else edge["object"]
            parent_to_child_dict[parent_node_id].add(child_node_id)
        logging.info(f"    A total of {len(parent_to_child_dict)} nodes have child subclasses")

        # Then recursively derive all 'subclass_of' descendants for each node
        if parent_to_child_dict:
            root = "root"  # Need something to act as a parent to all other parents, as a starting point
            parent_to_child_dict[root] = set(parent_to_child_dict)
            parent_to_descendants_dict = defaultdict(set)
            problem_nodes = set()
            _ = _get_descendants(root, parent_to_child_dict, parent_to_descendants_dict, 0, problem_nodes)

            # Filter out some unhelpful nodes (too many descendants and/or not useful)
            del parent_to_descendants_dict["root"]
            node_ids = set(parent_to_descendants_dict)
            for node_id in node_ids:
                node = self.node_lookup_map[node_id]
                if len(parent_to_descendants_dict[node_id]) > 5000 or node["category"] == "biolink:OntologyClass" or node_id.startswith("biolink:"):
                    del parent_to_descendants_dict[node_id]
            deleted_node_ids = node_ids.difference(set(parent_to_descendants_dict))

            self.subclass_index = parent_to_descendants_dict

            # Print out/save some useful stats
            parent_to_num_descendants = {node_id: len(descendants) for node_id, descendants in parent_to_descendants_dict.items()}
            descendant_counts = list(parent_to_num_descendants.values())
            prefix_counts = defaultdict(int)
            top_50_biggest_parents = sorted(parent_to_num_descendants.items(), key=lambda x: x[1], reverse=True)[:50]
            for node_id in parent_to_descendants_dict:
                prefix = node_id.split(":")[0]
                prefix_counts[prefix] += 1
            sorted_prefix_counts = dict(sorted(prefix_counts.items(), key=lambda count: count[1], reverse=True))
            with open("subclass_report.json", "w+") as report_file:
                report = {"total_edges_in_kg": len(self.edge_lookup_map),
                          "num_subclass_of_edges_from_approved_sources": len(subclass_edge_ids),
                          "num_nodes_with_descendants": {
                              "total": len(parent_to_descendants_dict),
                              "by_prefix": sorted_prefix_counts
                          },
                          "num_descendants_per_node": {
                              "mean": round(statistics.mean(descendant_counts), 3),
                              "max": max(descendant_counts),
                              "median": statistics.median(descendant_counts),
                              "mode": statistics.mode(descendant_counts)
                          },
                          "problem_nodes": {
                              "count": len(problem_nodes),
                              "curies": list(problem_nodes)
                          },
                          "top_50_biggest_parents": {
                              "counts": {item[0]: item[1] for item in top_50_biggest_parents},
                              "curies": [item[0] for item in top_50_biggest_parents]
                          },
                          "deleted_nodes": {
                              "count": len(deleted_node_ids),
                              "curies": list(deleted_node_ids)
                          },
                          "example_mappings": {
                              "Diabetes mellitus (MONDO:0005015)": list(self.subclass_index.get("MONDO:0005015", [])),
                              "Adams-Oliver syndrome (MONDO:0007034)": list(self.subclass_index.get("MONDO:0007034", []))
                          }
                          }
                json.dump(report, report_file, indent=2)

        logging.info(f"Building subclass_of index took {round((time.time() - start) / 60, 2)} minutes.")

    @staticmethod
    def _download_and_unzip_remote_file(remote_file_name: str, local_destination_path: str):
        temp_location = f"{SCRIPT_DIR}/{remote_file_name}"
        remote_path = f"{KG2C_DUMP_URL_BASE}/{remote_file_name}"
        logging.info(f"Downloading remote file from URL: {remote_path}")
        subprocess.check_call(["curl", "-L", remote_path, "-o", temp_location])
        if remote_file_name.endswith(".gz"):
            logging.info(f"Unzipping downloaded file")
            subprocess.check_call(["gunzip", "-f", temp_location])
            temp_location = temp_location.strip(".gz")
        subprocess.check_call(["mv", temp_location, local_destination_path])

    def _print_main_index_human_friendly(self):
        for input_curie, categories_dict in self.main_index.items():
            print(f"{input_curie}: #####################################################################")
            for category_id, predicates_dict in categories_dict.items():
                print(f"    {self.category_map_reversed[category_id]}: ------------------------------")
                for predicate_id, directions_tuple in predicates_dict.items():
                    print(f"        {self.predicate_map_reversed[predicate_id]}:")
                    for direction_dict in directions_tuple:
                        print(f"        {'Forwards' if directions_tuple.index(direction_dict) == 1 else 'Backwards'}:")
                        for output_curie, edge_ids in direction_dict.items():
                            print(f"            {output_curie}:")
                            print(f"                {edge_ids}")

    @staticmethod
    def _get_current_memory_usage():
        # Thanks https://www.geeksforgeeks.org/how-to-get-current-cpu-and-ram-usage-in-python/
        virtual_mem_usage_info = psutil.virtual_memory()
        memory_percent_used = virtual_mem_usage_info[2]
        memory_used_in_gb = virtual_mem_usage_info[3] / 10**9
        return round(memory_used_in_gb, 1), memory_percent_used

    # ---------------------------------------- QUERY ANSWERING METHODS ------------------------------------------- #

    def answer_query(self, trapi_query: dict) -> Dict[str, Dict[str, Union[set, dict]]]:
        logging.info(f"TRAPI query is: {trapi_query}")
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
        subject_qnode_key = qedge["subject"]
        object_qnode_key = qedge["object"]
        subject_qnode = trapi_query["nodes"][subject_qnode_key]
        object_qnode = trapi_query["nodes"][object_qnode_key]
        if "ids" not in subject_qnode and "ids" not in object_qnode:
            raise ValueError(f"Can only answer queries where at least one QNode has a curie ('ids') specified.")
        # Make sure there aren't any qualifiers we don't support
        for qualifier_constraint in qedge.get("qualifier_constraints", []):
            for qualifier in qualifier_constraint.get("qualifier_set"):
                if qualifier["qualifier_type_id"] not in self.supported_qualifiers:
                    raise ValueError(f"Unsupported qedge qualifier encountered: {qualifier['qualifier_type_id']}. "
                                     f"Supported qualifiers are: {self.supported_qualifiers}")

        # Record which curies specified in the QG any descendant curies correspond to
        descendant_to_query_curie_map = {subject_qnode_key: defaultdict(set), object_qnode_key: defaultdict(set)}
        if subject_qnode.get("ids") and subject_qnode.get("allow_subclasses"):
            subject_qnode_curies_with_descendants = list()
            subject_qnode_curies = set(subject_qnode["ids"])
            for query_curie in subject_qnode_curies:
                descendants = self._get_descendants(query_curie)
                for descendant in descendants:
                    # We only want to record the mapping in the case of a true descendant
                    if descendant not in subject_qnode_curies:
                        descendant_to_query_curie_map[subject_qnode_key][descendant].add(query_curie)
                subject_qnode_curies_with_descendants += descendants
            subject_qnode["ids"] = list(set(subject_qnode_curies_with_descendants))
        if object_qnode.get("ids") and object_qnode.get("allow_subclasses"):
            object_qnode_curies_with_descendants = list()
            object_qnode_curies = set(object_qnode["ids"])
            for query_curie in object_qnode_curies:
                descendants = self._get_descendants(query_curie)
                for descendant in descendants:
                    # We only want to record the mapping in the case of a true descendant
                    if descendant not in object_qnode_curies:
                        descendant_to_query_curie_map[object_qnode_key][descendant].add(query_curie)
                object_qnode_curies_with_descendants += descendants
            object_qnode["ids"] = list(set(object_qnode_curies_with_descendants))

        # Convert to canonical predicates in the QG as needed
        self._force_qedge_to_canonical_predicates(qedge)

        # Load the query and do any necessary transformations to categories/predicates
        input_qnode_key = self._determine_input_qnode_key(trapi_query["nodes"])
        output_qnode_key = list(set(trapi_query["nodes"]).difference({input_qnode_key}))[0]
        input_curies = self._convert_to_set(trapi_query["nodes"][input_qnode_key]["ids"])
        output_curies = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get("ids"))
        output_categories_expanded = self._get_expanded_output_category_ids(output_qnode_key, trapi_query)
        qedge_predicates_expanded = self._get_expanded_qedge_predicates(qedge)
        logging.info(f"Input curies are {input_curies}")
        logging.info(f"Output curies are {output_curies}")
        logging.info(f"QEdge predicates derived are {qedge_predicates_expanded}")

        # Use our main index to find results to the query
        final_qedge_answers = set()
        final_input_qnode_answers = set()
        final_output_qnode_answers = set()
        main_index = self.main_index
        for input_curie in input_curies:
            answer_edge_ids = []
            if input_curie in main_index and len(answer_edge_ids) < self.num_edges_per_answer_cutoff:
                # Consider ALL output categories if none were provided or if output curies were specified
                categories_present = set(main_index[input_curie])
                categories_to_inspect = output_categories_expanded.intersection(categories_present) if output_categories_expanded and not output_curies else categories_present
                for output_category in categories_to_inspect:
                    if output_category in main_index[input_curie]:
                        predicates_present = set(main_index[input_curie][output_category])
                        predicates_to_inspect = set(qedge_predicates_expanded).intersection(predicates_present)
                        # Loop through each QG predicate (and their descendants), looking up answers as we go
                        for predicate in predicates_to_inspect:
                            consider_bidirectional = qedge_predicates_expanded.get(predicate)
                            if consider_bidirectional:
                                directions = {0, 1}
                            else:
                                # 1 means we'll look for edges recorded in the 'forwards' direction, 0 means 'backwards'
                                directions = {1} if input_qnode_key == qedge["subject"] else {0}
                            if output_curies:
                                # We need to look for the matching output node(s)
                                for direction in directions:
                                    curies_present = set(main_index[input_curie][output_category][predicate][direction])
                                    matching_output_curies = output_curies.intersection(curies_present)
                                    for output_curie in matching_output_curies:
                                        answer_edge_ids += list(main_index[input_curie][output_category][predicate][direction][output_curie])
                            else:
                                for direction in directions:
                                    answer_edge_ids += list(set().union(*main_index[input_curie][output_category][predicate][direction].values()))

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

        # Form final response
        # TODO: Actually return TRAPI, not just this... (use descendant_to_query_curie_map to fill out query_id)
        nodes = {
            input_qnode_key: {node_id: self.node_lookup_map[node_id]
                              for node_id in final_input_qnode_answers},
            output_qnode_key: {node_id: self.node_lookup_map[node_id]
                               for node_id in final_output_qnode_answers}
        }
        edges = {qedge_key: {edge_id: self.edge_lookup_map[edge_id] for edge_id in final_qedge_answers}}
        answer_kg = {"nodes": nodes, "edges": edges}

        return answer_kg

    def _answer_edgeless_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, Union[set, dict]]]:
        # When no qedges are involved, we only fulfill qnodes that have a curie
        if not all(qnode.get("ids") for qnode in trapi_query["nodes"].values()):
            raise ValueError("For qnode-only queries, every qnode must have curie(s) specified.")
        answer_kg = {"nodes": dict(), "edges": dict()}
        for qnode_key, qnode in trapi_query["nodes"].items():
            descendant_to_query_curie_map = defaultdict(set)
            qnode_ids = self._convert_to_set(qnode["ids"])
            input_curies = qnode["ids"]
            if qnode.get("allow_subclasses"):
                for query_curie in qnode_ids:
                    descendants = self._get_descendants(query_curie)
                    for descendant in descendants:
                        # Record query curie mapping if this is a descendant not listed in the QG
                        if descendant not in qnode_ids:
                            descendant_to_query_curie_map[descendant].add(query_curie)
                    input_curies += descendants
            found_curies = set(input_curies).intersection(set(self.node_lookup_map))
            if found_curies:
                if trapi_query.get("include_metadata"):
                    answer_kg["nodes"][qnode_key] = {node_id: self.node_lookup_map[node_id] + (list(descendant_to_query_curie_map.get(node_id, set())),)
                                                     for node_id in found_curies}
                else:
                    answer_kg["nodes"][qnode_key] = list(found_curies)
        return answer_kg

    def _get_descendants(self, node_ids: Union[List[str], str]) -> List[str]:
        node_ids = self._convert_to_set(node_ids)
        proper_descendants = {descendant_id for node_id in node_ids
                              for descendant_id in self.subclass_index.get(node_id, set())}
        descendants = proper_descendants.union(node_ids)
        return list(descendants)

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

    def _get_expanded_output_category_ids(self, output_qnode_key: str, trapi_query: dict) -> Set[int]:
        output_category_names_raw = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get("categories"))
        output_category_names_raw = {self.bh.get_root_category()} if not output_category_names_raw else output_category_names_raw
        output_category_names = self.bh.replace_mixins_with_direct_mappings(output_category_names_raw)
        output_categories_with_descendants = self.bh.get_descendants(output_category_names, include_mixins=False)
        output_category_ids = {self.category_map.get(category, self.non_biolink_item_id) for category in output_categories_with_descendants}
        return output_category_ids

    def _consider_bidirectional(self, predicate: str, direct_qg_predicates: Set[str]) -> bool:
        """
        This function determines whether or not QEdge direction should be ignored for a particular predicate or
        'conglomerate' predicate based on the Biolink model and QG parameters.
        """
        if "--" in predicate:  # Means it's a 'conglomerate' predicate
            predicate = self._get_used_predicate(predicate)
        # Make sure we extract the true predicate/qualified predicate from conglomerate predicates
        direct_qg_predicates = {self._get_used_predicate(direct_predicate) for direct_predicate in direct_qg_predicates}

        ancestor_predicates = set(self.bh.get_ancestors(predicate, include_mixins=False))
        ancestor_predicates_in_qg = ancestor_predicates.intersection(direct_qg_predicates)
        has_symmetric_ancestor_in_qg = any(self.bh.is_symmetric(ancestor) for ancestor in ancestor_predicates_in_qg)
        has_asymmetric_ancestor_in_qg = any(not self.bh.is_symmetric(ancestor) for ancestor in ancestor_predicates_in_qg)
        if self.bh.is_symmetric(predicate) or (has_symmetric_ancestor_in_qg and not has_asymmetric_ancestor_in_qg):
            return True
        else:
            return False

    @staticmethod
    def _get_used_predicate(conglomerate_predicate: str) -> str:
        """
        This extracts the predicate used as part of the conglomerate predicate (which could be either the qualified
        predicate or regular predicate).
        """
        return conglomerate_predicate.split("--")[0]

    def _force_qedge_to_canonical_predicates(self, qedge: dict):
        user_qual_predicates = self._get_qualified_predicates_from_qedge(qedge)
        user_regular_predicates = self._convert_to_set(qedge.get("predicates"))
        user_predicates = user_qual_predicates if user_qual_predicates else user_regular_predicates
        canonical_predicates = set(self.bh.get_canonical_predicates(user_predicates))
        user_non_canonical_predicates = user_predicates.difference(canonical_predicates)
        user_canonical_predicates = user_predicates.intersection(canonical_predicates)
        if user_non_canonical_predicates and not user_canonical_predicates:
            # It's safe to flip this qedge's direction so that it uses only the canonical form
            original_subject = qedge["subject"]
            qedge["subject"] = qedge["object"]
            qedge["object"] = original_subject
            if user_qual_predicates:
                # Flip all of the qualified predicates
                for qualifier_constraint in qedge.get("qualifier_constraints", []):
                    for qualifier in qualifier_constraint.get("qualifier_set"):
                        if qualifier["qualifier_type_id"] == self.qedge_qualified_predicate_property:
                            canonical_qual_predicate = self.bh.get_canonical_predicates(qualifier["qualifier_value"])[0]
                            qualifier["qualifier_value"] = canonical_qual_predicate
            else:
                # Otherwise just flip all of the regular predicates
                qedge["predicates"] = list(canonical_predicates)
        elif user_non_canonical_predicates and user_canonical_predicates:
            raise ValueError(f"QueryGraph uses both canonical and non-canonical "
                             f"{'qualified ' if user_qual_predicates else ''}predicates. Canonical: "
                             f"{user_canonical_predicates}, Non-canonical: {user_non_canonical_predicates}. "
                             f"You must use either all canonical or all non-canonical predicates.")

    def _get_qualified_predicates_from_qedge(self, qedge: dict) -> Set[str]:
        qualified_predicates = set()
        for qualifier_constraint in qedge.get("qualifier_constraints", []):
            for qualifier in qualifier_constraint.get("qualifier_set"):
                if qualifier["qualifier_type_id"] == self.qedge_qualified_predicate_property:
                    qualified_predicates.add(qualifier["qualifier_value"])
        return qualified_predicates

    def _get_expanded_qedge_predicates(self, qedge: dict) -> Dict[str, bool]:
        """
        This function returns a qedge's "conglomerate" predicates for qualified qedges (where the qualified info is kind
        of flattened or conglomerated into one derived predicate string), or its regular predicates when no qualified
        info is available. It also returns descendants of the predicates/conglomerate predicates.
        """
        # Use 'conglomerate' predicates if the query has any qualifier constraints
        if qedge.get("qualifier_constraints"):
            qedge_conglomerate_predicates = self._get_conglomerate_predicates_from_qedge(qedge)
            logging.info(f"Qedge conglomerate predicates are: {qedge_conglomerate_predicates}")
            # Now find all descendant versions of our conglomerate predicates (pre-computed during index-building)
            qedge_conglomerate_predicates_expanded = {descendant for conglomerate_predicate in qedge_conglomerate_predicates
                                                      for descendant in self.conglomerate_predicate_descendant_index.get(conglomerate_predicate, set())}
            logging.info(f"Qedge conglomerate predicates expanded are: {qedge_conglomerate_predicates_expanded}")
            qedge_predicates = qedge_conglomerate_predicates
            qedge_predicates_expanded = qedge_conglomerate_predicates_expanded
        # Otherwise we'll use the regular predicates if no qualified predicates were given
        else:
            qedge_predicates_raw = self._convert_to_set(qedge.get("predicates"))
            qedge_predicates_raw = {self.bh.get_root_predicate()} if not qedge_predicates_raw else qedge_predicates_raw
            qedge_predicates = self.bh.replace_mixins_with_direct_mappings(qedge_predicates_raw)
            qedge_predicates_expanded = {descendant_predicate for qg_predicate in qedge_predicates
                                         for descendant_predicate in self.bh.get_descendants(qg_predicate, include_mixins=False)}
            logging.info(f"Qedge predicates expanded are: {qedge_predicates_expanded}")
        # Convert english categories/predicates/conglomerate predicates into integer IDs (helps save space)
        qedge_predicate_ids_dict = {self.predicate_map.get(predicate, self.non_biolink_item_id):
                                        self._consider_bidirectional(predicate, qedge_predicates)
                                    for predicate in qedge_predicates_expanded}

        return qedge_predicate_ids_dict

    def _get_conglomerate_predicates_from_qedge(self, qedge: dict) -> Set[str]:
        qedge_conglomerate_predicates = set()
        # First get the direct conglomerate predicates for this query edge
        for qualifier_constraint in qedge.get("qualifier_constraints", []):
            qualifier_dict = {qualifier["qualifier_type_id"]: qualifier["qualifier_value"]
                              # TODO: Ask TRAPI group why qualifier_set isn't a dict?
                              for qualifier in qualifier_constraint["qualifier_set"]}
            # Use the regular predicate (could be multiple) if no qualified predicate is specified
            qualified_predicate = qualifier_dict.get(self.qedge_qualified_predicate_property)
            object_aspect_qualifier = qualifier_dict.get(self.qedge_object_aspect_property)
            object_direction_qualifier = qualifier_dict.get(self.qedge_object_direction_property)
            predicates = qedge.get("predicates")
            if predicates and not qualified_predicate:
                # We'll use any regular predicate(s) if no qualified predicate was given
                new_conglomerate_predicates = {self._get_conglomerate_predicate(qualified_predicate=qualified_predicate,
                                                                                predicate=predicate,
                                                                                object_direction=object_direction_qualifier,
                                                                                object_aspect=object_aspect_qualifier)
                                               for predicate in predicates}
                qedge_conglomerate_predicates = qedge_conglomerate_predicates.union(new_conglomerate_predicates)
            else:
                # Use the qualified predicate (is 'None' if not available)
                qedge_conglomerate_predicates.add(self._get_conglomerate_predicate(qualified_predicate=qualified_predicate,
                                                                                   predicate=None,
                                                                                   object_direction=object_direction_qualifier,
                                                                                   object_aspect=object_aspect_qualifier))
        return qedge_conglomerate_predicates

    # ----------------------------------------- GENERAL HELPER METHODS ---------------------------------------------- #

    def _get_file_names_to_use_unzipped(self) -> Tuple[Optional[str], Optional[str]]:
        remote_edges_file_name = self.kg_config.get("remote_edges_file_name")
        remote_nodes_file_name = self.kg_config.get("remote_nodes_file_name")
        local_edges_file_name = self.kg_config.get("local_edges_file_name")
        local_nodes_file_name = self.kg_config.get("local_nodes_file_name")
        if local_edges_file_name and local_nodes_file_name:
            return local_nodes_file_name.strip(".gz"), local_edges_file_name.strip(".gz")
        elif remote_edges_file_name and remote_nodes_file_name:
            return remote_nodes_file_name.strip(".gz"), remote_edges_file_name.strip(".gz")
        else:
            logging.error("In kg_config.json, you must specify what edge/nodes files to use - either remote files "
                          "(on kg2webhost) or local files")
            return None, None

    @staticmethod
    def _convert_to_set(input_item: any) -> Set[str]:
        if isinstance(input_item, str):
            return {input_item}
        elif isinstance(input_item, list):
            return set(input_item)
        else:
            return set()

    @staticmethod
    def serialize_with_sets(obj: any) -> any:
        # Thank you https://stackoverflow.com/a/60544597
        if isinstance(obj, set):
            return list(obj)
        else:
            return obj


def main():
    plover = PloverDB()
    plover.build_indexes()
    plover.load_indexes()


if __name__ == "__main__":
    main()
