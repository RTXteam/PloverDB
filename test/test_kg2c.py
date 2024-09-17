import json
import os
import sys
from collections import defaultdict

import pytest
import requests
from typing import Dict, Union, List

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover_tester import PloverTester

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

tester = PloverTester(endpoint=pytest.endpoint)


def test_simple():
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
             "ids": ["CHEBI:30797"]
          },
          "n01": {
             "categories": ["biolink:NamedThing"]
          }
       }
    }
    response = tester.run_query(query)


def test_unconstrained_output_node():
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
    response = tester.run_query(query)


def test_unconstrained_predicate():
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
    response = tester.run_query(query)


def test_multiple_output_categories():
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
    response = tester.run_query(query)


def test_multiple_predicates():
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
    response = tester.run_query(query)
    all_predicates = {edge["predicate"] for edge in response["message"]["knowledge_graph"]["edges"].values()}
    assert len(all_predicates) >= 2
    assert "biolink:physically_interacts_with" in all_predicates


def test_doubly_pinned_query():
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
    response = tester.run_query(query)


def test_multiple_input_ids():
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
    response = tester.run_query(query)
    assert tester.get_num_distinct_concepts(response, "n00") == 2


def test_single_node_query():
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE]
            }
        }
    }
    response = tester.run_query(query)
    assert tester.get_num_distinct_concepts(response, "n00") == 1


def test_single_node_query_with_multiple_ids():
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE, ACETAMINOPHEN_CURIE]
            }
        }
    }
    response = tester.run_query(query)
    assert tester.get_num_distinct_concepts(response, "n00") == 2


def test_catching_multihop_query():
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
    response = tester.run_query(query, should_produce_error=True)


def test_symmetric_predicate():
    # Make sure that symmetric predicates are answered in both directions (when subj/obj are swapped)
    ids = [ASPIRIN_CURIE, METHYLPREDNISOLONE_CURIE]
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
    response_a = tester.run_query(query)
    node_ids_a = set(response_a["message"]["knowledge_graph"]["nodes"])

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
    response_b = tester.run_query(query)
    node_ids_b = set(response_b["message"]["knowledge_graph"]["nodes"])
    assert node_ids_a == node_ids_b


def test_asymmetric_predicate_1():
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
    response = tester.run_query(query)
    # Make sure this edge wasn't fulfilled in the backwards direction
    n00_node_ids = tester.get_node_ids(response, "n00")
    assert all(edge["subject"] in n00_node_ids for edge in response["message"]["knowledge_graph"]["edges"].values())


def test_asymmetric_predicate_2():
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
    response = tester.run_query(query, should_produce_results=False)


def test_concept_subclasses_single_node_query():
    query_subclass = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [DIABETES_CURIE],
            }
        }
    }
    response = tester.run_query(query_subclass)
    assert tester.get_num_distinct_concepts(response, "n00") > 1


def test_mixins_in_query():
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
    response = tester.run_query(query)


def test_canonical_predicate_handling():
    # First run a query using the canonical version of a predicate
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
    response_canonical = tester.run_query(query_canonical)
    node_ids_canonical = set(response_canonical["message"]["knowledge_graph"]["nodes"])

    # Then make sure we get the same answers if we use the non-canonical version of that predicate
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
    response_non_canonical = tester.run_query(query_non_canonical)
    node_ids_non_canonical = set(response_non_canonical["message"]["knowledge_graph"]["nodes"])

    assert node_ids_canonical == node_ids_non_canonical


def test_hierarchical_category_reasoning():
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
    response = tester.run_query(query)
    n01_node_ids = tester.get_node_ids(response, "n01")
    assert any(node_id for node_id in n01_node_ids
               if "biolink:NamedThing" not in response["message"]["knowledge_graph"]["nodes"][node_id]["categories"])


def test_hierarchical_predicate_reasoning():
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
    response = tester.run_query(query)
    assert any(edge["predicate"] != "biolink:related_to"
               for edge in response["message"]["knowledge_graph"]["edges"].values())


def test_query_id_mapping_in_results():
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
    response = tester.run_query(query)
    assert tester.get_num_distinct_concepts(response, "n00") == 2
    assert any(node_id for node_id in response["message"]["knowledge_graph"]["nodes"]
               if DIABETES_T1_CURIE in tester.get_equivalent_curies(response, node_id))

    for result in response["message"]["results"]:
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
    response = tester.run_query(query)
    print(response["message"]["knowledge_graph"]["nodes"])


if __name__ == "__main__":
    pytest.main(['-v', 'test.py'])
