#!/usr/bin/env python3
import json
import logging
import os
import pathlib
import pickle
import statistics
import subprocess
import time
from collections import defaultdict
from typing import List, Dict, Union, Set, Optional, Tuple

SCRIPT_DIR = f"{os.path.dirname(os.path.abspath(__file__))}"


class PloverDB:

    def __init__(self):
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s %(levelname)s: %(message)s',
                            handlers=[logging.StreamHandler()])
        self.config_file_path = f"{SCRIPT_DIR}/../kg_config.json"
        with open(self.config_file_path) as config_file:
            self.kg_config = json.load(config_file)
        self.is_test = self.kg_config["is_test"]
        self.remote_index_file_name = self.kg_config["remote_index_file_name"]
        self.remote_kg_file_name = self.kg_config["remote_kg_file_name"]
        self.local_kg_file_name = self.kg_config["local_kg_file_name"]
        self.pickle_index_name, self.kg_json_name = self._get_local_file_names()
        self.kg_json_path = f"{SCRIPT_DIR}/../{self.kg_json_name}"
        self.pickle_index_path = f"{SCRIPT_DIR}/../{self.pickle_index_name}"
        self.predicate_property = self.kg_config["labels"]["edges"]
        self.categories_property = self.kg_config["labels"]["nodes"]
        self.bh = None  # BiolinkHelper is downloaded later on
        self.core_node_properties = {"name", "category"}
        self.non_biolink_item_id = 9999
        self.category_map = dict()  # Maps category english name --> int ID
        self.predicate_map = dict()  # Maps predicate english name --> int ID
        self.predicate_map_reversed = dict()  # Maps predicate int ID --> english name
        self.node_lookup_map = dict()
        self.edge_lookup_map = dict()
        self.main_index = dict()
        self.subclass_index = dict()

    # ------------------------------------------ INDEX BUILDING METHODS --------------------------------------------- #

    def build_indexes(self):
        logging.info("Starting to build indexes..")
        start = time.time()

        # Download the proper remote data file or get set up to use a local KG file
        if self.remote_index_file_name:
            self._download_and_unzip_remote_file(self.remote_index_file_name, self.pickle_index_path)
            return  # No need to re-build indexes since we were able to download them
        elif self.remote_kg_file_name:
            self._download_and_unzip_remote_file(self.remote_kg_file_name, self.kg_json_path)
        else:
            logging.info(f"Will use local KG file {self.local_kg_file_name}")
            if self.local_kg_file_name.endswith(".gz"):
                logging.info(f"Unzipping local KG file")
                subprocess.check_call(["gunzip", "-f", f"{self.kg_json_path}.gz"])

        # Load the JSON KG
        logging.info(f"Loading KG JSON file ({self.kg_json_name})..")
        with open(self.kg_json_path, "r") as kg2c_file:
            kg2c_dict = json.load(kg2c_file)
            biolink_version = kg2c_dict.get("biolink_version")
            if biolink_version:
                logging.info(f"  Biolink version for this KG is {biolink_version}")

        # Set up BiolinkHelper (download from RTX repo)
        bh_file_name = "biolink_helper.py"
        logging.info(f"Downloading {bh_file_name} from RTX repo")
        local_path = f"{SCRIPT_DIR}/{bh_file_name}"
        remote_path = f"https://github.com/RTXteam/RTX/blob/master/code/ARAX/BiolinkHelper/{bh_file_name}?raw=true"
        subprocess.check_call(["curl", "-L", remote_path, "-o", local_path])
        from biolink_helper import BiolinkHelper
        self.bh = BiolinkHelper(biolink_version=biolink_version)

        # Create basic node/edge lookup maps
        logging.info(f"Building basic node/edge lookup maps")
        self.node_lookup_map = {node["id"]: node for node in kg2c_dict["nodes"]}
        self.edge_lookup_map = {edge["id"]: edge for edge in kg2c_dict["edges"]}

        # Convert all edges to their canonical predicate form
        logging.info(f"Converting edges to their canonical form")
        for edge_id, edge in self.edge_lookup_map.items():
            canonical_predicate = self.bh.get_canonical_predicates(edge["predicate"])[0]
            if canonical_predicate != edge["predicate"]:
                # Flip the edge (because the original predicate must be the canonical predicate's inverse)
                edge["predicate"] = canonical_predicate
                original_subject = edge["subject"]
                edge["subject"] = edge["object"]
                edge["object"] = original_subject

        if self.is_test:
            # Narrow down our test JSON file to make sure all node IDs used by edges appear in our node_lookup_map
            node_ids_used_by_edges = {edge["subject"] for edge in self.edge_lookup_map.values()}.union(edge["object"] for edge in self.edge_lookup_map.values())
            node_lookup_map_trimmed = {node_id: self.node_lookup_map[node_id] for node_id in node_ids_used_by_edges
                                       if node_id in self.node_lookup_map}
            self.node_lookup_map = node_lookup_map_trimmed
            edge_lookup_map_trimmed = {edge_id: edge for edge_id, edge in self.edge_lookup_map.items() if
                                       edge["subject"] in self.node_lookup_map and edge["object"] in self.node_lookup_map}
            self.edge_lookup_map = edge_lookup_map_trimmed

        # Build a helper map of nodes --> category labels (including ancestors)
        logging.info("Determining nodes' category labels (including Biolink ancestors)..")
        node_to_category_labels_map = dict()
        for node_id, node in self.node_lookup_map.items():
            category_names = node[self.categories_property]
            category_names_with_ancestors = self.bh.get_ancestors(category_names, include_mixins=False)
            node_to_category_labels_map[node_id] = {self._get_category_id(category_name)
                                                    for category_name in category_names_with_ancestors}

        # Build our main index (modified/nested adjacency list kind of structure)
        logging.info("Building main index..")
        count = 0
        total = len(self.edge_lookup_map)
        for edge_id, edge in self.edge_lookup_map.items():
            subject_id = edge["subject"]
            object_id = edge["object"]
            predicate = self._get_predicate_id(edge[self.predicate_property])
            subject_categories = node_to_category_labels_map[subject_id]
            object_categories = node_to_category_labels_map[object_id]
            # Record this edge in both the forwards and backwards direction
            self._add_to_main_index(subject_id, object_id, object_categories, predicate, edge_id, 1)
            self._add_to_main_index(object_id, subject_id, subject_categories, predicate, edge_id, 0)
            count += 1
            if count % 1000000 == 0:
                logging.info(f"  Have processed {count} edges ({round((count / total) * 100)}%)..")

        # Build the subclass_of index as needed
        if self.kg_config.get("subclass_sources"):
            self._build_subclass_index(set(self.kg_config["subclass_sources"]))
        else:
            logging.info(f"Not building subclass_of index since no subclass sources were specified in kg_config.json")

        # Convert node/edge lookup maps into tuple forms (and get rid of extra properties) to save space
        logging.info("Converting node/edge objects to tuple form..")
        node_properties = ("name", "category")
        edge_properties = ("subject", "object", "predicate", "knowledge_source")
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

        # Save all indexes in a big pickle
        logging.info(f"Saving indexes to {self.pickle_index_path}..")
        all_indexes = {"node_lookup_map": self.node_lookup_map,
                       "edge_lookup_map": self.edge_lookup_map,
                       "node_headers": node_properties,
                       "edge_headers": edge_properties,
                       "main_index": self.main_index,
                       "subclass_index": self.subclass_index,
                       "predicate_map": self.predicate_map,
                       "category_map": self.category_map,
                       "biolink_version": biolink_version}
        with open(self.pickle_index_path, "wb") as index_file:
            pickle.dump(all_indexes, index_file, protocol=pickle.HIGHEST_PROTOCOL)

        logging.info(f"Removing {self.kg_json_name} from the image now that index building is done")
        subprocess.call(["rm", "-f", self.kg_json_path])

        logging.info(f"Done building indexes! Took {round((time.time() - start) / 60, 2)} minutes.")

    def load_indexes(self):
        logging.info(f"Checking whether pickle of indexes is already available..")
        pickle_index_file = pathlib.Path(self.pickle_index_path)
        if not pickle_index_file.exists():
            if self.remote_index_file_name:
                # Download the pre-computed pickle of indexes
                self._download_and_unzip_remote_file(self.remote_index_file_name, self.pickle_index_path)
            else:
                # Otherwise we'll have to build indexes from a KG file
                logging.info(f"No index pickle exists and none was specified for download in kg_config.json - will "
                             f"build indexes")
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
            self.predicate_map_reversed = {value: key for key, value in self.predicate_map.items()}
            self.category_map = all_indexes["category_map"]
            biolink_version = all_indexes["biolink_version"]

        # Set up BiolinkHelper
        from biolink_helper import BiolinkHelper
        self.bh = BiolinkHelper(biolink_version=biolink_version)

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

    def _build_subclass_index(self, subclass_sources: Set[str]):
        logging.info(f"  Building subclass_of index using {subclass_sources} edges..")
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
                             if edge[self.predicate_property] in subclass_predicates and
                             set(edge.get("knowledge_source", set())).intersection(subclass_sources)}
        logging.info(f"    Found {len(subclass_edge_ids)} subclass_of edges to consider (from specified sources)")

        # Build a map of nodes to their direct 'subclass_of' children
        parent_to_child_dict = defaultdict(set)
        for edge_id in subclass_edge_ids:
            edge = self.edge_lookup_map[edge_id]
            parent_node_id = edge["object"] if edge[self.predicate_property] == "biolink:subclass_of" else edge["subject"]
            child_node_id = edge["subject"] if edge[self.predicate_property] == "biolink:subclass_of" else edge["object"]
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

        logging.info(f"  Building subclass_of index took {round((time.time() - start) / 60, 2)} minutes.")

    @staticmethod
    def _download_and_unzip_remote_file(remote_file_name: str, local_destination_path: str):
        logging.info(f"Downloading remote file {remote_file_name} from translator-lfs-artifacts repo")
        temp_location = f"{SCRIPT_DIR}/{remote_file_name}"
        remote_path = f"https://github.com/ncats/translator-lfs-artifacts/blob/main/files/{remote_file_name}?raw=true"
        subprocess.check_call(["curl", "-L", remote_path, "-o", temp_location])
        if remote_file_name.endswith(".gz"):
            logging.info(f"Unzipping downloaded file")
            subprocess.check_call(["gunzip", "-f", temp_location])
            temp_location = temp_location.strip(".gz")
        subprocess.check_call(["mv", temp_location, local_destination_path])

    # ---------------------------------------- QUERY ANSWERING METHODS ------------------------------------------- #

    def answer_query(self, trapi_query: dict) -> Dict[str, Dict[str, Union[set, dict]]]:
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
        descendant_to_query_curie_map = {subject_qnode_key: dict(), object_qnode_key: dict()}
        if subject_qnode.get("ids") and subject_qnode.get("allow_subclasses"):
            subject_qnode_curies_with_descendants = list()
            subject_qnode_curies = set(subject_qnode["ids"])
            for query_curie in subject_qnode_curies:
                descendants = self._get_descendants(query_curie)
                for descendant in descendants:
                    # We only want to record the mapping in the case of a true descendant
                    if descendant not in subject_qnode_curies:
                        descendant_to_query_curie_map[subject_qnode_key][descendant] = query_curie
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
                        descendant_to_query_curie_map[object_qnode_key][descendant] = query_curie
                object_qnode_curies_with_descendants += descendants
            object_qnode["ids"] = list(set(object_qnode_curies_with_descendants))

        # Convert to canonical predicates in the QG as needed
        user_predicates = self._convert_to_set(qedge.get("predicates"))
        canonical_predicates = set(self.bh.get_canonical_predicates(user_predicates))
        user_non_canonical_predicates = user_predicates.difference(canonical_predicates)
        user_canonical_predicates = user_predicates.intersection(canonical_predicates)
        if user_non_canonical_predicates and not user_canonical_predicates:
            # It's safe to flip this qedge so that it uses only the canonical form
            original_subject = qedge["subject"]
            qedge["subject"] = qedge["object"]
            qedge["object"] = original_subject
            qedge["predicates"] = list(canonical_predicates)
        elif user_non_canonical_predicates and user_canonical_predicates:
            raise ValueError(f"QueryGraph uses both canonical and non-canonical predicates. Canonical: "
                             f"{user_canonical_predicates}, Non-canonical: {user_non_canonical_predicates}. "
                             f"You must use either all canonical or all non-canonical predicates.")

        # Load the query and do any necessary transformations to categories/predicates
        enforce_directionality = trapi_query.get("enforce_directionality")
        respect_symmetry = trapi_query.get("respect_predicate_symmetry")
        input_qnode_key = self._determine_input_qnode_key(trapi_query["nodes"])
        output_qnode_key = list(set(trapi_query["nodes"]).difference({input_qnode_key}))[0]
        input_curies = self._convert_to_set(trapi_query["nodes"][input_qnode_key]["ids"])
        output_category_names_raw = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get("categories"))
        output_category_names_raw = {self.bh.get_root_category()} if not output_category_names_raw else output_category_names_raw
        output_category_names = self.bh.replace_mixins_with_direct_mappings(output_category_names_raw)
        output_curies = self._convert_to_set(trapi_query["nodes"][output_qnode_key].get("ids"))
        qg_predicate_names_raw = self._convert_to_set(qedge.get("predicates"))
        qg_predicate_names_raw = {self.bh.get_root_predicate()} if not qg_predicate_names_raw else qg_predicate_names_raw
        qg_predicate_names = self.bh.replace_mixins_with_direct_mappings(qg_predicate_names_raw)
        qg_predicate_names_expanded = {descendant_predicate for qg_predicate in qg_predicate_names
                                       for descendant_predicate in self.bh.get_descendants(qg_predicate, include_mixins=False)}
        # Convert the string/english versions of categories/predicates into integer IDs (helps save space)
        output_categories = {self.category_map.get(category, self.non_biolink_item_id) for category in output_category_names}
        qg_predicates = {self.predicate_map.get(predicate, self.non_biolink_item_id): self._consider_bidirectional(predicate, qg_predicate_names, respect_symmetry, enforce_directionality)
                         for predicate in qg_predicate_names_expanded}

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
                        predicates_present = set(main_index[input_curie][output_category])
                        predicates_to_inspect = set(qg_predicates).intersection(predicates_present)
                        # Loop through each QG predicate (and their descendants), looking up answers as we go
                        for predicate in predicates_to_inspect:
                            consider_bidirectional = qg_predicates.get(predicate)
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
                                        answer_edge_ids.append(main_index[input_curie][output_category][predicate][direction][output_curie])
                            else:
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
            nodes = {input_qnode_key: {node_id: self.node_lookup_map[node_id] + (descendant_to_query_curie_map[input_qnode_key].get(node_id))
                                       for node_id in final_input_qnode_answers},
                     output_qnode_key: {node_id: self.node_lookup_map[node_id] + (descendant_to_query_curie_map[output_qnode_key].get(node_id))
                                        for node_id in final_output_qnode_answers}}
            edges = {qedge_key: {edge_id: self.edge_lookup_map[edge_id] for edge_id in final_qedge_answers}}
        else:
            nodes = {input_qnode_key: list(final_input_qnode_answers),
                     output_qnode_key: list(final_output_qnode_answers)}
            edges = {qedge_key: list(final_qedge_answers)}
        answer_kg = {"nodes": nodes, "edges": edges}
        return answer_kg

    def _answer_edgeless_query(self, trapi_query: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]) -> Dict[str, Dict[str, Union[set, dict]]]:
        # When no qedges are involved, we only fulfill qnodes that have a curie
        if not all(qnode.get("ids") for qnode in trapi_query["nodes"].values()):
            raise ValueError("For qnode-only queries, every qnode must have curie(s) specified.")
        answer_kg = {"nodes": dict(), "edges": dict()}
        for qnode_key, qnode in trapi_query["nodes"].items():
            input_curies = set(self._get_descendants(qnode["ids"])) if qnode.get("allow_subclasses") else self._convert_to_set(qnode["ids"])
            found_curies = input_curies.intersection(set(self.node_lookup_map))
            if found_curies:
                if trapi_query.get("include_metadata"):
                    answer_kg["nodes"][qnode_key] = {node_id: self.node_lookup_map[node_id] for node_id in found_curies}
                else:
                    answer_kg["nodes"][qnode_key] = list(found_curies)
        return answer_kg

    def _get_descendants(self, node_ids: List[str]) -> List[str]:
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

    def _consider_bidirectional(self, predicate_name: str, input_qg_predicate_names: Set[str], respect_symmetry: bool,
                                enforce_directionality: bool) -> bool:
        """
        This function determines whether or not QEdge direction should be ignored for a particular predicate
        based on the Biolink model and QG parameters.
        """
        ancestor_predicates = set(self.bh.get_ancestors(predicate_name, include_mixins=False))
        ancestor_predicates_in_qg = ancestor_predicates.intersection(input_qg_predicate_names)
        has_symmetric_ancestor_in_qg = any(self.bh.is_symmetric(ancestor) for ancestor in ancestor_predicates_in_qg)
        has_asymmetric_ancestor_in_qg = any(not self.bh.is_symmetric(ancestor) for ancestor in ancestor_predicates_in_qg)
        if respect_symmetry:
            if self.bh.is_symmetric(predicate_name) or (has_symmetric_ancestor_in_qg and not has_asymmetric_ancestor_in_qg):
                return True
            else:
                return False
        else:
            return True if not enforce_directionality else False

    # ----------------------------------------- GENERAL HELPER METHODS ---------------------------------------------- #

    def _get_local_file_names(self) -> Tuple[Optional[str], Optional[str]]:
        remote_index_file_name = self.kg_config.get("remote_index_file_name")
        remote_kg_file_name = self.kg_config.get("remote_kg_file_name")
        local_kg_file_name = self.kg_config.get("local_kg_file_name")
        if not remote_index_file_name and not remote_kg_file_name and not local_kg_file_name:
            logging.error("In kg_config.json, you must specify either a remote file to download (either a JSON KG "
                          "file or a pickle file of indexes) from the translator-lfs-artifacts repo or a local KG "
                          "file to use.")
            return None, None
        else:
            if remote_index_file_name:
                return remote_index_file_name.strip(".gz"), None
            else:
                kg_file_name = remote_kg_file_name.strip(".gz") if remote_kg_file_name else local_kg_file_name.strip(".gz")
                index_file_name = f"{kg_file_name.strip('.json')}_indexes.pickle"
                return index_file_name, kg_file_name

    @staticmethod
    def _convert_to_set(input_item: any) -> Set[str]:
        if isinstance(input_item, str):
            return {input_item}
        elif isinstance(input_item, list):
            return set(input_item)
        else:
            return set()


def main():
    plover = PloverDB()
    plover.build_indexes()
    plover.load_indexes()


if __name__ == "__main__":
    main()
