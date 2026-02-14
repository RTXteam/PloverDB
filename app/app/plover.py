"""
PloverDB: An in-memory, Biolink-compliant, TRAPI-speaking graph database.

This module implements the core PloverDB engine for loading, indexing,
querying, and serving biomedical knowledge graphs in compliance with
the Biolink Model and the Translator Reasoner API (TRAPI).

PloverDB supports:

- Streaming ingestion of large node and edge files (TSV/JSONL, optionally gzipped)
- Canonicalization and normalization of identifiers via the SRI Node Normalizer
- Construction of optimized in-memory indexes for fast query answering
- Support for qualified predicates, subclass reasoning, and predicate hierarchies
- Generation of TRAPI-compliant knowledge graph and result responses
- Persistent caching of indexes via pickling for fast reloads

The primary entry point is the :class:`PloverDB` class, which manages
index construction, loading, and query execution for a single
knowledge-provider endpoint as defined by a configuration file.

This module is intended to be executed and imported as a Python package. 
It must not be run directly as a standalone script.

Typical usage::

    from app.plover import PloverDB

    plover = PloverDB(config_file_name="config.json")
    plover.build_indexes()
    plover.load_indexes()
    result = plover.answer_query(trapi_query)

Index building is typically performed offline (e.g., during container
builds or deployment) and reused at runtime.

Note
----
Because this module constructs large in-memory data structures, it is
designed for environments with substantial RAM and includes utilities
for monitoring and debugging memory usage.
"""
from __future__ import annotations
import copy
import csv
import gc
import inspect
import itertools
import json
from datetime import datetime
from urllib.parse import urlparse

import gzip
import logging
import os
import pickle
import pprint
import shutil
import statistics
import subprocess
import sys
import time

from collections import defaultdict
from collections.abc import Sequence, Mapping, Set as ABCSet
from typing import Union, Optional, cast, Iterator, Any
from pathlib import Path
from pympler import asizeof

import flask
import psutil
import requests

# pylint: disable=wrong-import-position
if __name__ == "__main__" and __package__ is None:
    raise SystemExit("ERROR: This module must be run as a package")
from .biolink_helper import get_biolink_helper

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = "/var/log/ploverdb.log"
DEFAULT_TIMEOUT = (4.0, 30.0)
equivalent_curies_property_tuple = ("equivalent_curies",
                                    "equivalent_identifiers",
                                    "equivalent_ids",
                                    "same_as")

def _add_edge_to_main_index_bidir(
        main_index: dict[str, dict],
        subject_id: str,
        object_id: str,
        subject_category_ids: set[int],
        object_category_ids: set[int],
        predicate_id: int,
        edge_id: str,
) -> None:
    main_sd = main_index.setdefault

    # forward (subject -> object), direction=1
    node_map = main_sd(subject_id, {})
    node_sd = node_map.setdefault
    for category_id in object_category_ids:
        cat_map = node_sd(category_id, {})
        pred_map = cat_map.setdefault(predicate_id, [{}, {}])
        dir_map = pred_map[1]
        dir_map.setdefault(object_id, set()).add(edge_id)

    # backward (object -> subject), direction=0
    node_map = main_sd(object_id, {})
    node_sd = node_map.setdefault
    for category_id in subject_category_ids:
        cat_map = node_sd(category_id, {})
        pred_map = cat_map.setdefault(predicate_id, [{}, {}])
        dir_map = pred_map[0]
        dir_map.setdefault(subject_id, set()).add(edge_id)

def _pprint_sizes_mb(
    sizes: Mapping[str, int],
    *,
    precision: int = 2,
    multiplier: float = 1.0
) -> None:
    """
    Pretty-print a mapping of sizes in bytes, converted to MB.

    Args:
        sizes: Mapping from key -> size in bytes
        precision: Number of decimal places for MB values
    """
    mb = 1024 * 1024

    converted = {
        key: f"{round(multiplier * val / mb, precision)} MB"
        for key, val in sizes.items()
    }

    pprint.pprint(converted)

def _sizeof_dict_entries(edge: dict[Any, Any]) -> dict[Any, int]:
    """
    Return a dict mapping each key in `edge` to the total memory footprint
    (in bytes) of that key and its associated value.

    The key is measured shallowly via sys.getsizeof.
    The value is measured deeply via pympler.asizeof.

    Parameters
    ----------
    edge : dict
        Dictionary whose entries will be sized.

    Returns
    -------
    dict
        Mapping: key -> (sizeof(key) + deep sizeof(value)) in bytes.
    """

    sizes: dict[Any, int] = {}

    for key, value in edge.items():

        try:
            key_size = sys.getsizeof(key)
        except TypeError:
            key_size = 0

        try:
            value_size = asizeof.asizeof(value)
        except (TypeError, ValueError, OverflowError, MemoryError):
            value_size = 0

        sizes[key] = key_size + value_size

    return sizes

def _get_current_memory_usage() -> tuple[float, float, float]:
    vm = psutil.virtual_memory()

    proc = psutil.Process()

    return (
        round(vm.available / 1024**3, 1),            # "system_vm_available_used_gb"
        round(vm.percent, 1),                        # "system_percent"
        round(proc.memory_info().rss / 1024**3, 1),  # process_rss_gb
    )


def _format_memory_usage(message: str,
                         *
                         args) -> tuple:
    return (message + "Memory: %sG available; %s%% used; process using %sG",
            *args,
            *_get_current_memory_usage())


def _print_top_objects(
    *,
    limit: int = 30,
    min_mb: float = 1.0,
    depth: int = 1,
) -> None:
    """
    Print largest objects from:
      - caller locals
      - self attributes (if present)
      - globals

    De-duplicates shared objects.

    Call from inside a function/method.
    """

    frame = inspect.currentframe()
    assert frame is not None

    try:
        # Walk up to caller frame
        for _ in range(depth):
            frame = frame.f_back  # type: ignore[assignment]
            if frame is None:
                return

        seen: set[int] = set()
        results: list[tuple[str, str, int, str]] = []
        # (source, name, size, type)

        def scan_namespace(
            source: str,
            ns: Mapping[str, object],
        ) -> None:
            for name, val in ns.items():
                oid = id(val)
                if oid in seen:
                    continue
                seen.add(oid)

                try:
                    size = asizeof.asizeof(val)
                except (TypeError, ValueError, OverflowError, MemoryError):
                    continue

                size_mb = size / 1024 / 1024
                if size_mb < min_mb:
                    continue

                results.append(
                    (
                        source,
                        name,
                        size,
                        type(val).__name__,
                    )
                )

        # ---- locals ----
        scan_namespace("local", frame.f_locals)

        # ---- self attrs ----
        self_obj = frame.f_locals.get("self")
        if self_obj is not None:
            try:
                scan_namespace("self", vars(self_obj))
            except (TypeError, AttributeError):
                # TypeError: no __dict__ (e.g., __slots__)
                # AttributeError: unusual/proxy objects
                pass

        # ---- globals ----
        scan_namespace("global", frame.f_globals)

        # ---- sort ----
        results.sort(key=lambda x: x[2], reverse=True)

        # ---- print ----
        print(f"\n=== Top Memory Objects (>{min_mb:.1f} MB) ===\n")

        for src, name, size, typ in results[:limit]:
            print(
                f"[{src:6s}] "
                f"{name:30s} "
                f"{size/1024/1024:8.2f} MB  "
                f"({typ})"
            )

        print()

    finally:
        # Prevent reference cycles
        del frame

def _convert_to_set(input_item: Any) -> set[str]:
    if isinstance(input_item, str):
        return {input_item}
    if isinstance(input_item, list):
        return set(input_item)
    if isinstance(input_item, set):
        return input_item
    return set()

def _convert_to_list(input_item: Any) -> list[str]:
    if isinstance(input_item, str):
        return [input_item]
    if isinstance(input_item, list):
        return input_item
    if isinstance(input_item, set):
        return list(input_item)
    return []

def _is_empty(value: Any) -> bool:
    if isinstance(value, list):
        return all(_is_empty(item) for item in value)
    if value or isinstance(value, (int, float, complex)):
        return False
    return True

def _url_basename(file_or_url: str) -> str:
    """
    If file_or_url is a URL, return its base filename.
    Otherwise return None.
    """
    parsed = urlparse(file_or_url)
    # Must have scheme and netloc to be a real URL
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Not a valid URL: {file_or_url}")

    # Extract last path component
    name = Path(parsed.path).name
    if not name:
        raise ValueError(f"URL has no basename: {file_or_url}")
    return name

def _is_basename(filename: str) -> bool:
    p = Path(filename)
    return (p.name == p.as_posix()) or (p.name == str(p))

def _is_url(some_string: str) -> bool:
    # Thank you: https://stackoverflow.com/a/52455972
    try:
        result = urlparse(some_string)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def _load_pickle_file(file_path: str) -> Any:
    logging.info("Loading %s into memory", file_path)
    start = time.time()
    with open(file_path, "rb") as pickle_file:
        contents = pickle.load(pickle_file)
    logging.info("Done loading %s into memory. Took %s seconds",
                 file_path, round(time.time() - start, 1))
    return contents

def _save_to_pickle_file(item: Any, file_path: str):
    logging.info("Saving data to %s", file_path)
    start = time.time()
    with open(file_path, "wb") as pickle_file:
        pickle.dump(item, pickle_file,
                    protocol=pickle.HIGHEST_PROTOCOL)
    logging.info("Done saving data to %s. Took %s seconds",
                 file_path, round(time.time() - start, 1))

def _download_remote_file(
        remote_file_path: str,
        local_destination_path: str
) -> None:
    """
    Download remote_file_path to local_destination_path using pure Pyo
    Does NOT gunzip: if the URL points to a .gz, the .gz bytes are stored as-is.
    """
    url = remote_file_path
    dest = Path(local_destination_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Download to a temp file in the destination directory (so rename is atomic).
    tmp = dest.with_name(dest.name + ".tmp")

    # Keep raw bytes as served; avoid transfer-encoding gzip auto-decode.
    headers = {"Accept-Encoding": "identity"}

    timeout = DEFAULT_TIMEOUT          # (connect timeout, read timeout) seconds
    chunk_size = 1024**2               # 1 MiB buffer
    retries = 3
    backoff_s = 1.0

    logging.info("Downloading remote file from URL: %s "
                 "to local file %s", url, local_destination_path)

    last_exc: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True,
                              headers=headers,
                              timeout=timeout,
                              allow_redirects=True) as r:
                r.raise_for_status()

                # Ensure we write the raw wire bytes.
                if hasattr(r.raw, "decode_content"):
                    r.raw.decode_content = False

                with open(tmp, "wb") as f:
                    shutil.copyfileobj(r.raw, f, length=chunk_size)

            os.replace(tmp, dest)  # atomic on POSIX if same filesystem
            return

        except (requests.RequestException, OSError) as e:
            last_exc = e
            # Clean up partial temp file
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

            if attempt < retries:
                time.sleep(backoff_s * attempt)
            else:
                raise RuntimeError(f"Failed to download {url} -> {dest}") from e

    raise RuntimeError(f"Failed to download {url} -> {dest}") from last_exc

def _get_equiv_id_map_from_sri(
        node_ids: list[str],
        drug_chemical_conflation: bool = False
) -> dict[str, str]:
    response = requests.post("https://nodenormalization-sri.renci.org/get_normalized_nodes",
                             json={"curies": node_ids,
                                   "conflate": True,
                                   "drug_chemical_conflate": drug_chemical_conflation},
                             timeout=DEFAULT_TIMEOUT)

    # Preferred IDs for nodes are themselves:
    equiv_id_map = {node_id: node_id for node_id in node_ids}
    if response.status_code == 200:
        for node_id, normalized_info in response.json().items():
            if normalized_info:  # This means the SRI NN recognized the node ID we asked for
                equiv_nodes = normalized_info["equivalent_identifiers"]
                for equiv_node in equiv_nodes:
                    equiv_id = equiv_node["identifier"]
                    equiv_id_map[equiv_id] = node_id
    else:
        logging.warning("Request for batch of node IDs sent to SRI NodeNormalizer failed "
                        "(status: %s). Input identifier synonymization may not work properly.",
                        response.status_code)

    return equiv_id_map

def _reverse_dictionary(some_dict: dict) -> dict:
    return {value: key for key, value in some_dict.items()}

def _load_value(val: str) -> Any:
    if isinstance(val, str):
        if val.isdigit():
            return int(val)
        if val.replace(".", "").isdigit():
            return float(val)
        if val.lower() in {"t", "true"}:
            return True
        if val.lower() in {"f", "false"}:
            return False
        if val.lower() in {"none", "null"}:
            return None
        return val
    return val

def _load_column_value(
        col_value: Any,
        col_name: str,
        array_properties: set[str],
        array_delimiter: str
) -> Any:
    # Load lists as actual lists, instead of strings
    if col_name in array_properties:
        return [_load_value(val) for val in col_value.split(array_delimiter)]
    return _load_value(col_value)

def _open_maybe_gzip(path: Path):
    # Returns a text-mode file handle
    if path.suffixes[-1:] == [".gz"]:
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, "rt", encoding="utf-8", newline="")

def _iter_records(fname: str,
                  array_properties: set[str],
                  array_delimiter: str) -> Iterator[dict[str, Any]]:
    path = Path(fname)
    suffixes = path.suffixes

    if not suffixes:
        raise ValueError(f"invalid filepath; expected .tsv/.jsonl (optionally .gz): {fname}")

    is_gz = suffixes[-1:] == [".gz"]
    base_suffixes = suffixes[:-1] if is_gz else suffixes

    # ---- TSV ----
    if base_suffixes[-1:] == [".tsv"]:
        with _open_maybe_gzip(path) as f:
            reader = csv.reader(f, delimiter="\t")
            try:
                header = next(reader)
            except StopIteration as e:
                raise ValueError(f"file is empty: {fname}") from e

            header = [h.strip() for h in header]
            if len(set(header)) != len(header):
                raise ValueError(f"duplicate column names in header: {fname}")

            for lineno, row in enumerate(reader, start=2):
                if not row or all(not field.strip() for field in row):
                    continue
                if len(row) != len(header):
                    raise ValueError(
                        f"column count mismatch at line {lineno} in {fname}: "
                        f"expected {len(header)} fields, got {len(row)}"
                    )
                yield {col: _load_column_value(val, col, array_properties, array_delimiter)
                       for col, val in zip(header, row)}
        return

    # ---- JSONL ----
    if base_suffixes[-1:] == [".jsonl"]:
        with _open_maybe_gzip(path) as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"invalid JSON at line {lineno} in {fname}") from e
                if not isinstance(obj, dict):
                    raise ValueError(f"expected JSON object at line {lineno} in {fname}")
                yield obj
        return

    # --- Any other file extension is not allowed ---
    raise ValueError(f"invalid filepath; expected .tsv/.jsonl (optionally .gz): {fname}")


def _get_descendants(
    node_id: str,
    parent_to_child_map: Mapping[str, ABCSet[str]],
    parent_to_descendants_map: dict[str, set[str]],
    *,
    max_depth: int = 20,
    problem_nodes: Optional[set[str]] = None,
    _depth: int = 0,
    _visiting: Optional[set[str]] = None,
) -> set[str]:
    """
    Return the transitive descendants of `node_id` using `parent_to_child_map`.

    - Uses `parent_to_descendants_map` as a memoization cache (filled in-place).
    - Detects cycles via a DFS "visiting" set; any node involved in a cycle is
      added to `problem_nodes`.
    - Also adds `node_id` to `problem_nodes` if recursion exceeds `max_depth`.
    - Always returns a (possibly empty) set of descendant node IDs.

    Parameters
    ----------
    node_id:
        The parent node whose descendants you want.
    parent_to_child_map:
        Mapping from parent -> immediate children.
    parent_to_descendants_map:
        Mutable memoization cache: parent -> all descendants.
    max_depth:
        Depth cutoff guard (primarily to avoid pathological recursion).
    problem_nodes:
        Optional set to collect nodes that are part of a cycle or exceed max_depth.

    Notes
    -----
    The underscore-prefixed parameters are internal and should not be passed by callers.
    """

    if node_id in parent_to_descendants_map:
        return parent_to_descendants_map[node_id]

    if problem_nodes is None:
        problem_nodes = set()
    if _visiting is None:
        _visiting = set()

    if _depth > max_depth:
        problem_nodes.add(node_id)
        parent_to_descendants_map.setdefault(node_id, set())
        return parent_to_descendants_map[node_id]

    if node_id in _visiting:
        # Cycle detected
        problem_nodes.add(node_id)
        parent_to_descendants_map.setdefault(node_id, set())
        return parent_to_descendants_map[node_id]

    _visiting.add(node_id)
    descendants: set[str] = set()

    for child_id in parent_to_child_map.get(node_id, set()):
        descendants.add(child_id)
        descendants |= _get_descendants(
            child_id,
            parent_to_child_map,
            parent_to_descendants_map,
            max_depth=max_depth,
            problem_nodes=problem_nodes,
            _depth=_depth + 1,
            _visiting=_visiting,
        )

    _visiting.remove(node_id)

    parent_to_descendants_map[node_id] = descendants
    return descendants


class PloverDB:

    def __init__(self, config_file_name: str):
        # Set up logging (when run outside of docker, can't write to /var/log - handle that
        # situation)
        try:
            logging.basicConfig(level=logging.INFO,
                                format='%(asctime)s %(levelname)s: %(message)s',
                                handlers=[logging.StreamHandler(),
                                          logging.FileHandler(LOG_FILE_PATH)])
        except OSError:
            alt_log_file_path = os.path.join(SCRIPT_DIR, "ploverdb.log")
            logging.basicConfig(level=logging.INFO,
                                format='%(asctime)s %(levelname)s: %(message)s',
                                handlers=[logging.StreamHandler(),
                                          logging.FileHandler(alt_log_file_path)])

        self.config_file_name = config_file_name
        self.parent_dir = os.path.dirname(SCRIPT_DIR)
        config_file_path = os.path.join(self.parent_dir, self.config_file_name)
        with open(config_file_path, encoding="utf-8") as config_file:
            self.kg_config = json.load(config_file)
        self.endpoint_name = self.kg_config["endpoint_name"]
        self.debug = self.kg_config.get("debug", False)
        self.sri_test_triples_path = \
            os.path.join(self.parent_dir, f"sri_test_triples_{self.endpoint_name}.json")
        self.kp_home_html_path = \
            os.path.join(self.parent_dir, f"home_{self.endpoint_name}.html")
        self.indexes_dir_path = \
            os.path.join(self.parent_dir, f"plover_indexes_{self.endpoint_name}")

        self.is_test = self.kg_config.get("is_test")
        self.biolink_version = self.kg_config["biolink_version"]
        logging.info("Biolink version to use is: %s", self.biolink_version)
        self.trapi_attribute_map = self.load_trapi_attribute_map()
        self.num_edges_per_answer_cutoff = \
            self.kg_config.get("num_edges_per_answer_cutoff", 1_000_000)
        self.edge_predicate_property = self.kg_config["labels"]["edges"]
        self.categories_property = self.kg_config["labels"]["nodes"]
        zip_properties = {property_name for zip_info \
                          in self.kg_config.get("zip", {}).values()
             for property_name in zip_info["properties"]}
        self.array_properties = \
            zip_properties.union(set(self.kg_config.get("other_array_properties", [])))
        self.graph_qualified_predicate_property = "qualified_predicate"
        self.graph_object_direction_property = "object_direction_qualifier"
        self.graph_object_aspect_property = "object_aspect_qualifier"
        self.qedge_qualified_predicate_property = \
            f"biolink:{self.graph_qualified_predicate_property}"
        self.qedge_object_direction_property = \
            f"biolink:{self.graph_object_direction_property}"
        self.qedge_object_aspect_property = f"biolink:{self.graph_object_aspect_property}"
        self.bh = get_biolink_helper(self.biolink_version)
        self.non_biolink_item_id = 9999
        self.category_map: dict[str, int] = {}  # Maps category english name --> int ID
        # Maps category int ID --> english name:
        self.category_map_reversed: dict[int, str] = {}
        self.predicate_map: dict[str, int] = {}  # Maps predicate english name --> int ID
        # Maps predicate int ID --> english name:
        self.predicate_map_reversed: dict[int, str] = {}
        self.node_lookup_map: dict[str, dict[str, Any]] = {}
        self.edge_lookup_map: dict[str, dict[str, Any]] = {}
        self.main_index: dict[str, dict] = {}
        self.subclass_index: dict[str, set[str]] = {}
        self.conglomerate_predicate_descendant_index: dict[str, set[str]] = defaultdict(set)
        self.meta_kg: dict[str, dict[str, dict[str, list[str]]]|list[dict[str, Any]]] = {}
        self.preferred_id_map: dict[str, str] = {}
        self.supported_qualifiers = \
            {self.qedge_qualified_predicate_property, self.qedge_object_direction_property,
             self.qedge_object_aspect_property}
        self.core_node_properties = {"name", self.categories_property}
        self.core_edge_properties = \
            {"subject", "object", "predicate", "primary_knowledge_source",
             "source_record_urls",
             self.graph_qualified_predicate_property, self.graph_object_direction_property,
                                     self.graph_object_aspect_property}
        self.trial_phases_map = \
            {0: "not_provided", 0.5: "pre_clinical_research_phase",
             1: "clinical_trial_phase_1", 2: "clinical_trial_phase_2",
             3: "clinical_trial_phase_3", 4: "clinical_trial_phase_4",
             1.5: "clinical_trial_phase_1_to_2", 2.5: "clinical_trial_phase_2_to_3"}
        self.trial_phases_map_reversed = _reverse_dictionary(self.trial_phases_map)
        self.trial_phase_properties: set[str] = \
            {property_name for property_name, attribute_shell \
             in self.trapi_attribute_map.items()
             if attribute_shell.get("value_type_id", "") == "biolink:MaxResearchPhaseEnum"}
        self.knowledge_source_properties = \
            {"knowledge_source", "primary_knowledge_source",
             "aggregator_knowledge_source", "supporting_data_source"}
        self.kp_infores_curie = self.kg_config["kp_infores_curie"]
        self.edge_sources = self._load_edge_sources(self.kg_config)
        self.array_delimiter = self.kg_config.get("array_delimiter", ",")
        self.query_log: list[dict[str, Any]] = []

    # ---------------------------- INDEX BUILDING METHODS ----------------------------- #

    def build_indexes(self) -> None:
        logging.info("Starting to build indexes for endpoint %s", self.endpoint_name)
        start = time.time()
        # Create a subdirectory to store pickles of indexes in
        os.makedirs(self.indexes_dir_path, exist_ok=True)

        nodes_file_or_url, edges_file_or_url = self._get_file_names_to_use()
        download_nodes: bool = _is_url(nodes_file_or_url)
        nodes_file: str
        if download_nodes:
            nodes_file = _url_basename(nodes_file_or_url)
        else:
            nodes_file = nodes_file_or_url
        edges_file: str
        download_edges: bool = _is_url(edges_file_or_url)
        if download_edges:
            edges_file = _url_basename(edges_file_or_url)
        else:
            edges_file = edges_file_or_url

        parent_dir = self.parent_dir
        if _is_basename(nodes_file):
            nodes_path = os.path.abspath(os.path.join(parent_dir, nodes_file))
        else:
            nodes_path = nodes_file
        if _is_basename(edges_file):
            edges_path = os.path.abspath(os.path.join(parent_dir, edges_file))
        else:
            edges_path = edges_file

        kg_config = self.kg_config
        debug = self.debug

        if debug:
            # sample a node/edge (for size estim.) every `debug_sample_per` nodes/edges
            debug_sample_per = 100

        subclass_edges_path: Optional[str] = None
        if kg_config.get("remote_subclass_edges_file_url"):
            logging.info("No subclass_of edges detected in the graph. "
                         "Will download some based on kg_config.")
            subclass_edges_remote_file_url = kg_config["remote_subclass_edges_file_url"]
            assert _is_url(subclass_edges_remote_file_url), \
                "Subclass edges remote file URL from config file is not a URL: " \
                f"{subclass_edges_remote_file_url}"
            subclass_edges_file = _url_basename(subclass_edges_remote_file_url)
            subclass_edges_path = os.path.join(parent_dir,
                                               subclass_edges_file)
            download_subclass_edges = True
        else:
            download_subclass_edges = False

        # download any required remote files up-front, so we can fail early if
        # one of the URLs is incorrect or download is failing for some reason
        if download_nodes:
            _download_remote_file(nodes_file_or_url, nodes_path)

        if download_edges:
            _download_remote_file(edges_file_or_url, edges_path)

        if download_subclass_edges:
            assert isinstance(subclass_edges_path, str), \
                f"invalid type for subclass_edges_path: {type(subclass_edges_path)}"
            _download_remote_file(subclass_edges_remote_file_url, subclass_edges_path)

        # Load the files into a KG, depending on file type
        logging.info("Streaming edges from file %s", edges_path)
        edges_gen = _iter_records(edges_path, self.array_properties, self.array_delimiter)

        # Precompute zip config into a convenient structure
        zip_prop_map = kg_config.get("zip") or {}
        zipped_specs: list[tuple[str, list[str]]] = []
        zip_prop_owner: dict[str, str] = {}
        for zipped_prop_name, info in zip_prop_map.items():
            props = info.get("properties") or []
            if not props:
                continue
            for p in props:
                if p in zip_prop_owner:
                    raise ValueError(f"two zip specs, {zipped_prop_name} and "
                                     f"{zip_prop_owner[p]}, reference the same "
                                     f"property: {p}")
                zip_prop_owner[p] = zipped_prop_name
            zipped_specs.append((zipped_prop_name, props))

        is_empty = _is_empty

        # Create basic node lookup map
        logging.info("Streaming nodes from file %s", nodes_path)
        nodes_gen = _iter_records(nodes_path, self.array_properties, self.array_delimiter)
        logging.info("Building basic node/edge lookup maps")
        logging.info("Loading node lookup map")
        node_to_category_labels_map: dict[str, set[int]] = {}
        node_lookup_map: dict[str, dict[str, Any]] = {}
        node_properties_to_ignore = kg_config.get("ignore_node_properties", [])
        convert_input_ids = kg_config.get("convert_input_ids")
        preferred_id_map = self.preferred_id_map
        categories_property = self.categories_property
        biolink_helper = self.bh
        get_category_id = self._get_category_id
        node_ctr = 0
        start_nodes = time.time()
        drug_chemical_conflation = kg_config.get("drug_chemical_conflation", False)
        node_id_batch: list[str] = []
        batch_size = 1_000  # suggested max batch size
        equivalent_ids_in_graph = False
        node_sizes_total: dict[str,int] = defaultdict(int)
        for node in nodes_gen:
            node_id = cast(str, node['id'])

            # Remove node properties we don't care about (according to config file)
            for prop_to_ignore in node_properties_to_ignore:
                node.pop(prop_to_ignore, None)

            # Record equivalent identifiers (if provided) for each node so we
            # can 'canonicalize' incoming queries
            if self.kg_config.get("convert_input_ids"):
                equivalent_ids = {
                    curie
                    for p in equivalent_curies_property_tuple
                    for curie in node.get(p, [])
                }
                if equivalent_ids:
                    equivalent_ids_in_graph = True
                    for equiv_id in equivalent_ids:
                        preferred_id_map[equiv_id] = node_id

                    # Then delete no-longer-needed equiv IDs property (these can be
                    # huge, faster streaming without)
                    for k in equivalent_curies_property_tuple:
                        node.pop(k, None)

            node.pop("id", None)  # Don't need this anymore since it's now the key

            # Build a helper map of nodes --> category labels
            categories = _convert_to_set(node[categories_property])
            proper_ancestors_for_each_category = \
                [set(biolink_helper
                     .get_ancestors(category, include_mixins=False,
                                    include_conflations=False)).difference({category})
                 for category in categories]
            all_proper_ancestors = set().union(*proper_ancestors_for_each_category)
            most_specific_categories = categories.difference(all_proper_ancestors)
            node_to_category_labels_map[node_id] = \
                {get_category_id(category_name)
                 for category_name in most_specific_categories}
            node_lookup_map[node_id] = node

            # if config file specifies to normalize input IDs, and if the graph
            # didn't already supply equivalent node IDs, use the SRI node normalizer
            # to normalize the nodes in batches
            if convert_input_ids and not equivalent_ids_in_graph:
                if len(node_id_batch) == batch_size:
                    equiv_id_map_for_batch = \
                        _get_equiv_id_map_from_sri(node_id_batch,
                                                   drug_chemical_conflation)
                    preferred_id_map.update(equiv_id_map_for_batch)
                    node_id_batch = []
                node_id_batch.append(node_id)

            node_ctr += 1

            if debug:
                if node_ctr % debug_sample_per == 0:
                    node_sizes = _sizeof_dict_entries(node)
                    for k, c in node_sizes.items():
                        node_sizes_total[k] += c

            if node_ctr % 1_000_000 == 0:
                logging.info(*_format_memory_usage("  Processed %s nodes in %s seconds. ",
                                                   f"{node_ctr:,}",
                                                   round(time.time() - start_nodes, 1)))

        if debug:
            _pprint_sizes_mb(node_sizes_total, multiplier=float(debug_sample_per))

        logging.info(*_format_memory_usage("Have loaded %s nodes in %s seconds. ",
                                           format(len(node_to_category_labels_map), ","),
                                           round(time.time() - start_nodes, 1)))

        logging.info("Preferred ID map includes %s equivalent identifiers",
                     len(preferred_id_map))

        # Add a build node for this Plover build (don't want this in the meta KG,
        # so we add it here)
        plover_build_node = \
            {"name": f"Plover deployment of {self.kp_infores_curie}",
             "category": "biolink:InformationContentEntity",
             "description": f"This Plover build was done on {datetime.now()} "
             "from input files "
             f"'{kg_config['nodes_file']}' and '{kg_config['edges_file']}'. "
             f"Biolink version used was {self.biolink_version}."}
        node_lookup_map["PloverDB"] = plover_build_node

         # Save the node lookup map now that we're done using/modifying it
        _save_to_pickle_file(node_lookup_map,
                             os.path.join(self.indexes_dir_path,
                                          "node_lookup_map.pkl"))
        del node_lookup_map
        gc.collect()  # Make sure we free up any memory we can
        logging.info(*_format_memory_usage("Have deleted the node_lookup_map "
                                           "and run garbage collection. "))
        if debug:
            _print_top_objects(min_mb=100)

        graph_object_direction_property = self.graph_object_direction_property
        graph_object_aspect_property = self.graph_object_aspect_property
        trial_phase_properties: set[str] = self.trial_phase_properties
        core_edge_properties = self.core_edge_properties
        edge_properties_to_ignore = kg_config.get("ignore_edge_properties") or []
        convert_trial_phase_to_enum = self._convert_trial_phase_to_enum
        edge_lookup_map: dict[str, dict[str, Any]] = {}
        edge_predicate_property = self.edge_predicate_property
        graph_qualified_predicate_property = self.graph_qualified_predicate_property
        edge_ctr = 0
        start_edges = time.time()
        edge_sizes_total: dict[str,int] = defaultdict(int)
        normalize = kg_config.get("normalize")
        meta_triples_map: dict[tuple[int, str, int], set[str]] = defaultdict(set)
        meta_qual_map: dict[tuple[int, str, int], dict[str, set[str]]] = \
            defaultdict(lambda: defaultdict(set))
        test_triples_map = {}
        qedge_qual_pred_prop = self.qedge_qualified_predicate_property
        qedge_obj_dir_prop = self.qedge_object_direction_property
        qedge_obj_aspect_prop = self.qedge_object_aspect_property

        # Create reversed category/predicate maps now that we're done building those maps
        self.category_map_reversed = _reverse_dictionary(self.category_map)

        logging.info("Pickling category_map and deleting it from memory")
        # Save regular category/predicate maps now that we're done using those
        _save_to_pickle_file(self.category_map,
                             os.path.join(self.indexes_dir_path, "category_map.pkl"))
        del self.category_map

        category_map_reversed = self.category_map_reversed

        for edge in edges_gen:
            try:
                edge_id = str(edge["id"])
            except KeyError as e:
                raise KeyError(f"edge missing required 'id' field in {edges_path}") from e

            # remove edge properties that are on the "ignore" list from the config file
            for prop_to_ignore in edge_properties_to_ignore:
                edge.pop(prop_to_ignore, None)

            # Correct qualified property names (this is really for KG2)
            if "qualified_object_direction" in edge:
                edge[graph_object_direction_property] = \
                    edge.pop("qualified_object_direction")
            if "qualified_object_aspect" in edge:
                edge[graph_object_aspect_property] = edge.pop("qualified_object_aspect")

             # ---- Zip up specified columns into list-of-dicts ----
            for zipped_prop_name, props in zipped_specs:
                # Get the column arrays; if any are missing, skip or raise (choose behavior)
                try:
                    cols = [edge[p] for p in props]
                except KeyError as e:
                    raise KeyError(f"for edge {edge_id}, missing zip column "
                                   f"{e.args[0]} \for {zipped_prop_name}") from e
                # Zip rows (assumes cols are equal-length sequences)
                for prop, col in zip(props, cols):
                    if isinstance(col, (str, bytes, dict, set)) or \
                       not isinstance(col, Sequence):
                        raise TypeError(f"for edge {edge_id}, zip column {prop} is "
                                        f"{type(col).__name__}; expected Sequence "
                                        "(non-string)")
                items: list[dict[str, Any]] = []
                try:
                    for row in zip(*cols, strict=True):
                        obj = dict(zip(props, row))
                        # Clean empties + trial phase conversion
                        for nested_name in list(obj.keys()):
                            v = obj[nested_name]
                            if is_empty(v):
                                del obj[nested_name]
                                continue
                            if nested_name in trial_phase_properties:
                                obj[nested_name] = convert_trial_phase_to_enum(v)
                        # Optionally skip empty objects entirely
                        if obj:
                            items.append(obj)
                except ValueError as e:
                    raise ValueError(f"for edge {edge_id}, zip length mismatch for "
                                     f"{zipped_prop_name} in {edges_path}") from e
                edge[zipped_prop_name] = items
                for p in props:
                    edge.pop(p, None)

            # delete any remaining top-level properties that are empty
            to_del = [k for k, v in edge.items() if is_empty(v)]
            for k in to_del:
                edge.pop(k, None)

            # Convert any trial phase property values from int to Biolink enum
            for trial_phase_prop in trial_phase_properties:
                if trial_phase_prop in edge:
                    edge[trial_phase_prop] = \
                        convert_trial_phase_to_enum(edge[trial_phase_prop])

            # Convert all edge to its canonical predicate form; correct missing biolink
            # prefixes
            predicate = edge[edge_predicate_property]
            qualified_predicate = edge.get(graph_qualified_predicate_property)
            canonical_predicate = \
                biolink_helper.get_canonical_predicates(predicate, print_warnings=False)[0]
            canonical_qualified_predicate = \
                biolink_helper.get_canonical_predicates(qualified_predicate,
                                                        print_warnings=False)[0] \
                                                        if qualified_predicate else None
            predicate_is_canonical = canonical_predicate == predicate
            qualified_predicate_is_canonical = canonical_qualified_predicate == qualified_predicate
            if qualified_predicate and \
                    ((predicate_is_canonical and not qualified_predicate_is_canonical) or
                     (not predicate_is_canonical and qualified_predicate_is_canonical)):
                logging.error("Edge %s has one of [predicate, qualified_predicate] that is "
                              "in canonical form and one that is not; cannot reconcile",
                              edge_id)
                return  # TODO: look into whether we should raise an exception here
            # Both predicate and qualified_pred must be non-canonical:
            if canonical_predicate != predicate:
                # Flip the edge (because the original predicate must be the canonical
                # predicate's inverse)
                edge[edge_predicate_property] = canonical_predicate
                edge[graph_qualified_predicate_property] = canonical_qualified_predicate
                original_subject = edge["subject"]
                edge["subject"] = edge["object"]
                edge["object"] = original_subject

            add_edge = None

            if normalize:
                edge["subject"] = preferred_id_map[edge["subject"]]
                edge["object"] = preferred_id_map[edge["object"]]
                edge_id = (f'{edge["subject"]}--{edge["predicate"]}--{edge["object"]}--'
                           f'{edge.get("primary_knowledge_source", "")}')
                edge["id"] = edge_id
                if edge.get("supporting_studies"):
                    study_objs_by_nctids = {study_obj["nctid"]: study_obj
                                            for study_obj in edge["supporting_studies"]}
                    edge["supporting_studies"] = list(study_objs_by_nctids.values())
                if edge_id in edge_lookup_map:
                    # Add this edge's array properties to the existing merged edge
                    merged_edge = edge_lookup_map[edge_id]
                    for property_name, value in edge.items():
                        if property_name in merged_edge:
                            if isinstance(value, list):
                                merged_edge[property_name] = \
                                    merged_edge[property_name] + value
                        else:
                            merged_edge[property_name] = value
                    add_edge = False
                else:
                    add_edge = True

            subj_categories = node_to_category_labels_map[edge["subject"]]
            obj_categories = node_to_category_labels_map[edge["object"]]
            edge_attribute_names = {k for k in edge if k not in core_edge_properties}
            qualified_predicate = edge.get(graph_qualified_predicate_property)
            object_dir_qualifier = edge.get(graph_object_direction_property)
            object_aspect_qual = edge.get(graph_object_aspect_property)
            for subj_category in subj_categories:
                for obj_category in obj_categories:
                    meta_triple = \
                        (subj_category, cast(str, edge["predicate"]), obj_category)
                    meta_triples_map[meta_triple].update(edge_attribute_names)
                    if qualified_predicate:
                        meta_qual_map[meta_triple][qedge_qual_pred_prop].add(qualified_predicate)
                    if object_dir_qualifier:
                        meta_qual_map[meta_triple][qedge_obj_dir_prop].add(object_dir_qualifier)
                    if object_aspect_qual:
                        meta_qual_map[meta_triple][qedge_obj_aspect_prop].add(object_aspect_qual)
                    # Create one test triple for each meta edge (basically an example edge)
                    if meta_triple not in test_triples_map:
                        test_triples_map[meta_triple] = \
                            {"subject_category": category_map_reversed[subj_category],
                             "object_category": category_map_reversed[obj_category],
                             "predicate": edge["predicate"],
                             "subject_id": edge["subject"],
                             "object_id": edge["object"]}

            # store the final edge in the `edge_lookup_map` by its `edge_id` key
            if (not normalize) or add_edge:
                edge_lookup_map[edge_id] = edge

            edge_ctr += 1
            if edge_ctr % 1_000_000 == 0:
                logging.info(
                    *_format_memory_usage("  Processed %s edges in %s seconds. ",
                                          f"{edge_ctr:,}",
                                          round(time.time() - start_edges, 1)))

            if debug:
                if edge_ctr % debug_sample_per == 0:
                    edge_sizes = _sizeof_dict_entries(edge)
                    for k, c in edge_sizes.items():
                        edge_sizes_total[k] += c

        if debug:
            _pprint_sizes_mb(edge_sizes_total, multiplier=float(debug_sample_per))

        if debug:
            _print_top_objects(min_mb=100)

        logging.info("Have loaded %s edges in %s seconds", format(edge_ctr, ","),
                     round(time.time() - start_edges, 1))

        if self.is_test:
            # Narrow down our test file to exclude orphan edges
            logging.info("Narrowing down test edges file to make sure node "
                         "IDs used by edges appear in nodes dict")
            edge_lookup_map = {edge_id: edge for edge_id, edge in edge_lookup_map.items() if
                               edge["subject"] in node_to_category_labels_map and \
                               edge["object"] in node_to_category_labels_map}
            logging.info("After narrowing down test file, node_lookup_map contains %s nodes, "
                         "edge_lookup_map contains %s edges",
                         len(node_to_category_labels_map), len(edge_lookup_map))

        # Build the meta knowledge graph and SRI test triples
        logging.info("Starting to build meta knowledge graph and SRI test triples")
        get_trapi_edge_attribute=self._get_trapi_edge_attribute
        meta_edges = [{"subject": category_map_reversed[triple[0]],
                       "predicate": triple[1],
                       "object": category_map_reversed[triple[2]],
                       "attributes": [{"attribute_type_id": \
                                       get_trapi_edge_attribute(attribute_name, None, {})[
                                           "attribute_type_id"],
                                       "constraint_use": True,
                                       # TODO: Do this for real: vvvv
                                       "constraint_name": attribute_name.replace("_", " ")}  
                                       # TODO: Do this for real: ^^^^
                                      for attribute_name in attribute_names],
                       "qualifiers": [{"qualifier_type_id": qualifier_property,
                                       "applicable_values": list(qualifier_values)}
                                      for qualifier_property, qualifier_values \
                                      in meta_qual_map[triple].items()]}
                      for triple, attribute_names in meta_triples_map.items()]
        logging.info("Identified %s different meta edges", len(meta_edges))
        # Then construct meta nodes
        category_to_prefixes_map = defaultdict(set)
        for node_key, categories_int in node_to_category_labels_map.items():
            prefix = node_key.split(":")[0]
            for category in categories_int:
                category_to_prefixes_map[category].add(prefix)
        meta_nodes = {category_map_reversed[category]: {"id_prefixes": list(prefixes)}
                      for category, prefixes in category_to_prefixes_map.items()}
        logging.info("Identified %s different meta nodes", len(meta_nodes))
        self.meta_kg = {"nodes": meta_nodes, "edges": meta_edges}
        _save_to_pickle_file(self.meta_kg,
                             os.path.join(self.indexes_dir_path, "meta_kg.pkl"))
        del self.meta_kg, meta_nodes, meta_edges
        gc.collect()
        logging.info(*_format_memory_usage("Have deleted the meta maps and run garbage "
                                           "collection. "))

        get_conglomerate_predicate_id_from_edge = self._get_conglomerate_predicate_id_from_edge
        # Build our main index (modified/nested adjacency list kind of structure)
        logging.info("Building main index")
        main_index = self.main_index
        edge_ctr = 0
        qualified_edges_count = 0
        total = len(edge_lookup_map)
        max_allowed_percent_memory_usage = 90
        get_predicate_id = self._get_predicate_id
        for edge_id, edge in edge_lookup_map.items():
            subject_id = edge["subject"]
            object_id = edge["object"]
            predicate = edge[edge_predicate_property]
            # add `predicate` to the `self.predicate_map` as a key, with the value
            # being a sequentially- and automatically-assigned integer predicate ID:
            predicate_id = get_predicate_id(predicate)
            subject_category_ids = node_to_category_labels_map[subject_id]
            object_category_ids = node_to_category_labels_map[object_id]
            # Record this edge in the forwards and backwards directions
            _add_edge_to_main_index_bidir(main_index,
                                          subject_id,
                                          object_id,
                                          subject_category_ids,
                                          object_category_ids,
                                          predicate_id,
                                          edge_id)
            # Record this edge under its qualified predicate/other properties, if such info is
            # provided
            if edge.get(graph_qualified_predicate_property) or \
               edge.get(graph_object_direction_property) or \
               edge.get(graph_object_aspect_property):
                conglomerate_predicate_id = get_conglomerate_predicate_id_from_edge(edge)
                _add_edge_to_main_index_bidir(main_index,
                                              subject_id,
                                              object_id,
                                              subject_category_ids,
                                              object_category_ids,
                                              conglomerate_predicate_id,
                                              edge_id)
                qualified_edges_count += 1
            edge_ctr += 1
            if edge_ctr % 1_000_000 == 0:
                memory_args = _format_memory_usage("  Processed %s edges (%s%%), "
                                                   "%s of which were qualified edges. ",
                                                   edge_ctr,
                                                   round((edge_ctr / total) * 100),
                                                   qualified_edges_count)
                logging.info(*memory_args)
                memory_usage_percent = memory_args[5]
                if memory_usage_percent > max_allowed_percent_memory_usage:
                    raise MemoryError(f"Memory usage percent ({memory_usage_percent}%) "
                                      f"is greater than {max_allowed_percent_memory_usage}%;"
                                      " terminating.")

        logging.info("Done building main index; there were %s edges, %s of which "
                     "were qualified.",
                     edge_ctr, qualified_edges_count)
        _save_to_pickle_file(self.main_index, os.path.join(self.indexes_dir_path,
                                                           "main_index.pkl"))
        del self.main_index, main_index, node_to_category_labels_map
        gc.collect()  # Make sure we free up any memory we can
        logging.info(*_format_memory_usage(
            message=(
                "Have deleted the main_index and just ran "
                "garbage collection. "
            )
        ))

        logging.info("Constructing predicate_map_reversed from predicate_map")
        self.predicate_map_reversed = _reverse_dictionary(self.predicate_map)
        logging.info("Pickling predicate_map_reversed and deleting it from memory")
        _save_to_pickle_file(self.predicate_map_reversed,
                             os.path.join(self.indexes_dir_path, "predicate_map_reversed.pkl"))
        del self.predicate_map_reversed

        logging.info("Pickling predicate_map and deleting it from memory")
        _save_to_pickle_file(self.predicate_map,
                             os.path.join(self.indexes_dir_path, "predicate_map.pkl"))
        del self.predicate_map

        logging.info("Pickling category_map_reversed and deleting it from memory")
        # Save some other indexes we're done using/modifying
        _save_to_pickle_file(self.category_map_reversed,
                             os.path.join(self.indexes_dir_path, "category_map_reversed.pkl"))
        del self.category_map_reversed

        logging.info("Starting call to _build_conglomerate_predicate_descendant_index")
        # Record each conglomerate predicate in the KG under its ancestors
        self._build_conglomerate_predicate_descendant_index(edge_lookup_map)
        logging.info("Saving conglomerate_predicate_descendant_index")
        _save_to_pickle_file(self.conglomerate_predicate_descendant_index,
                             os.path.join(self.indexes_dir_path,
                                          "conglomerate_predicate_descendant_index.pkl"))
        del self.conglomerate_predicate_descendant_index

        # Build the subclass_of index
        logging.info("Getting subclass edges")
        subclass_edges = self._get_subclass_edges(subclass_edges_path, edge_lookup_map)
        logging.info("Building index of subclass edges")
        self._build_subclass_index(subclass_edges, len(edge_lookup_map))
        del subclass_edges

        logging.info("Saving index of subclass edges")
        _save_to_pickle_file(self.subclass_index,
                             os.path.join(self.indexes_dir_path, "subclass_index.pkl"))
        del self.subclass_index

        logging.info("Saving edge_lookup_map")
        # Save the edge lookup map now that we're done with it
        _save_to_pickle_file(edge_lookup_map,
                             os.path.join(self.indexes_dir_path,
                                          "edge_lookup_map.pkl"))
        del edge_lookup_map
        gc.collect()  # Make sure we free up any memory we can
        logging.info(*_format_memory_usage(message="Have just run garbage collection. "))

        logging.info("Saving preferred_id_map")
        # Save the preferred ID map now that we're done using it
        _save_to_pickle_file(self.preferred_id_map,
                             os.path.join(self.indexes_dir_path, "preferred_id_map.pkl"))
        del self.preferred_id_map

        # Then save test triples file
        test_triples_dict = {"edges": list(test_triples_map.values())}
        logging.info("Saving test triples file to %s; includes "
                     "%s test triples",
                     self.sri_test_triples_path, len(test_triples_dict['edges']))
        with open(self.sri_test_triples_path, "w+", encoding="utf-8") as test_triples_file:
            json.dump(test_triples_dict, test_triples_file)
        del test_triples_dict

        # Fill out the home page HTML template for this KP with the proper KP endpoint/infores
        # curie
        logging.info("Filling out html home template and saving to %s",
                     self.kp_home_html_path)
        kp_home_template_path = os.path.join(parent_dir, "kp_home_template.html")
        with open(kp_home_template_path, "r", encoding="utf-8") as template_file:
            html_string = template_file.read()
        revised_html = html_string.replace("{{kp_infores_curie}}",
                                           self.kp_infores_curie).replace("{{kp_endpoint_name}}",
                                                                          self.endpoint_name)
        with open(self.kp_home_html_path, "w+", encoding="utf-8") as kp_home_file:
            kp_home_file.write(revised_html)

        if not self.is_test:
            logging.info("Removing local files from the image now that index building is done")
            subprocess.call(["rm", "-f", nodes_path])
            subprocess.call(["rm", "-f", edges_path])

        logging.info("Done building indexes! Took %s minutes.",
                     round((time.time() - start) / 60, 2))

    def load_indexes(self):
        logging.info("Starting to load indexes for endpoint %s",
                     self.endpoint_name)
        logging.info("Checking whether index subdirectory (%s) already exists",
                     self.indexes_dir_path)
        if not os.path.exists(self.indexes_dir_path):
            logging.info("No pickle indexes exist - will build indexes")
            self.build_indexes()

        # Load our pickled indexes into memory
        logging.info("Loading indexes from %s (in parallel)",
                     self.indexes_dir_path)
        start = time.time()

        self.node_lookup_map = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                              "node_lookup_map.pkl"))
        self.edge_lookup_map = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                              "edge_lookup_map.pkl"))
        self.main_index = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                         "main_index.pkl"))
        self.subclass_index = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                             "subclass_index.pkl"))
        self.predicate_map = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                            "predicate_map.pkl"))
        self.predicate_map_reversed = \
            _load_pickle_file(os.path.join(self.indexes_dir_path,
                                           "predicate_map_reversed.pkl"))
        self.category_map = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                           "category_map.pkl"))
        self.category_map_reversed = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                                    "category_map_reversed.pkl"))
        self.conglomerate_predicate_descendant_index = \
            _load_pickle_file(os.path.join(self.indexes_dir_path,
                                           "conglomerate_predicate_descendant_index.pkl"))
        self.meta_kg = _load_pickle_file(os.path.join(self.indexes_dir_path, "meta_kg.pkl"))
        self.preferred_id_map = _load_pickle_file(os.path.join(self.indexes_dir_path,
                                                               "preferred_id_map.pkl"))
        logging.info("Indexes are fully loaded! Took %s minutes.",
                     round((time.time() - start) / 60, 2))

    def load_trapi_attribute_map(self) -> dict[str, Any]:
        # First load the default TRAPI attributes template into map form
        trapi_attribute_template_path = os.path.join(self.parent_dir,
                                                     "trapi_attribute_template.json")
        with open(trapi_attribute_template_path, "r", encoding="utf-8") \
             as attribute_template_file:
            attribute_templates = json.load(attribute_template_file)
        trapi_attribute_map = {}
        for item in attribute_templates:
            for property_name in item["property_names"]:
                if property_name in trapi_attribute_map:
                    logging.error("More than one item in trapi_attribute_template.json uses the "
                                  "same property_name: '%s'! Not allowed.",
                                  property_name)
                    raise ValueError()
                trapi_attribute_map[property_name] = item["attribute_shell"]

        # Then override defaults with any attribute shells provided in the config file
        if self.kg_config.get("trapi_attribute_map"):
            logging.info("Updating default TRAPI attribute map with config file TRAPI attribute "
                         "map")
            trapi_attribute_map.update(self.kg_config["trapi_attribute_map"])

        return trapi_attribute_map

    def _get_conglomerate_predicate_from_edge(self, edge: dict) -> str:
        qualified_predicate = edge.get(self.graph_qualified_predicate_property)
        object_direction = edge.get(self.graph_object_direction_property)
        object_aspect = edge.get(self.graph_object_aspect_property)
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
    def _get_conglomerate_predicate(
            qualified_predicate: Optional[str],
            predicate: Optional[str],
            object_direction: Optional[str],
            object_aspect: Optional[str]
    ) -> str:
        # If no qualified predicate is provided, use the regular unqualified predicate
        predicate_to_use = qualified_predicate if qualified_predicate else predicate
        return f"{predicate_to_use}--{object_direction}--{object_aspect}"

    def _get_category_id(self, category_name: str) -> int:
        if category_name not in self.category_map:
            num_categories = len(self.category_map)
            self.category_map[category_name] = num_categories
        return self.category_map[category_name]

    def _build_conglomerate_predicate_descendant_index(
            self,
            edge_lookup_map: \
            dict[str, dict[str, Any]]
    ) -> None:
        # Record each conglomerate predicate in the KG under its ancestors (inc. None and regular
        # predicate variations)
        logging.info("Building conglomerate qualified predicate descendant index..")
        conglomerate_predicates_already_seen = set()
        for edge in edge_lookup_map.values():
            conglomerate_pred = self._get_conglomerate_predicate_from_edge(edge)
            qualified_predicate = edge.get(self.graph_qualified_predicate_property)
            qualified_obj_direction = edge.get(self.graph_object_direction_property)
            qualified_obj_aspect = edge.get(self.graph_object_aspect_property)
            if (qualified_predicate or qualified_obj_direction or qualified_obj_aspect) \
               and conglomerate_pred not in conglomerate_predicates_already_seen:
                predicate_variations = \
                    [qualified_predicate, edge.get(self.edge_predicate_property)]
                for predicate in predicate_variations:
                    predicate_ancestors = set(self.bh.get_ancestors(predicate)).union({None})
                    direction_ancestors = \
                        set(self.bh.get_ancestors(qualified_obj_direction)).union({None})
                    aspect_ancestors = \
                        set(self.bh.get_ancestors(qualified_obj_aspect)).union({None})
                    ancestor_combinations = \
                        set(itertools.product(predicate_ancestors,
                                              direction_ancestors,
                                              aspect_ancestors))
                    ancestor_conglomerate_predicates = \
                        {f"{combination[0]}--{combination[1]}--{combination[2]}"
                         for combination in ancestor_combinations}.difference({"None--None--None"})
                    for ancest in ancestor_conglomerate_predicates:
                        self.conglomerate_predicate_descendant_index[ancest].add(conglomerate_pred)
                conglomerate_predicates_already_seen.add(conglomerate_pred)

    def _get_subclass_edges(
            self,
            subclass_edges_path: Optional[str],
            edge_lookup_map: dict[str, dict[str, Any]]
    ) -> list[dict]:
        subclass_predicates = {"biolink:subclass_of", "biolink:superclass_of"}
        subclass_edges = [edge for edge in edge_lookup_map.values()
                          if edge[self.edge_predicate_property] in subclass_predicates]
        if subclass_edges:
            logging.info("Found %s subclass_of edges in the graph. Will use these for concept "
                         "subclass reasoning",
                         len(subclass_edges))
        else:
            if subclass_edges_path:
                logging.info("Loading subclass edges from %s and filtering out those not "
                             "involving our nodes",
                             subclass_edges_path)
                edges_gen = _iter_records(subclass_edges_path, set(), self.array_delimiter)
                    # TODO: Make smarter... need to be connected, not necessarily directly?
                    # and add to preferred id map?
                subclass_edges = [edge_obj for edge_obj in edges_gen
                                  if edge_obj["subject"] in self.preferred_id_map
                                  and edge_obj["object"] in self.preferred_id_map]
                logging.info("Identified %s subclass edges linking to equivalent IDs of our nodes",
                             len(subclass_edges))
                logging.info("Remapping those edges to use our preferred identifiers")
                for edge in subclass_edges:
                    edge["subject"] = self.preferred_id_map[edge["subject"]]
                    edge["object"] = self.preferred_id_map[edge["object"]]
                subprocess.call(["rm", "-f", subclass_edges_path])
            else:
                logging.warning("No url to a subclass edges file provided in %s. Will proceed "
                                "without subclass concept reasoning",
                                self.config_file_name)

        if self.kg_config.get("subclass_sources"):
            subclass_sources = set(self.kg_config["subclass_sources"])
            logging.info("Filtering subclass edges to only those from sources specified in kg "
                         "config: %s",
                         subclass_sources)
            subclass_edges = [edge for edge in subclass_edges
                              if edge.get("primary_knowledge_source") in subclass_sources]

        # Deduplicate subclass edges (now primary source doesn't matter since we've already
        # filtered on that)
        logging.info("Deduplicating subclass edges based on triples..")
        deduplicated_subclass_edges_map = \
            {f"{edge['subject']}--{edge['predicate']}--{edge['object']}": edge
             for edge in subclass_edges}
        subclass_edges = list(deduplicated_subclass_edges_map.values())
        logging.info("In the end, have %s subclass triples to base concept subclass reasoning on",
                     len(subclass_edges))

        return subclass_edges

    def _build_subclass_index(
            self,
            subclass_edges: list[dict],
            total_edges_count: int
    ) -> None:
        logging.info("Building subclass_of index using %s subclass_of edges",
                     len(subclass_edges))
        start = time.time()

        # Build a map of nodes to their direct 'subclass_of' children
        parent_to_child_dict = defaultdict(set)
        for edge in subclass_edges:
            parent_node_id = \
                edge["object"] if edge[self.edge_predicate_property] == \
                "biolink:subclass_of" else edge["subject"]
            child_node_id = \
                edge["subject"] if edge[self.edge_predicate_property] == \
                "biolink:subclass_of" else edge["object"]
            parent_to_child_dict[parent_node_id].add(child_node_id)
        logging.info("A total of %s nodes have child subclasses",
                     len(parent_to_child_dict))

        # Then recursively derive all 'subclass_of' descendants for each node
        if parent_to_child_dict:
            # Need something to act as a parent to all other parents, as a starting point:
            root = "root"
            parent_to_child_dict[root] = set(parent_to_child_dict)
            parent_to_descendants_dict: dict[str, set[str]] = defaultdict(set)
            problem_nodes: set[str] = set()
            _ = _get_descendants(root,
                                 parent_to_child_dict,
                                 parent_to_descendants_dict,
                                 max_depth=0,
                                 problem_nodes=problem_nodes)

            # Filter out some unhelpful nodes (too many descendants and/or not useful)
            del parent_to_descendants_dict["root"]
            node_ids = set(parent_to_descendants_dict)
            for node_id in node_ids:
                if len(parent_to_descendants_dict[node_id]) > 5000 or \
                   node_id.startswith("biolink:"):
                    del parent_to_descendants_dict[node_id]
            deleted_node_ids = node_ids.difference(set(parent_to_descendants_dict))

            self.subclass_index = parent_to_descendants_dict

            # Print out/save some useful stats
            logging.info("Hit recursion depth for %s nodes. Truncated their lineages",
                         len(problem_nodes))
            parent_to_num_descendants = \
                {node_id: len(descendants) for node_id, descendants \
                 in parent_to_descendants_dict.items()}
            descendant_counts = list(parent_to_num_descendants.values())
            prefix_counts: dict[str, int] = defaultdict(int)
            top_50_biggest_parents = \
                sorted(parent_to_num_descendants.items(), key=lambda x: x[1], reverse=True)[:50]
            for node_id in parent_to_descendants_dict:
                prefix = node_id.split(":")[0]
                prefix_counts[prefix] += 1
            sorted_prefix_counts = \
                dict(sorted(prefix_counts.items(), key=lambda count: count[1], reverse=True))
            with open("subclass_report.json", "w+", encoding="utf-8") as report_file:
                report = {"total_edges_in_kg": total_edges_count,
                          "num_subclass_of_edges_from_approved_sources": len(subclass_edges),
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
                              "Diabetes mellitus (MONDO:0005015)": \
                              list(self.subclass_index.get("MONDO:0005015", [])),
                              "Adams-Oliver syndrome (MONDO:0007034)": \
                              list(self.subclass_index.get("MONDO:0007034", []))
                          }
                          }
                json.dump(report, report_file, indent=2)

        logging.info("Building subclass_of index took %s minutes.",
                     round((time.time() - start) / 60, 2))


    def _print_main_index_human_friendly(self):
        counter = 0
        for input_curie, categories_dict in self.main_index.items():
            if counter <= 10:
                print(f"{input_curie}: ##########################################################")
                for category_id, predicates_dict in categories_dict.items():
                    print(f"    {self.category_map_reversed[category_id]}: "
                          "------------------------------")
                    for predicate_id, directions_tuple in predicates_dict.items():
                        print(f"        {self.predicate_map_reversed[predicate_id]}:")
                        for direction_dict in directions_tuple:
                            dir_str = 'Forwards' if directions_tuple.index(direction_dict) == 1 \
                                else 'Backwards'
                            print(f"        {dir_str}:")
                            for output_curie, edge_ids in direction_dict.items():
                                print(f"            {output_curie}:")
                                print(f"                {edge_ids}")
            else:
                break
            counter += 1

    def _convert_trial_phase_to_enum(self, phase_value: Any) -> Any:
        if phase_value in self.trial_phases_map:
            return self.trial_phases_map[phase_value]
        if isinstance(phase_value, str):
            return self.trial_phases_map.get(_load_value(phase_value), phase_value)
        return phase_value

    def _get_equiv_id_map_from_sri(self, node_ids: list[str]) -> dict[str, str]:
        response = requests.post("https://nodenormalization-sri.renci.org/get_normalized_nodes",
                                 json={"curies": node_ids,
                                       "conflate": True,
                                       "drug_chemical_conflate": \
                                       self.kg_config.get("drug_chemical_conflation", False)},
                                 timeout=DEFAULT_TIMEOUT)

        # Preferred IDs for nodes are themselves:
        equiv_id_map = {node_id: node_id for node_id in node_ids}
        if response.status_code == 200:
            for node_id, normalized_info in response.json().items():
                if normalized_info:  # This means the SRI NN recognized the node ID we asked for
                    equiv_nodes = normalized_info["equivalent_identifiers"]
                    for equiv_node in equiv_nodes:
                        equiv_id = equiv_node["identifier"]
                        equiv_id_map[equiv_id] = node_id
        else:
            logging.warning("Request for batch of node IDs sent to SRI NodeNormalizer failed "
                            "(status: %s). Input identifier synonymization may not work properly.",
                            response.status_code)

        return equiv_id_map

    def _load_edge_sources(self, kg_config: dict):
        sources_template = kg_config.get("sources_template")
        if sources_template:
            for sources_shells in sources_template.values():
                for source_shell in sources_shells:
                    source_shell["resource_id"] = \
                        source_shell["resource_id"].replace("{kp_infores_curie}",
                                                            self.kp_infores_curie)
                    if source_shell.get("upstream_resource_ids"):
                        edited_upstream_ids = \
                            [resource_id.replace("{kp_infores_curie}", self.kp_infores_curie)
                             for resource_id in source_shell["upstream_resource_ids"]]
                        source_shell["upstream_resource_ids"] = edited_upstream_ids
        return sources_template

    # ------------------------------ QUERY ANSWERING METHODS --------------------------------- #

    def answer_query(self, trapi_query: dict) -> dict[str, Any]:
        self.query_log = []  # Clear query log of any prior entries
        # Handle case where someone submits only a query graph (not nested in a 'message')
        trapi_query = \
            {"message": {"query_graph": trapi_query}} if "nodes" in trapi_query else trapi_query
        trapi_qg = copy.deepcopy(trapi_query["message"]["query_graph"])
        # Before doing anything else, convert any node ids to equivalents we recognize
        for qnode_key, qnode in trapi_qg["nodes"].items():
            qnode_ids = qnode.get("ids")
            if qnode_ids:
                self.log_trapi("INFO", f"Converting qnode {qnode_key}'s 'ids' to equivalent ids we recognize")
                qnode["ids"] = list({self.preferred_id_map.get(input_id, input_id) for input_id in qnode_ids})

        # Handle single-node queries (not part of TRAPI, but handy)
        if not trapi_qg.get("edges"):
            return self._answer_single_node_query(trapi_qg)
        # Otherwise make sure this is a one-hop query
        if len(trapi_qg["edges"]) > 1:
            err_message = (f"Bad Request. Can only answer single-edge queries. Your QG has "
                           f"{len(trapi_qg['edges'])} edges.")
            self.raise_http_error(400, err_message)
        # Make sure at least one qnode has a curie
        qedge_key = next(qedge_key for qedge_key in trapi_qg["edges"])
        qedge = trapi_qg["edges"][qedge_key]
        subject_qnode_key = qedge["subject"]
        object_qnode_key = qedge["object"]
        subject_qnode = trapi_qg["nodes"][subject_qnode_key]
        object_qnode = trapi_qg["nodes"][object_qnode_key]
        if "ids" not in subject_qnode and "ids" not in object_qnode:
            err_message = "Bad Request. Can only answer queries where at least one QNode has 'ids' specified."
            self.raise_http_error(400, err_message)
        # Make sure there aren't any qualifiers we don't support
        for qualifier_constraint in qedge.get("qualifier_constraints", []):
            for qualifier in qualifier_constraint.get("qualifier_set"):
                if qualifier["qualifier_type_id"] not in self.supported_qualifiers:
                    err_message = (f"Forbidden. Unsupported qedge qualifier encountered: "
                                   f"{qualifier['qualifier_type_id']}. Supported qualifiers are: "
                                   f"{self.supported_qualifiers}")
                    self.raise_http_error(403, err_message)

        # Expand qnode ids to descendant concepts and record original query IDs
        descendant_to_query_id_map: dict[str, dict[str, set[str]]] = \
                                         {subject_qnode_key: defaultdict(set),
                                          object_qnode_key: defaultdict(set)}
        if subject_qnode.get("ids"):
            subject_qnode_curies_with_descendants = []
            subject_qnode_curies = set(subject_qnode["ids"])
            for query_curie in subject_qnode_curies:
                descendants = self._get_descendants(query_curie)
                for descendant in descendants:
                    # We only want to record the mapping in the case of a true descendant
                    if descendant not in subject_qnode_curies:
                        descendant_to_query_id_map[subject_qnode_key][descendant].add(query_curie)
                subject_qnode_curies_with_descendants += descendants
            subject_qnode["ids"] = list(set(subject_qnode_curies_with_descendants))
            log_message = f"After expansion to descendant concepts, subject qnode has {len(subject_qnode['ids'])} ids"
            self.log_trapi("INFO", log_message)
        if object_qnode.get("ids"):
            object_qnode_curies_with_descendants = []
            object_qnode_curies = set(object_qnode["ids"])
            for query_curie in object_qnode_curies:
                descendants = self._get_descendants(query_curie)
                for descendant in descendants:
                    # We only want to record the mapping in the case of a true descendant
                    if descendant not in object_qnode_curies:
                        descendant_to_query_id_map[object_qnode_key][descendant].add(query_curie)
                object_qnode_curies_with_descendants += descendants
            object_qnode["ids"] = list(set(object_qnode_curies_with_descendants))
            log_message = f"After expansion to descendant concepts, object qnode has {len(object_qnode['ids'])} ids"
            self.log_trapi("INFO", log_message)

        # Actually answer the query
        input_qnode_key = self._determine_input_qnode_key(trapi_qg["nodes"])
        output_qnode_key = list(set(trapi_qg["nodes"]).difference({input_qnode_key}))[0]
        self.log_trapi("INFO", "Looking up answers to query..")
        input_qnode_answers, output_qnode_answers, qedge_answers = self._lookup_answers(input_qnode_key,
                                                                                        output_qnode_key,
                                                                                        trapi_qg)

        # Temporarily keeping the 'include_metadata' option to make Plover backwards-compatible for pathfinder
        if trapi_qg.get("include_metadata"):
            # TODO: Delete after Pathfinder is updated for Plover2.0
            self.log_trapi("INFO", f"Done with query, returning {qedge_answers} edges (slim format)")
            return {"nodes": {input_qnode_key: {node_id: self.get_node_as_tuple(node_id) +
                                                (list(descendant_to_query_id_map[input_qnode_key].get(node_id, set())),)
                                                for node_id in input_qnode_answers},
                     output_qnode_key: {node_id: self.get_node_as_tuple(node_id) +
                                        (list(descendant_to_query_id_map[output_qnode_key].get(node_id, set())),)
                                        for node_id in output_qnode_answers}},
                    "edges": {qedge_key: {edge_id: self.get_edge_as_tuple(edge_id) for edge_id in qedge_answers}}}
        if trapi_qg.get("include_metadata") is False:
            # TODO: Delete after Pathfinder is updated for Plover2.0
            self.log_trapi("INFO", f"Done with query, returning {qedge_answers} edges (ids-only format)")
            return {"nodes": {input_qnode_key: list(input_qnode_answers),
                              output_qnode_key: list(output_qnode_answers)},
                    "edges": {qedge_key: list(qedge_answers)}}
        # Form final TRAPI response
        trapi_response = self._create_response_from_answer_ids(input_qnode_answers,
                                                               output_qnode_answers,
                                                               qedge_answers,
                                                               input_qnode_key,
                                                               output_qnode_key,
                                                               qedge_key,
                                                               trapi_query["message"]["query_graph"],
                                                               descendant_to_query_id_map)
        log_message = f"Done with query, returning TRAPI response ({len(trapi_response['message']['results'])} results)"
        self.log_trapi("INFO", log_message)
        return trapi_response

    def get_node_as_tuple(self, node_id: str) -> tuple:
        # TODO: Delete after Pathfinder is updated for Plover2.0
        node = self.node_lookup_map[node_id]
        return node.get("name"), cast(list[str], node.get(self.categories_property))[0]

    def get_edge_as_tuple(self, edge_id: str) -> tuple:
        # TODO: Delete after Pathfinder is updated for Plover2.0
        edge = self.edge_lookup_map[edge_id]
        return (edge["subject"], edge["object"], edge[self.edge_predicate_property],
                edge.get("primary_knowledge_source"), edge.get(self.graph_qualified_predicate_property, ""),
                edge.get(self.graph_object_direction_property, ""), edge.get(self.graph_object_aspect_property, ""),
                "False")  # Silly to have these in strings, but that's the old format... will delete eventually

    def get_edges(self, node_pairs: list[list[str]]) -> dict:
        """
        Finds edges between the specified node pairs. Does *not* currently do concept subclass reasoning.
        """
        # Loop through pairs
        qg_template: dict[str, dict[str, dict[str, Any]]] = \
            {"nodes": {"na": {"ids": []},
                       "nb": {"ids": []}},
             "edges": {"e": {"subject": "na",
                             "object": "nb",
                             "predicates": ["biolink:related_to"]}}}
        node_pairs_to_edge_ids = {}
        all_node_ids = set()
        all_edge_ids = set()
        logging.info("%s: Looking up edges for %s node pairs",
                     self.endpoint_name, len(node_pairs))
        for node_id_a, node_id_b in node_pairs:
            # Convert to equivalent identifiers we recognize
            node_id_a_preferred = self.preferred_id_map.get(node_id_a, node_id_a)
            node_id_b_preferred = self.preferred_id_map.get(node_id_b, node_id_b)

            # Find answers for this pair (NO SUBCLASS REASONING)
            qg_template["nodes"]["na"]["ids"] = [node_id_a_preferred]
            qg_template["nodes"]["nb"]["ids"] = [node_id_b_preferred]
            input_node_ids, output_node_ids, edge_ids = self._lookup_answers("na", "nb", qg_template)

            # Record answers for this pair
            pair_key = f"{node_id_a}--{node_id_b}"
            node_pairs_to_edge_ids[pair_key] = list(edge_ids)
            all_edge_ids |= edge_ids
            all_node_ids |= input_node_ids
            all_node_ids |= output_node_ids

        logging.info("%s: Found edges for %s node pairs",
                     self.endpoint_name, len(node_pairs_to_edge_ids))

        # Then grab all edge/node objects
        kg = {"edges": {edge_id: self._convert_edge_to_trapi_format(self.edge_lookup_map[edge_id])
                        for edge_id in all_edge_ids},
              "nodes": {node_id: self._convert_node_to_trapi_format(self.node_lookup_map[node_id])
                        for node_id in all_node_ids}}

        logging.info("%s: Returning answer with %s edges and %s nodes.",
                     self.endpoint_name, len(kg['edges']), len(kg['nodes']))
        return {"pairs_to_edge_ids": node_pairs_to_edge_ids, "knowledge_graph": kg}

    def get_neighbors(self, node_ids: list[str], categories: list[str], predicates: list[str]) -> dict:
        """
        Finds neighbors for input nodes. Does *not* do subclass reasoning currently.
        """
        qg_template: dict[str, dict[str, dict[str, Any]]] = \
            {"nodes": {"n_in": {"ids": []},
                       "n_out": {"categories": categories}},
                       "edges": {"e": {"subject": "n_in",
                                       "object": "n_out",
                                       "predicates": predicates}}}
        neighbors_map = {}
        logging.info("%s: Looking up neighbors for %s input nodes",
                     self.endpoint_name, len(node_ids))
        for node_id in node_ids:
            # Convert to the equivalent identifier we recognize
            node_id_preferred = self.preferred_id_map.get(node_id, node_id)

            # Find neighbors of this node
            qg_template["nodes"]["n_in"]["ids"] = [node_id_preferred]
            _, output_node_ids, _ = self._lookup_answers("n_in", "n_out", qg_template)

            # Record neighbors for this node
            neighbors_map[node_id] = list(output_node_ids)
        logging.info("%s: Returning neighbors map with %s entries",
                     self.endpoint_name, len(neighbors_map))
        return neighbors_map

    def _lookup_answers(self, input_qnode_key: str, output_qnode_key: str, trapi_qg: dict) -> tuple[set, set, set]:
        qedge = next(qedge for qedge in trapi_qg["edges"].values())
        # Convert to canonical predicates in the QG as needed
        self._force_qedge_to_canonical_predicates(qedge)

        # Load the query and do any necessary transformations to categories/predicates
        input_curies = _convert_to_set(trapi_qg["nodes"][input_qnode_key]["ids"])
        output_curies = _convert_to_set(trapi_qg["nodes"][output_qnode_key].get("ids"))
        output_categories_expanded = self._get_expanded_output_category_ids(output_qnode_key, trapi_qg)
        qedge_predicates_expanded = self._get_expanded_qedge_predicates(qedge)

        # Use our main index to find results to the query
        final_qedge_answers: set[str] = set()
        final_input_qnode_answers = set()
        final_output_qnode_answers = set()
        main_index = self.main_index
        for input_curie in input_curies:
            answer_edge_ids = []
            # Stop looking for further answers if we've reached our edge limit
            if input_curie in main_index:
                # Consider ALL output categories if none were provided or if output curies were specified
                categories_present = set(main_index[input_curie])
                categories_to_inspect = output_categories_expanded.intersection(categories_present) if output_categories_expanded and not output_curies else categories_present
                for output_category in categories_to_inspect:
                    if output_category in main_index[input_curie]:
                        predicates_present = set(main_index[input_curie][output_category])
                        predicates_to_inspect = set(qedge_predicates_expanded).intersection(predicates_present)
                        # Loop through each QG predicate (and their descendants), looking up answers as we go
                        for predicate in predicates_to_inspect:
                            if len(final_qedge_answers) >= self.num_edges_per_answer_cutoff:
                                err_message = (f"Forbidden. Your query will produce more than "
                                               f"{self.num_edges_per_answer_cutoff} answer edges. You need to make "
                                               f"your query smaller by reducing the number of input node IDs and/or "
                                               f"using more specific categories/predicates.")
                                self.raise_http_error(403, err_message)
                            else:
                                consider_bidirectional = qedge_predicates_expanded.get(predicate)
                                if consider_bidirectional:
                                    directions = {0, 1}
                                else:
                                    # 1 means we'll look for edges recorded in 'forwards' direction, 0 means 'backwards'
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
                subject_curie = self.edge_lookup_map[answer_edge_id]["subject"]
                object_curie = self.edge_lookup_map[answer_edge_id]["object"]
                output_curie = object_curie if object_curie != input_curie else subject_curie
                # Add this edge and its nodes to our answer KG
                final_qedge_answers.add(answer_edge_id)
                final_input_qnode_answers.add(input_curie)
                final_output_qnode_answers.add(output_curie)

        return final_input_qnode_answers, final_output_qnode_answers, final_qedge_answers

    def _create_response_from_answer_ids(self, final_input_qnode_answers: set[str],
                                         final_output_qnode_answers: set[str],
                                         final_qedge_answers: set[str],
                                         input_qnode_key: str,
                                         output_qnode_key: str,
                                         qedge_key: str,
                                         trapi_qg: dict,
                                         descendant_to_query_id_map: dict) -> dict:
        log_message = (f"Found {len(final_input_qnode_answers)} input node answers, "
                       f"{len(final_output_qnode_answers)} output node answers, {len(final_qedge_answers)} edges")
        self.log_trapi("INFO", log_message)
        self.log_trapi("INFO", "Beginning to transform answers to TRAPI format..")

        # Handle any attribute constraints on the query edge
        edges = {edge_id: self._convert_edge_to_trapi_format(self.edge_lookup_map[edge_id])
                 for edge_id in final_qedge_answers}
        qedge_attribute_constraints = trapi_qg["edges"][qedge_key].get("attribute_constraints") if trapi_qg.get("edges") else []
        if qedge_attribute_constraints:
            log_message = f"Detected {len(qedge_attribute_constraints)} attribute constraints on qedge {qedge_key}"
            self.log_trapi("INFO", log_message)
            edges = self._filter_edges_by_attribute_constraints(edges, qedge_attribute_constraints)
            final_qedge_answers = set(edges)

            # Remove any nodes orphaned by attribute constraint handling
            node_ids_used_by_edges = {edge["subject"] for edge in edges.values()}.union({edge["object"] for edge in edges.values()})
            final_input_qnode_answers = final_input_qnode_answers.intersection(node_ids_used_by_edges)
            final_output_qnode_answers = final_output_qnode_answers.intersection(node_ids_used_by_edges)

            log_message = (f"After constraint handling, have {len(final_input_qnode_answers)} input node answers, "
                           f"{len(final_output_qnode_answers)} output node answers, {len(final_qedge_answers)} edges")
            self.log_trapi("INFO", log_message)
            self.log_trapi("INFO", "Continuing transformation of answers to TRAPI format..")

        # Then form the final TRAPI response
        response = {
            "message": {
                "query_graph": trapi_qg,
                "knowledge_graph": {
                    "nodes": {node_id: self._convert_node_to_trapi_format(self.node_lookup_map[node_id])
                              for node_id in final_input_qnode_answers.union(final_output_qnode_answers)},
                    "edges": edges
                },
                "results": self._get_trapi_results(final_input_qnode_answers,
                                                   final_output_qnode_answers,
                                                   final_qedge_answers,
                                                   input_qnode_key,
                                                   output_qnode_key,
                                                   qedge_key,
                                                   trapi_qg,
                                                   descendant_to_query_id_map)
            },
            "logs": self.query_log
        }
        return response

    def _convert_node_to_trapi_format(self, node_biolink: dict) -> dict:
        trapi_node = {
            "name": node_biolink.get("name"),
            "categories": _convert_to_list(node_biolink[self.categories_property]),
            "attributes": [self._get_trapi_node_attribute(property_name, value)
                           for property_name, value in node_biolink.items()
                           if property_name not in self.core_node_properties]  # Will be empty list if none (required)
        }
        return trapi_node

    def _convert_edge_to_trapi_format(self, edge_biolink: dict) -> dict:
        if self.kg_config.get("sources_template"):
            sources_template = copy.deepcopy(self.edge_sources)  # Need to copy because source urls change per edge
            if edge_biolink["predicate"] in sources_template:
                sources = sources_template[edge_biolink["predicate"]]
            else:
                sources = sources_template["default"]
        else:
            # Craft sources based on primary knowledge source on edges
            primary_ks_id = edge_biolink["primary_knowledge_source"]
            source_primary = {
                "resource_id": primary_ks_id,
                "resource_role": "primary_knowledge_source"
            }
            source_kp = {
                "resource_id": self.kp_infores_curie,
                "resource_role": "aggregator_knowledge_source",
                "upstream_resource_ids": [primary_ks_id]
            }
            sources = [source_primary, source_kp]

        if edge_biolink.get("source_record_urls"):
            source_kp = next(source for source in sources if source["resource_id"] == self.kp_infores_curie)
            source_kp["source_record_urls"] = edge_biolink["source_record_urls"]

        trapi_edge = {
            "subject": edge_biolink["subject"],
            "object": edge_biolink["object"],
            "predicate": edge_biolink["predicate"],
            "sources": sources,
            "attributes": self._get_trapi_edge_attributes(edge_biolink)
        }

        # Add any qualifier info
        qualifiers = []
        if edge_biolink.get(self.graph_qualified_predicate_property):
            qualifiers.append({
                "qualifier_type_id": "biolink:qualified_predicate",
                "qualifier_value": edge_biolink[self.graph_qualified_predicate_property]
            })
        if edge_biolink.get(self.graph_object_direction_property):
            qualifiers.append({
                "qualifier_type_id": "biolink:object_direction_qualifier",
                "qualifier_value": edge_biolink[self.graph_object_direction_property]
            })
        if edge_biolink.get(self.graph_object_aspect_property):
            qualifiers.append({
                "qualifier_type_id": "biolink:object_aspect_qualifier",
                "qualifier_value": edge_biolink[self.graph_object_aspect_property]
            })
        if qualifiers:
            trapi_edge["qualifiers"] = qualifiers

        return trapi_edge

    def _get_trapi_node_attribute(self, property_name: str, value: Any) -> dict:
        # Just use a default attribute for any properties/attributes not yet defined in kg_config.json
        attribute = copy.deepcopy(self.trapi_attribute_map.get(property_name, {"attribute_type_id": property_name}))
        attribute["value"] = value
        if attribute.get("attribute_source"):
            attribute["attribute_source"] = attribute["attribute_source"].replace("{kp_infores_curie}",
                                                                                  self.kp_infores_curie)
        if attribute.get("value_url"):
            attribute["value_url"] = attribute["value_url"].replace("{value}", value)
        return attribute

    def _get_trapi_edge_attributes(self, edge_biolink: dict) -> list[dict]:
        attributes = []
        non_core_edge_properties = set(edge_biolink.keys()).difference(self.core_edge_properties)
        for property_name in non_core_edge_properties:
            value = edge_biolink[property_name]
            if property_name in self.kg_config.get("zip", {}):
                # Handle special 'zipped' properties (e.g., supporting_studies)
                # Create an attribute for each item in this zipped up list, giving it subattributes as appropriate
                leader_property_name = self.kg_config["zip"][property_name]["leader"]
                for zipped_obj in value:
                    leader_attribute = self._get_trapi_edge_attribute(leader_property_name,
                                                                      zipped_obj[leader_property_name],
                                                                      edge_biolink)
                    leader_attribute["attributes"] = []
                    for zipped_property_name, zipped_value in zipped_obj.items():
                        if zipped_property_name != leader_property_name:
                            subattribute = self._get_trapi_edge_attribute(zipped_property_name,
                                                                          zipped_value,
                                                                          edge_biolink)
                            leader_attribute["attributes"].append(subattribute)
                    attributes.append(leader_attribute)
            else:
                # Otherwise this is just a regular attribute (no subattributes)
                attributes.append(self._get_trapi_edge_attribute(property_name, value, edge_biolink))
        return attributes

    def _get_trapi_edge_attribute(self, property_name: str, value: Any, edge_biolink: dict) -> dict:
        # Just use a default attribute for any properties/attributes not yet defined in kg_config.json
        attribute = copy.deepcopy(self.trapi_attribute_map.get(property_name, {"attribute_type_id": property_name}))
        attribute["value"] = value
        if attribute.get("attribute_source"):
            source_property_name = attribute["attribute_source"].strip("{").strip("}")
            if source_property_name == "kp_infores_curie":
                attribute["attribute_source"] = self.kp_infores_curie
            else:
                attribute["attribute_source"] = edge_biolink.get(source_property_name)
        if attribute.get("value_url"):
            attribute["value_url"] = attribute["value_url"].replace("{value}", value)
        return attribute

    def _get_trapi_results(self, final_input_qnode_answers: set[str],
                           final_output_qnode_answers: set[str],
                           final_qedge_answers: set[str],
                           input_qnode_key: str,
                           output_qnode_key: str,
                           qedge_key: str,
                           trapi_qg: dict,
                           descendant_to_query_id_map: dict) -> list[dict]:
        if qedge_key:  # This is how we detect this isn't a single-node query
            # First group edges that belong in the same result
            input_qnode_is_set = trapi_qg["nodes"][input_qnode_key].get("is_set")
            output_qnode_is_set = trapi_qg["nodes"][output_qnode_key].get("is_set")
            edge_groups = defaultdict(set)
            input_node_groups = defaultdict(set)
            output_node_groups = defaultdict(set)
            for edge_id in final_qedge_answers:
                edge = self.edge_lookup_map[edge_id]
                # Figure out which is the input vs. output node
                subject_id = edge["subject"]
                object_id = edge["object"]
                fulfilled_forwards = subject_id in final_input_qnode_answers and object_id in final_output_qnode_answers
                input_node_id = subject_id if fulfilled_forwards else object_id
                output_node_id = object_id if fulfilled_forwards else subject_id
                # Determine the proper hash key for each node
                input_node_hash_key = "*" if input_qnode_is_set else input_node_id
                output_node_hash_key = "*" if output_qnode_is_set else output_node_id
                # Assign this edge to the result it belongs in (based on its result hash key)
                result_hash_key = (input_node_hash_key, output_node_hash_key)
                edge_groups[result_hash_key].add(edge_id)
                input_node_groups[result_hash_key].add(input_node_id)
                output_node_groups[result_hash_key].add(output_node_id)

            # Then form actual results based on our result groups
            results = []
            for result_hash_key, result_edges in edge_groups.items():
                result = {
                    "node_bindings": {
                        input_qnode_key: [self._create_trapi_node_binding(input_node_id,
                                                                          descendant_to_query_id_map[input_qnode_key].get(input_node_id))
                                          for input_node_id in input_node_groups[result_hash_key]],
                        output_qnode_key: [self._create_trapi_node_binding(output_node_id,
                                                                           descendant_to_query_id_map[output_qnode_key].get(output_node_id))
                                           for output_node_id in output_node_groups[result_hash_key]]
                    },
                    "analyses": [
                        {
                            "edge_bindings": {
                                qedge_key: [{"id": edge_id, "attributes": []}  # Attributes must be empty list if none
                                            for edge_id in result_edges]
                            },
                            "resource_id": self.kp_infores_curie
                        }
                    ],
                    "resource_id": self.kp_infores_curie
                }
                results.append(result)
        else:
            # Handle single-node queries
            results = [
                {
                    "node_bindings": {
                        input_qnode_key: [
                            self._create_trapi_node_binding(node_id,
                                                            descendant_to_query_id_map[input_qnode_key].get(node_id))
                            for node_id in final_input_qnode_answers],
                    },
                    "analyses": [{"edge_bindings": {}, "attributes": []}],
                    "resource_id": self.kp_infores_curie
                }
            ]
        return results

    @staticmethod
    def _create_trapi_node_binding(node_id: str, query_ids: Optional[set[str]]) -> dict:
        node_binding = {"id": node_id, "attributes": []}  # Attributes must be empty list if none
        if query_ids:
            query_id = next(query_id for query_id in query_ids)  # TRAPI/translator isn't set up to handle multiple yet
            if node_id != query_id:
                node_binding["query_id"] = query_id
        return node_binding

    def _filter_edges_by_attribute_constraints(self, trapi_edges: dict[str, dict],
                                               qedge_attribute_constraints: list[dict]) -> dict[str, dict]:
        constraints_dict = {f"{constraint['id']}--{constraint['operator']}--{constraint['value']}--{constraint.get('not')}": constraint
                            for constraint in qedge_attribute_constraints}
        constraints_set = set(constraints_dict)
        edge_keys_to_delete = set()
        for edge_key, edge in trapi_edges.items():
            fulfilled = False
            # First try to fulfill all constraints via top-level attributes on this edge
            # Pretend that edge sources are attributes too, to allow filtering based on sources via attr constraints
            sources_attrs = [{"attribute_type_id": source["resource_role"],
                              "value": source["resource_id"]} for source in edge["sources"]]
            fulfilled_top = {constraint_key for constraint_key, constraint in constraints_dict.items()
                             if any(self._meets_constraint(attribute=attribute,
                                                           constraint=constraint)
                                    for attribute in edge["attributes"] + sources_attrs)}

            # If any constraints remain unfulfilled, see if we can fulfill them using subattributes
            remaining_constraints = constraints_set.difference(fulfilled_top)
            if remaining_constraints:
                # NOTE: All remaining constraints must be fulfilled by subattributes on the *same* attribute to count
                for attribute in edge["attributes"]:
                    fulfilled_nested = {constraint_key for constraint_key in remaining_constraints
                                        if any(self._meets_constraint(attribute=subattribute,
                                                                      constraint=constraints_dict[constraint_key])
                                               for subattribute in attribute.get("attributes", []))}
                    if fulfilled_nested == remaining_constraints:
                        fulfilled = True
                        break  # Don't need to check remaining attributes on this edge
            else:
                fulfilled = True

            if not fulfilled:
                edge_keys_to_delete.add(edge_key)

        # Then actually delete the edges
        if edge_keys_to_delete:
            log_message = f"Deleting {len(edge_keys_to_delete)} edges that do not meet qedge attribute constraints"
            self.log_trapi("INFO", log_message)
            for edge_key in edge_keys_to_delete:
                del trapi_edges[edge_key]
        return trapi_edges

    def _meets_constraint(self, attribute: dict, constraint: dict) -> bool:
        # Make sure we have compatible attribute/constraint IDs
        constraint_id = constraint["id"]
        attribute_id = attribute["attribute_type_id"]
        if constraint_id == "knowledge_source" and attribute_id in self.knowledge_source_properties:
            attribute_id = "knowledge_source"  # Allow sub-source types to fulfill higher level 'knowledge_source'
        if attribute_id != constraint_id:
            return False

        attribute_value = attribute["value"]
        constraint_value = constraint["value"]
        operator = constraint["operator"]
        is_not = constraint.get("not")

        # Do some data type conversions, as needed
        attribute_val_is_list = isinstance(attribute_value, list)
        constraint_val_is_list = isinstance(constraint_value, list)
        # Convert clinical trial phase enum to numbers (internally) for easier comparison
        if attribute_val_is_list:
            attribute_value = [self.trial_phases_map_reversed.get(val, val) for val in attribute_value]
        else:
            attribute_value = self.trial_phases_map_reversed.get(attribute_value, attribute_value)
        if constraint_val_is_list:
            constraint_value = [self.trial_phases_map_reversed.get(val, val) for val in constraint_value]
            constraint_value = [_load_value(val) for val in constraint_value]
        else:
            constraint_value = self.trial_phases_map_reversed.get(constraint_value, constraint_value)
            constraint_value = _load_value(constraint_value)

        try:
            # TODO: Add 'matches'?
            meets_constraint = True
            # Now figure out whether the attribute meets the constraint, ignoring the 'not' property on the constraint
            if operator == "==":
                if attribute_val_is_list and constraint_val_is_list:
                    meets_constraint = set(attribute_value).intersection(set(constraint_value)) != set()
                elif attribute_val_is_list:
                    meets_constraint = constraint_value in attribute_value
                elif constraint_val_is_list:
                    meets_constraint = attribute_value in constraint_value
                else:
                    meets_constraint = attribute_value == constraint_value
            elif operator == "<":
                if attribute_val_is_list and constraint_val_is_list:
                    meets_constraint = any(attribute_val < constraint_val for attribute_val in attribute_value
                                           for constraint_val in constraint_value)
                elif attribute_val_is_list:
                    meets_constraint = any(attribute_val < constraint_value for attribute_val in attribute_value)
                elif constraint_val_is_list:
                    meets_constraint = any(attribute_value < constraint_val for constraint_val in constraint_value)
                else:
                    meets_constraint = attribute_value < constraint_value
            elif operator == ">":
                if attribute_val_is_list and constraint_val_is_list:
                    meets_constraint = any(attribute_val > constraint_val for attribute_val in attribute_value
                                           for constraint_val in constraint_value)
                elif attribute_val_is_list:
                    meets_constraint = any(attribute_val > constraint_value for attribute_val in attribute_value)
                elif constraint_val_is_list:
                    meets_constraint = any(attribute_value > constraint_val for constraint_val in constraint_value)
                else:
                    meets_constraint = attribute_value > constraint_value
            elif operator == "<=":
                if attribute_val_is_list and constraint_val_is_list:
                    meets_constraint = any(attribute_val <= constraint_val for attribute_val in attribute_value
                                           for constraint_val in constraint_value)
                elif attribute_val_is_list:
                    meets_constraint = any(attribute_val <= constraint_value for attribute_val in attribute_value)
                elif constraint_val_is_list:
                    meets_constraint = any(attribute_value <= constraint_val for constraint_val in constraint_value)
                else:
                    meets_constraint = attribute_value <= constraint_value
            elif operator == ">=":
                if attribute_val_is_list and constraint_val_is_list:
                    meets_constraint = any(attribute_val >= constraint_val for attribute_val in attribute_value
                                           for constraint_val in constraint_value)
                elif attribute_val_is_list:
                    meets_constraint = any(attribute_val >= constraint_value for attribute_val in attribute_value)
                elif constraint_val_is_list:
                    meets_constraint = any(attribute_value >= constraint_val for constraint_val in constraint_value)
                else:
                    meets_constraint = attribute_value >= constraint_value
            elif operator == "===":
                meets_constraint = attribute_value == constraint_value
            else:
                log_message = (f"Encountered unsupported operator: {operator}. Don't know how to handle; "
                               f"will ignore this constraint.")
                self.log_trapi("WARNING", log_message)
        except (TypeError, KeyError):
            return False

        # Now factor in the 'not' property on the constraint
        return not meets_constraint if is_not else meets_constraint

    def _get_descendants(self, node_ids: Union[list[str], str]) -> list[str]:
        node_ids_set = _convert_to_set(node_ids)
        proper_descendants = {descendant_id for node_id in node_ids_set
                              for descendant_id in self.subclass_index.get(node_id, set())}
        descendants = proper_descendants.union(node_ids_set)
        return list(descendants)

    @staticmethod
    def _determine_input_qnode_key(qnodes: dict[str, dict[str, Union[str, list[str], None]]]) -> str:
        # The input qnode should be the one with the larger number of curies (way more efficient for our purposes)
        qnode_key_with_most_curies = ""
        most_curies = 0
        for qnode_key, qnode in qnodes.items():
            ids_property = "ids" if "ids" in qnode else "id"
            qnode_ids = qnode.get(ids_property)
            if not qnode_ids:
                continue
            if isinstance(qnode_ids, str):
                qnode_ids = [qnode_ids]
            num_qnode_ids_curies = len(qnode_ids)
            if num_qnode_ids_curies > most_curies:
                most_curies = num_qnode_ids_curies
                qnode_key_with_most_curies = qnode_key
        return qnode_key_with_most_curies

    def _get_expanded_output_category_ids(self, output_qnode_key: str, trapi_qg: dict) -> set[int]:
        output_category_names_raw = _convert_to_set(trapi_qg["nodes"][output_qnode_key].get("categories"))
        output_category_names_raw = {self.bh.get_root_category()} if not output_category_names_raw else output_category_names_raw
        output_category_names = self.bh.replace_mixins_with_direct_mappings(output_category_names_raw)
        output_categories_with_descendants = self.bh.get_descendants(output_category_names, include_mixins=False)
        output_category_ids = {self.category_map.get(category, self.non_biolink_item_id) for category in output_categories_with_descendants}
        return output_category_ids

    def _consider_bidirectional(self, predicate: str, direct_qg_predicates: set[str]) -> bool:
        """
        This function determines whether or not QEdge direction should be ignored for a particular predicate or
        'conglomerate' predicate based on the Biolink model and QG parameters.
        """
        if "--" in predicate:  # Means it's a 'conglomerate' predicate
            predicate = self._get_used_predicate(predicate)
        # Make sure we extract the true predicate/qualified predicate from conglomerate predicates
        direct_qg_predicates = {self._get_used_predicate(direct_predicate) for direct_predicate in direct_qg_predicates}

        if predicate in direct_qg_predicates:
            return self.bh.is_symmetric(predicate)
        if all(self.bh.is_symmetric(direct_predicate) for direct_predicate in direct_qg_predicates):
            return True
        # Figure out which predicate(s) in the QG this descendant predicate corresponds to
        ancestor_predicates = set(self.bh.get_ancestors(predicate, include_mixins=True)).difference({predicate})
        ancestor_predicates_in_qg = ancestor_predicates.intersection(direct_qg_predicates)
        if any(self.bh.is_symmetric(qg_predicate_ancestor) for qg_predicate_ancestor in ancestor_predicates_in_qg):
            return True
        return self.bh.is_symmetric(predicate)

    @staticmethod
    def _get_used_predicate(conglomerate_predicate: str) -> str:
        """
        This extracts the predicate used as part of the conglomerate predicate (which could be either the qualified
        predicate or regular predicate).
        """
        return conglomerate_predicate.split("--")[0]

    def _force_qedge_to_canonical_predicates(self, qedge: dict):
        user_qual_predicates = self._get_qualified_predicates_from_qedge(qedge)
        user_regular_predicates = _convert_to_set(qedge.get("predicates"))
        user_predicates = user_qual_predicates if user_qual_predicates else user_regular_predicates
        canonical_predicates = set(self.bh.get_canonical_predicates(user_predicates, print_warnings=False))
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
                            canonical_qual_predicate = self.bh.get_canonical_predicates(qualifier["qualifier_value"],
                                                                                        print_warnings=False)[0]
                            qualifier["qualifier_value"] = canonical_qual_predicate
            else:
                # Otherwise just flip all of the regular predicates
                qedge["predicates"] = list(canonical_predicates)
        elif user_non_canonical_predicates and user_canonical_predicates:
            err_message = (f"QueryGraph uses both canonical and non-canonical "
                           f"{'qualified ' if user_qual_predicates else ''}predicates. Canonical: "
                           f"{user_canonical_predicates}, Non-canonical: {user_non_canonical_predicates}. "
                           f"You must use either all canonical or all non-canonical predicates.")
            self.raise_http_error(400, err_message)

    def _get_qualified_predicates_from_qedge(self, qedge: dict) -> set[str]:
        qualified_predicates = set()
        for qualifier_constraint in qedge.get("qualifier_constraints", []):
            for qualifier in qualifier_constraint.get("qualifier_set"):
                if qualifier["qualifier_type_id"] == self.qedge_qualified_predicate_property:
                    qualified_predicates.add(qualifier["qualifier_value"])
        return qualified_predicates

    def _get_expanded_qedge_predicates(self, qedge: dict) -> dict[int, bool]:
        """
        This function returns a qedge's "conglomerate" predicates for qualified qedges (where the qualified info is kind
        of flattened or conglomerated into one derived predicate string), or its regular predicates when no qualified
        info is available. It also returns descendants of the predicates/conglomerate predicates.
        """
        # Use 'conglomerate' predicates if the query has any qualifier constraints
        if qedge.get("qualifier_constraints"):
            qedge_conglomerate_predicates = self._get_conglomerate_predicates_from_qedge(qedge)
            # Now find all descendant versions of our conglomerate predicates (pre-computed during index-building)
            qedge_conglomerate_predicates_expanded = {descendant for conglomerate_predicate in qedge_conglomerate_predicates
                                                      for descendant in self.conglomerate_predicate_descendant_index.get(conglomerate_predicate, set())}
            qedge_predicates = qedge_conglomerate_predicates
            qedge_predicates_expanded = qedge_conglomerate_predicates_expanded
        # Otherwise we'll use the regular predicates if no qualified predicates were given
        else:
            qedge_predicates_raw = _convert_to_set(qedge.get("predicates"))
            qedge_predicates_raw = {self.bh.get_root_predicate()} if not qedge_predicates_raw else qedge_predicates_raw
            # Include both proper and mixin predicates, but also map mixins to their proper predicates (if any exist)
            qedge_predicates_proper = self.bh.replace_mixins_with_direct_mappings(qedge_predicates_raw)
            qedge_predicates = qedge_predicates_raw.union(qedge_predicates_proper)
            qedge_predicates_expanded = {descendant_predicate for qg_predicate in qedge_predicates
                                         for descendant_predicate in self.bh.get_descendants(qg_predicate, include_mixins=True)}
        # Convert english categories/predicates/conglomerate predicates into integer IDs (helps save space)
        qedge_predicate_ids_dict = {self.predicate_map.get(predicate, self.non_biolink_item_id):
                                        self._consider_bidirectional(predicate, qedge_predicates)
                                    for predicate in qedge_predicates_expanded}

        return qedge_predicate_ids_dict

    def _get_conglomerate_predicates_from_qedge(self, qedge: dict) -> set[str]:
        qedge_conglomerate_preds: set[str] = set()
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
                new_conglomerate_predicates = \
                    {self._get_conglomerate_predicate(qualified_predicate=qualified_predicate,
                                                      predicate=predicate,
                                                      object_direction=object_direction_qualifier,
                                                      object_aspect=object_aspect_qualifier)
                                               for predicate in predicates}
                qedge_conglomerate_preds = qedge_conglomerate_preds.union(new_conglomerate_predicates)
            else:
                # Use the qualified predicate (is 'None' if not available)
                qedge_conglomerate_preds.add(self._get_conglomerate_predicate(qualified_predicate=\
                                                                              qualified_predicate,
                                                                              predicate=None,
                                                                              object_direction=\
                                                                              object_direction_qualifier,
                                                                              object_aspect=\
                                                                              object_aspect_qualifier))
        return qedge_conglomerate_preds

    def _answer_single_node_query(self, trapi_qg: dict) -> Any:
        # When no qedges are involved, we only fulfill qnodes that have a curie (this isn't part of TRAPI; just handy)
        if len(trapi_qg["nodes"]) > 1:
            err_message = (f"Bad Request. Edgeless queries can only involve a single query node. "
                           f"Your QG has {len(trapi_qg['nodes'])} nodes.")
            self.raise_http_error(400, err_message)
        qnode_key = list(trapi_qg["nodes"].keys())[0]
        if not trapi_qg["nodes"][qnode_key].get("ids"):
            err_message = "Bad Request. For qnode-only queries, the qnode must have 'ids' specified."
            self.raise_http_error(400, err_message)

        self.log_trapi("INFO", "Answering single-node query...")
        qnode = trapi_qg["nodes"][qnode_key]
        qnode_ids_set = _convert_to_set(qnode["ids"])
        input_curies = qnode["ids"].copy()
        descendant_to_query_id_map: dict[str, dict[str, set[str]]] = {qnode_key: defaultdict(set)}
        if input_curies:
            for query_curie in qnode_ids_set:
                descendants = self._get_descendants(query_curie)
                for descendant in descendants:
                    # Record query curie mapping if this is a descendant not listed in the QG
                    if descendant not in qnode_ids_set:
                        descendant_to_query_id_map[qnode_key][descendant].add(query_curie)
                input_curies += descendants
        found_curies = set(input_curies).intersection(set(self.node_lookup_map))
        response = self._create_response_from_answer_ids(final_input_qnode_answers=found_curies,
                                                         final_output_qnode_answers=set(),
                                                         final_qedge_answers=set(),
                                                         input_qnode_key=qnode_key,
                                                         output_qnode_key="",
                                                         qedge_key="",
                                                         trapi_qg=trapi_qg,
                                                         descendant_to_query_id_map=\
                                                         descendant_to_query_id_map)
        log_message = f"Done with query, returning TRAPI response ({len(response['message']['results'])} results)"
        self.log_trapi("INFO", log_message)
        return response

    # ----------------------------------------- GENERAL HELPER METHODS ---------------------------------------------- #

    @staticmethod
    def raise_http_error(http_code: int, err_message: str):
        detail_message = f"{http_code} ERROR: {err_message}"
        logging.error(detail_message)
        flask.abort(http_code, detail_message)

    def _get_file_names_to_use(self) -> tuple[str, str]:
        nodes_file = self.kg_config["nodes_file"]
        edges_file = self.kg_config["edges_file"]
        return nodes_file, edges_file

    def log_trapi(self, level: str, message: str, code: Optional[str] = None):
        message = f"{self.endpoint_name}: {message}"
        # First log this in our usual log
        if level == "INFO":
            logging.info(message)
        elif level == "WARNING":
            logging.warning(message)
        elif level == "ERROR":
            logging.error(message)
        else:
            logging.debug(message)
        # Then also add it to our TRAPI log
        log_entry = {"timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "level": level,
                     "message": message}
        if code:
            log_entry["code"] = code
        self.query_log.append(log_entry)
