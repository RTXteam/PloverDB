import json
import os
from typing import List, Set, Optional

import pytest
import requests

SCRIPT_DIR = f"{os.path.dirname(os.path.abspath(__file__))}"


class PloverTester:

    def __init__(self, endpoint: str, subendpoint: Optional[str] = None):
        self.acetaminophen_id = "CHEBI:46195"
        self.diabetes_id = "MONDO:0005015"
        self.t2_diabetes_id = "MONDO:0005148"
        self.t1_diabetes_id = "MONDO:0005147"
        self.parkinsons_id = "MONDO:0005180"
        self.parkinsons_id_doid = "DOID:14330"

        self.endpoint = endpoint
        self.subendpoint = subendpoint
        self.endpoint_url = f"{self.endpoint}/{self.subendpoint}" if self.subendpoint else f"{self.endpoint}"
        print(f"endpoint url is {self.endpoint_url}")

    def run_query(self, trapi_qg: dict, should_produce_results: bool = True, should_produce_error: bool = False) -> dict:
        trapi_query = {"message": {"query_graph": trapi_qg}, "submitter": "ploverdb-test-suite"}
        is_edgeless_query = False if len(trapi_qg.get("edges", {})) else True
        response = requests.post(f"{self.endpoint_url}/query", json=trapi_query, headers={'accept': 'application/json'})
        if should_produce_error:
            assert not response.ok

        if response.ok:
            print(f"Request elapsed time: {response.elapsed.total_seconds()} sec")
            json_response = response.json()
            if pytest.save:
                with open(f"{SCRIPT_DIR}/test_response.json", "w+") as test_output_file:
                    json.dump(json_response, test_output_file, indent=2)

            assert json_response["message"]
            if should_produce_results:
                # Verify results structure looks good
                assert json_response["message"]["results"]
                results = json_response["message"]["results"]
                print(f"Returned {len(results)} results.")
                for result in results:
                    assert result["node_bindings"]
                    assert set(result["node_bindings"]) == set(trapi_qg["nodes"])  # Qnode keys should match
                    for qnode_key, qnode_bindings in result["node_bindings"].items():
                        for node_binding in qnode_bindings:
                            assert node_binding["id"]
                            assert isinstance(node_binding["attributes"], list)
                    if not is_edgeless_query:
                        assert result["analyses"]
                        assert len(result["analyses"]) == 1
                        for analysis in result["analyses"]:
                            assert analysis["edge_bindings"]
                            assert set(analysis["edge_bindings"]) == set(trapi_qg["edges"])  # Qedge keys should match
                            for qedge_key, qedge_bindings in analysis["edge_bindings"].items():
                                for edge_binding in qedge_bindings:
                                    assert edge_binding["id"]
                                    assert isinstance(edge_binding["attributes"], list)

                # Verify knowledge graph structure looks good
                assert json_response["message"]["knowledge_graph"]
                kg = json_response["message"]["knowledge_graph"]
                assert kg["nodes"]
                for node in kg["nodes"].values():
                    assert "name" in node  # Code be null for some (e.g. pathwhiz), but slot should still exist
                    assert node["categories"]
                    node_attributes = node.get("attributes")
                    assert isinstance(node_attributes, list)  # TRAPI 1.5 requires empty attribute lists if none
                if not is_edgeless_query:
                    assert kg["edges"]
                    for edge in kg["edges"].values():
                        assert edge["subject"]
                        assert edge["object"]
                        assert edge["predicate"]
                        assert edge["sources"]
                        sources = edge["sources"]
                        assert any(source["resource_role"] == "primary_knowledge_source" for source in sources)
                        for source in sources:
                            if source.get("source_record_urls"):
                                assert isinstance(source["source_record_urls"], list)
                        edge_attributes = edge.get("attributes")
                        assert isinstance(edge_attributes, list)  # Every edge should have attributes
                        assert len(edge_attributes)
                        assert any(attr for attr in edge_attributes
                                   if attr["attribute_type_id"] == "biolink:knowledge_level")
                        assert any(attr for attr in edge_attributes
                                   if attr["attribute_type_id"] == "biolink:agent_type")

                # Verify log structure looks good
                assert json_response["logs"]
                logs = json_response["logs"]
                assert len(logs)
                for entry in logs:
                    assert entry["timestamp"]
                    assert entry["level"]
                    assert entry["message"]

            return json_response
        else:
            print(f"Response status code was {response.status_code}. Response was: {response.text}")
            return dict()

    def run_get_edges(self, pairs: List[List[str]]) -> dict:
        pairs_query = {"pairs": pairs}
        response = requests.post(f"{self.endpoint_url}/get_edges", json=pairs_query,
                                 headers={'accept': 'application/json'})
        if response.ok:
            print(f"Request elapsed time: {response.elapsed.total_seconds()} sec")
            response_json = response.json()
            if pytest.save:
                with open(f"{SCRIPT_DIR}/test_response.json", "w+") as test_output_file:
                    json.dump(response_json, test_output_file, indent=2)
            pairs_to_edge_ids = response_json.get("pairs_to_edge_ids")
            assert pairs_to_edge_ids
            assert len(pairs_to_edge_ids) == len(pairs)
            knowledge_graph = response_json.get("knowledge_graph")
            assert knowledge_graph
            assert knowledge_graph.get("edges")
            assert knowledge_graph.get("nodes")
            print(f"Returned {len(knowledge_graph['edges'])} edges.")
            return response_json
        else:
            print(f"Response status code was {response.status_code}. Response was: {response.text}")
            return dict()

    def run_get_neighbors(self, query: dict) -> dict:
        response = requests.post(f"{self.endpoint_url}/get_neighbors", json=query,
                                 headers={'accept': 'application/json'})
        if response.ok:
            print(f"Request elapsed time: {response.elapsed.total_seconds()} sec")
            response_json = response.json()
            if pytest.save:
                with open(f"{SCRIPT_DIR}/test_response.json", "w+") as test_output_file:
                    json.dump(response_json, test_output_file, indent=2)
            assert len(response_json) == len(query["node_ids"])
            print(f"Answer includes {len(response_json)} entries.")
            for neighbors_list in response_json.values():
                assert neighbors_list
            return response_json
        else:
            print(f"Response status code was {response.status_code}. Response was: {response.text}")
            return dict()

    @staticmethod
    def print_results(results: List[dict]):
        print(f"\nPRINTING {len(results)} RESULTS:")
        result_counter = 0
        for result in results:
            result_counter += 1
            print(f"result {result_counter}:")
            print(f"  edges:")
            analysis_counter = 0
            for analysis in result["analyses"]:
                analysis_counter += 1
                print(f"    analysis {analysis_counter}:")
                for qedge_key, edge_bindings in analysis["edge_bindings"].items():
                    print(f"      {qedge_key} edge bindings:")
                    for edge_binding in edge_bindings:
                        print(f"        {edge_binding}")
            print(f"  nodes:")
            for qnode_key, node_bindings in result["node_bindings"].items():
                print(f"    {qnode_key}:")
                for node_binding in node_bindings:
                    print(f"      {node_binding}")

    @staticmethod
    def get_supporting_study_attributes(edge: dict) -> List[dict]:
        return [attribute for attribute in edge["attributes"]
                if attribute["attribute_type_id"] == "biolink:supporting_study"]

    @staticmethod
    def get_num_distinct_concepts(response: dict, qnode_key: str) -> int:
        distinct_concepts = {node_binding.get("query_id", node_binding["id"])
                             for result in response["message"]["results"]
                             for node_binding in result["node_bindings"][qnode_key]}
        return len(distinct_concepts)

    @staticmethod
    def get_node_ids(response: dict, qnode_key: str) -> Set[str]:
        node_ids = {node_binding["id"]
                    for result in response["message"]["results"]
                    for node_binding in result["node_bindings"][qnode_key]}
        return node_ids

    @staticmethod
    def get_equivalent_curies(response: dict, node_id: str) -> Set[str]:
        equiv_ids_attr = next(attr for attr in response["message"]["knowledge_graph"]["nodes"][node_id]["attributes"]
                              if attr["attribute_type_id"] == "biolink:xref")
        return set(equiv_ids_attr["value"])

