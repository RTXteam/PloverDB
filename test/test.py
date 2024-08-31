import json
from collections import defaultdict

import pytest
import requests
from typing import Dict, Union, List

ASPIRIN_CURIE = "CHEBI:15365"
TICLOPIDINE_CURIE = "CHEBI:9588"
ACETAMINOPHEN_CURIE = "CHEBI:46195"
PROC_CURIE = "NCBIGene:5624"
DIETHYLSTILBESTROL_CURIE = "PUBCHEM.COMPOUND:448537"
METHYLPREDNISOLONE_CURIE = "PUBCHEM.COMPOUND:23663977"
RHOBTB2_CURIE = "NCBIGene:23221"
DIABETES_CURIE = "MONDO:0005015"
DIABETES_T1_CURIE = "MONDO:0005147"
DIABETES_T2_CURIE = "MONDO:0005148"
POS_REG_OF_MITOCHONDRIAL_DEPOL = "GO:0051901"
MITOCHONDRIAL_DEPOLARIZATION = "GO:0051882"
PARKINSONS_CURIE = "MONDO:0005180"
BIPOLAR_CURIE = "MONDO:0004985"


def _print_kg(kg: Dict[str, Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]]):
    nodes_by_qg_id = kg["nodes"]
    edges_by_qg_id = kg["edges"]
    for qnode_key, node_ids in sorted(nodes_by_qg_id.items()):
        print(f"{qnode_key}: {node_ids}")
    for qedge_key, edge_ids in sorted(edges_by_qg_id.items()):
        print(f"{qedge_key}: {edge_ids}")


def _print_results(results: List[dict]):
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


def _run_query(trapi_qg: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]],
               return_trapi_response: bool = False) -> any:
    trapi_query = {"message": {"query_graph": trapi_qg},
                   "submitter": "ploverdb-test-suite"}
    response = requests.post(f"{pytest.endpoint}/query", json=trapi_query, headers={'accept': 'application/json'})
    if response.status_code == 200:
        json_response = response.json()
        with open(f"test_response.json", "w+") as test_output_file:
            json.dump(json_response, test_output_file, indent=2)

        # Convert the TRAPI response to the old plover response format (IDs organized by QG IDs)
        message = json_response["message"]
        answer_node_ids = defaultdict(set)
        answer_edge_ids = defaultdict(set)
        for result in message["results"]:
            for qnode_key, node_bindings in result["node_bindings"].items():
                for node_binding in node_bindings:
                    answer_node_ids[qnode_key].add(node_binding["id"])
            if result.get("analyses"):
                for qedge_key, edge_bindings in result["analyses"][0]["edge_bindings"].items():
                    for edge_binding in edge_bindings:
                        answer_edge_ids[qedge_key].add(edge_binding["id"])
        nodes = dict()
        edges = dict()
        for qnode_key, node_ids in answer_node_ids.items():
            nodes[qnode_key] = dict()
            for node_id in node_ids:
                nodes[qnode_key][node_id] = message["knowledge_graph"]["nodes"][node_id]
        for qedge_key, edge_ids in answer_edge_ids.items():
            edges[qedge_key] = dict()
            for edge_id in edge_ids:
                edges[qedge_key][edge_id] = message["knowledge_graph"]["edges"][edge_id]
        qg_organized_kg = {"nodes": nodes, "edges": edges}

        if return_trapi_response:
            return qg_organized_kg, json_response
        else:
            return qg_organized_kg
    else:
        print(f"Response status code was {response.status_code}. Response was: {response.text}")
        return dict()


def test_1a():
    # Simplest one-hop
    query = {
       "edges": {
          "e00": {
             "subject": "n00",
             "object": "n01",
             "predicates": ["biolink:related_to"]
          }
       },
       "nodes": {
          "n00": {
             "ids": ["GO:0035329"]
          },
          "n01": {
             "categories": ["biolink:NamedThing"]
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_2():
    # Output qnode is lacking a category
    query = {
       "edges": {
          "e00": {
             "subject": "n00",
             "object": "n01",
             "predicates": ["biolink:related_to"]
          }
       },
       "nodes": {
          "n00": {
             "ids": [ASPIRIN_CURIE],
             "categories": ["biolink:ChemicalEntity"]
          },
          "n01": {
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_3():
    # No predicate is specified
    query = {
       "edges": {
          "e00": {
             "subject": "n00",
             "object": "n01"
          }
       },
       "nodes": {
          "n00": {
             "ids": [ASPIRIN_CURIE],
             "categories": ["biolink:ChemicalEntity"]
          },
          "n01": {
              "categories": ["biolink:ChemicalEntity"]
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_4():
    # Multiple output categories
    query = {
       "edges": {
          "e00": {
             "subject": "n00",
             "object": "n01"
          }
       },
       "nodes": {
          "n00": {
             "ids": [ASPIRIN_CURIE]
          },
          "n01": {
              "categories": ["biolink:Protein", "biolink:Procedure"]
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_5():
    # Multiple predicates
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:physically_interacts_with", "biolink:related_to"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE]
            },
            "n01": {
                "categories": ["biolink:Protein", "biolink:Gene"]
            }
        }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_6():
    # Curie-to-curie query
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01"
            }
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE]
            },
            "n01": {
                "ids": [TICLOPIDINE_CURIE, ACETAMINOPHEN_CURIE]
            }
        }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_7():
    # Multiple-curie query
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01"
            }
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE, PROC_CURIE]
            },
            "n01": {
            }
        }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_8():
    # Single-node query
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) == 1


def test_9():
    # Single-node query with multiple curies
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE, ACETAMINOPHEN_CURIE]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) == 2


def test_11():
    # Verify catches larger than one-hop query
    query = {
        "edges": {
            "e00": {},
            "e01": {}
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE]
            },
            "n01": {
                "ids": [DIETHYLSTILBESTROL_CURIE]
            }
        }
    }
    kg = _run_query(query)
    assert not kg


def test_12a():
    ids = [ASPIRIN_CURIE, METHYLPREDNISOLONE_CURIE]
    # Test predicate symmetry is handled properly
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:interacts_with"]
            }
        },
        "nodes": {
            "n00": {
                "ids": ids
            },
            "n01": {
            }
        }
    }
    kg_symmetric = _run_query(query)

    query = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:interacts_with"]
            }
        },
        "nodes": {
            "n00": {
                "ids": ids
            },
            "n01": {
            }
        }
    }
    kg_symmetric_reversed = _run_query(query)

    assert kg_symmetric["nodes"]["n00"] and kg_symmetric["nodes"]["n01"] and kg_symmetric["edges"]["e00"]
    assert set(kg_symmetric["nodes"]["n01"]) == set(kg_symmetric_reversed["nodes"]["n01"])


def test_12b():
    # Make sure directionality is enforced for treats predicate
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE, METHYLPREDNISOLONE_CURIE]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        }
    }
    kg_asymmetric = _run_query(query)
    assert kg_asymmetric["nodes"]["n00"] and kg_asymmetric["nodes"]["n01"] and kg_asymmetric["edges"]["e00"]
    assert all(edge["subject"] in kg_asymmetric["nodes"]["n00"] for edge in kg_asymmetric["edges"]["e00"].values())


def test_12c():
    # Make sure no answers are returned when treats predicate is backwards in the QG
    query = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE, METHYLPREDNISOLONE_CURIE]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        }
    }
    kg_backwards = _run_query(query)
    assert not kg_backwards["edges"]


def test_14():
    # Test subclass_of reasoning with single-node queries
    query_subclass = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [DIABETES_CURIE],  # Diabetes mellitus
            }
        }
    }
    kg = _run_query(query_subclass)
    assert len(kg["nodes"]["n00"]) > 1
    query_no_subclass = {
        "include_metadata": True,
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [DIABETES_CURIE]  # Diabetes mellitus
            }
        }
    }
    kg = _run_query(query_no_subclass)
    assert len(kg["nodes"]["n00"]) == 1


def test_15():
    # Test predicate symmetry enforcement
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ACETAMINOPHEN_CURIE]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n01"]

    query_respecting_symmetry = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ACETAMINOPHEN_CURIE]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        },
        "respect_predicate_symmetry": True
    }
    kg_symmetry = _run_query(query_respecting_symmetry)
    assert kg_symmetry["nodes"]["n01"]

    query_symmetry_backwards = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ACETAMINOPHEN_CURIE]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        },
        "respect_predicate_symmetry": True
    }
    kg_symmetry_backwards = _run_query(query_symmetry_backwards)
    assert not kg_symmetry_backwards["nodes"]["n01"]
    assert len(kg_symmetry["nodes"]["n01"]) == len(kg["nodes"]["n01"])


def test_16():
    # Test mixins in the QG
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01"
            }
        },
        "nodes": {
            "n00": {
                "ids": [ACETAMINOPHEN_CURIE]
            },
            "n01": {
                "categories": ["biolink:PhysicalEssence"]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n01"])


def test_17():
    # Test canonical predicate handling
    query_canonical = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["PUBCHEM.COMPOUND:54758501"]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        }
    }
    kg_canonical = _run_query(query_canonical)
    assert len(kg_canonical["nodes"]["n01"])

    query_non_canonical = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:subject_of_treatment_application_or_study_for_treatment_by"]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["PUBCHEM.COMPOUND:54758501"]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        }
    }
    kg_non_canonical = _run_query(query_non_canonical)
    assert len(kg_non_canonical["nodes"]["n01"])

    assert len(kg_canonical["nodes"]["n01"]) == len(kg_non_canonical["nodes"]["n01"])


def test_18():
    # Test hierarchical category reasoning
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:interacts_with"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ACETAMINOPHEN_CURIE]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n01"]
    assert any(node["categories"] != "biolink:NamedThing" for node in kg["nodes"]["n01"].values())


def test_19():
    # Test hierarchical predicate reasoning
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:related_to"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [ACETAMINOPHEN_CURIE]
            },
            "n01": {
                "categories": ["biolink:Protein"]
            }
        }
    }
    kg = _run_query(query)
    assert kg["edges"]["e00"]
    assert any(edge["predicate"] != "biolink:related_to" for edge in kg["edges"]["e00"].values())


def test_20():
    # Test that the proper 'query_id' mapping (for TRAPI) is returned
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01"
            }
        },
        "nodes": {
            "n00": {
                "ids": [DIABETES_CURIE, DIABETES_T2_CURIE]
            },
            "n01": {
                "categories": ["biolink:ChemicalEntity"]
            }
        }
    }
    kg, trapi_response = _run_query(query, return_trapi_response=True)
    assert len(kg["nodes"]["n00"]) > 1
    assert {DIABETES_CURIE, DIABETES_T1_CURIE, DIABETES_T2_CURIE}.issubset(set(kg["nodes"]["n00"]))

    for result in trapi_response["message"]["results"]:
        for qnode_key, node_bindings in result["node_bindings"].items():
            for node_binding in node_bindings:
                if node_binding["id"] == DIABETES_CURIE:  # This ID was input in the QG
                    assert not node_binding.get("query_id")
                elif node_binding["id"] == DIABETES_T2_CURIE:  # This ID was input in the QG
                    assert not node_binding.get("query_id")
                elif node_binding["id"] == DIABETES_T1_CURIE:  # This ID was NOT input in the QG
                    # Descendant curies should indicate which QG curie they correspond to
                    assert node_binding.get("query_id") == DIABETES_CURIE


def test_21():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:qualified_predicate",
                         "qualifier_value": "biolink:causes"},
                        {"qualifier_type_id": "biolink:object_direction_qualifier",
                         "qualifier_value": "decreased"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["CHEBI:94557"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert "NCBIGene:2554" in kg["nodes"]["n01"]


def test_22():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:interacts_with"],  # This is the wrong regular predicate, but it shouldn't matter
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:qualified_predicate",
                         "qualifier_value": "biolink:causes"},
                        {"qualifier_type_id": "biolink:object_aspect_qualifier",
                         "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["CHEBI:90879"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert "NCBIGene:1890" in kg["nodes"]["n01"]


def test_23():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:affects"],
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:qualified_predicate",
                         "qualifier_value": "biolink:causes"},
                        {"qualifier_type_id": "biolink:object_direction_qualifier",
                         "qualifier_value": "increased"},
                        # {"qualifier_type_id": "biolink:object_aspect_qualifier",
                        #  "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": [POS_REG_OF_MITOCHONDRIAL_DEPOL]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert MITOCHONDRIAL_DEPOLARIZATION in kg["nodes"]["n01"]


def test_24():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:affects"],
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:qualified_predicate",
                         "qualifier_value": "biolink:causes"},
                        # {"qualifier_type_id": "biolink:object_direction_qualifier",
                        #  "qualifier_value": "increased"},
                        # {"qualifier_type_id": "biolink:object_aspect_qualifier",
                        #  "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": [POS_REG_OF_MITOCHONDRIAL_DEPOL]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert MITOCHONDRIAL_DEPOLARIZATION in kg["nodes"]["n01"]


def test_25():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:has_participant"],  # This is the wrong regular predicate
            }
        },
        "nodes": {
            "n00": {
                "ids": [POS_REG_OF_MITOCHONDRIAL_DEPOL]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert MITOCHONDRIAL_DEPOLARIZATION not in kg["nodes"]["n01"]  # Its regular predicate is 'regulates'


def test_26():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:interacts_with"],  # This is the wrong regular predicate
                "qualifier_constraints": [
                    {"qualifier_set": [
                        # {"qualifier_type_id": "biolink:qualified_predicate",
                        #  "qualifier_value": "biolink:causes"},
                        {"qualifier_type_id": "biolink:object_direction_qualifier",
                         "qualifier_value": "increased"},
                        {"qualifier_type_id": "biolink:object_aspect_qualifier",
                         "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": [POS_REG_OF_MITOCHONDRIAL_DEPOL]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert not kg["nodes"] or MITOCHONDRIAL_DEPOLARIZATION not in kg["nodes"]["n01"]  # Its regular predicate is 'regulates'


def test_27():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:regulates"],
            }
        },
        "nodes": {
            "n00": {
                "ids": [POS_REG_OF_MITOCHONDRIAL_DEPOL]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert MITOCHONDRIAL_DEPOLARIZATION in kg["nodes"]["n01"]


def test_28():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:regulates"],
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:qualified_predicate",
                         "qualifier_value": "biolink:causes"},
                        {"qualifier_type_id": "biolink:object_direction_qualifier",
                         "qualifier_value": "decreased"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["CHEBI:94557"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert "NCBIGene:2554" in kg["nodes"]["n01"]


def test_29():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:qualified_predicate",
                         "qualifier_value": "biolink:causes"},
                        {"qualifier_type_id": "biolink:object_direction_qualifier",
                         "qualifier_value": "decreased"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["CHEBI:94557"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert "NCBIGene:2554" in kg["nodes"]["n01"]


def test_30():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:object_aspect_qualifier",
                         "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["CHEBI:90879"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }
    kg = _run_query(query)
    assert "NCBIGene:1890" in kg["nodes"]["n01"]


def test_31():
    # Test treats
    query = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [BIPOLAR_CURIE]
            },
            "n01": {
                "categories": ["biolink:Drug"]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n01"])


def test_32():
    # Test is_set handling
    query = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:related_to"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [DIABETES_CURIE]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        }
    }

    query["nodes"]["n00"]["is_set"] = True
    query["nodes"]["n01"]["is_set"] = True
    kg, trapi_response_issettrue = _run_query(query, return_trapi_response=True)
    results_issettrue = trapi_response_issettrue["message"].get("results")
    assert results_issettrue
    assert len(results_issettrue) == 1

    query["nodes"]["n00"]["is_set"] = False
    query["nodes"]["n01"]["is_set"] = True
    kg, trapi_response_objectset = _run_query(query, return_trapi_response=True)
    results_objectset = trapi_response_objectset["message"].get("results")
    assert results_objectset

    query["nodes"]["n00"]["is_set"] = True
    query["nodes"]["n01"]["is_set"] = False
    kg, trapi_response_subjectset = _run_query(query, return_trapi_response=True)
    results_subjectset = trapi_response_subjectset["message"].get("results")
    assert results_subjectset

    query["nodes"]["n00"]["is_set"] = False
    query["nodes"]["n01"]["is_set"] = False
    kg, trapi_response_issetfalse = _run_query(query, return_trapi_response=True)
    results_issetfalse = trapi_response_issetfalse["message"].get("results")
    assert results_issetfalse

    # _print_results(results_issettrue)
    # _print_results(results_objectset)
    # _print_results(results_subjectset)
    # _print_results(results_issetfalse)

    assert len(results_issetfalse) > len(results_subjectset) > len(results_objectset) > len(results_issettrue)

def test_undirected_related_to_for_underlying_treats_edge():
    """
    Make sure that when a related_to query comes in asking for an edge between two concepts that are connected
    only by a treats (or treats-ish) edge in the underlying graph, the query is answered in an undirected fashion.
    """
    query = {
        "edges": {
            "e00_1": {
                "object": "n00",
                "subject": "n00_1",
                "predicates": ["biolink:related_to"]
            }
        },
        "include_metadata": True,
        "nodes": {
            "n00": {
                "ids": [
                    "UMLS:C2931133"
                ]
            },
            "n00_1": {
                "ids": [
                    "UMLS:C0279936"
                ]
            }
        }
    }
    kg_1 = _run_query(query)
    assert kg_1["nodes"]["n00"] and kg_1["nodes"]["n00_1"]
    # Swap subject/object and make sure we get the same answers
    query["edges"]["e00_1"]["subject"] = "n00"
    query["edges"]["e00_1"]["object"] = "n00_1"
    kg_2 = _run_query(query)
    assert kg_2["nodes"]["n00"] and kg_2["nodes"]["n00_1"]
    assert len(kg_1["edges"]["e00_1"]) == len(kg_2["edges"]["e00_1"])
    assert len(kg_1["nodes"]["n00"]) == len(kg_2["nodes"]["n00_1"])
    assert len(kg_1["nodes"]["n00_1"]) == len(kg_2["nodes"]["n00"])

def test_version():
    # Print out the version of the KG2c being tested
    query = {
        "edges": {},
        "nodes": {
            "n00": {
                "ids": ["RTX:KG2c"]
            }
        }
    }
    kg = _run_query(query)
    print(kg)
    assert kg["nodes"]["n00"]


if __name__ == "__main__":
    pytest.main(['-v', 'test.py'])
