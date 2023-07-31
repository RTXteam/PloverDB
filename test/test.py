import pytest
import requests
from typing import Dict, Union, List


ASPIRIN_CURIE = "PUBCHEM.COMPOUND:2244"
TICLOPIDINE_CURIE = "PUBCHEM.COMPOUND:5472"
ACETAMINOPHEN_CURIE = "PUBCHEM.COMPOUND:1983"
PROC_CURIE = "NCBIGene:5624"
DIETHYLSTILBESTROL_CURIE = "PUBCHEM.COMPOUND:448537"
METHYLPREDNISOLONE_CURIE = "PUBCHEM.COMPOUND:23663977"
RHOBTB2_CURIE = "NCBIGene:23221"
DIABETES_CURIE = "MONDO:0005015"
DIABETES_T1_CURIE = "MONDO:0005147"
DIABETES_T2_CURIE = "MONDO:0005148"
CAUSES_INCREASE_CURIE = "GO:0051901"
INCREASED_CURIE = "GO:0051882"
PARKINSONS_CURIE = "MONDO:0005180"
BIPOLAR_CURIE = "MONDO:0004985"


def _print_kg(kg: Dict[str, Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]]):
    nodes_by_qg_id = kg["nodes"]
    edges_by_qg_id = kg["edges"]
    for qnode_key, node_ids in sorted(nodes_by_qg_id.items()):
        print(f"{qnode_key}: {node_ids}")
    for qedge_key, edge_ids in sorted(edges_by_qg_id.items()):
        print(f"{qedge_key}: {edge_ids}")


def _run_query(trapi_qg: Dict[str, Dict[str, Dict[str, Union[List[str], str, None]]]]):
    response = requests.post(f"{pytest.endpoint}/query", json=trapi_qg, headers={'accept': 'application/json'})
    if response.status_code == 200:
        json_response = response.json()
        _print_kg(json_response)
        return json_response
    else:
        print(f"Response status code was {response.status_code}. Response was: {response.text}")
        return dict()


def test_1():
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
    # Multiple curie to multiple curie query
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
        },
        "include_metadata": True
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


def test_10():
    # Edgeless query with multiple nodes
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [ASPIRIN_CURIE]
            },
            "n01": {
                "ids": [ACETAMINOPHEN_CURIE]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) == 1
    assert len(kg["nodes"]["n01"]) == 1


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


def test_12():
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
        },
        "include_metadata": True
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
        },
        "include_metadata": True
    }
    kg_symmetric_reversed = _run_query(query)

    assert kg_symmetric["nodes"]["n00"] and kg_symmetric["nodes"]["n01"] and kg_symmetric["edges"]["e00"]
    assert set(kg_symmetric["nodes"]["n01"]) == set(kg_symmetric_reversed["nodes"]["n01"])

    # Test treats only returns edges with direction matching QG
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:treats"]
            }
        },
        "nodes": {
            "n00": {
                "ids": ids
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        },
        "include_metadata": True
    }
    kg_asymmetric = _run_query(query)
    assert kg_asymmetric["nodes"]["n00"] and kg_asymmetric["nodes"]["n01"] and kg_asymmetric["edges"]["e00"]
    assert all(edge[0] in kg_asymmetric["nodes"]["n00"] for edge in kg_asymmetric["edges"]["e00"].values())

    # Test no edges are returned for backwards treats query
    query = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:treats"]
            }
        },
        "nodes": {
            "n00": {
                "ids": ids
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        },
        "include_metadata": True
    }
    kg_asymmetric_reversed = _run_query(query)
    assert not kg_asymmetric_reversed["edges"]["e00"]


def test_13():
    # TRAPI 1.1 property names
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
                "ids": [RHOBTB2_CURIE]
            },
            "n01": {
                "categories": ["biolink:ChemicalEntity"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]


def test_14():
    # Test subclass_of reasoning
    query_subclass = {
        "include_metadata": True,
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": [DIABETES_CURIE],  # Diabetes mellitus
                "allow_subclasses": True
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
                "predicates": ["biolink:treats"]
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
                "predicates": ["biolink:treats"]
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
                "predicates": ["biolink:treats"]
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
    query_non_canonical = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00",
                "predicates": ["biolink:treated_by"]
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
    kg_non_canonical = _run_query(query_non_canonical)
    assert len(kg_non_canonical["nodes"]["n01"])

    query_canonical = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:treats"]
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
    kg_canonical = _run_query(query_canonical)
    assert len(kg_canonical["nodes"]["n01"])

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
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n01"])
    assert any(node_tuple[1] != "biolink:NamedThing" for node_tuple in kg["nodes"]["n01"].values())


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
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert len(kg["edges"]["e00"])
    assert any(edge_tuple[2] != "biolink:related_to" for edge_tuple in kg["edges"]["e00"].values())


def test_20():
    # Test that the proper 'query_id' mapping (for TRAPI) is returned
    query = {
        "include_metadata": True,
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01"
            }
        },
        "nodes": {
            "n00": {
                "ids": [DIABETES_CURIE, DIABETES_T2_CURIE],
                "allow_subclasses": True
            },
            "n01": {
                "categories": ["biolink:ChemicalEntity"]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) > 1
    assert {DIABETES_CURIE, DIABETES_T1_CURIE, DIABETES_T2_CURIE}.issubset(set(kg["nodes"]["n00"]))
    diabetes_node_tuple = kg["nodes"]["n00"][DIABETES_CURIE]
    type_1_diabetes_node_tuple = kg["nodes"]["n00"][DIABETES_T1_CURIE]
    type_2_diabetes_node_tuple = kg["nodes"]["n00"][DIABETES_T2_CURIE]
    # Curies that appear in the QG should have no query_id listed
    assert not diabetes_node_tuple[-1]
    assert not type_2_diabetes_node_tuple[-1]
    # Descendant curies should indicate which QG curie they correspond to
    assert type_1_diabetes_node_tuple[-1] == [DIABETES_CURIE]


def test_21():
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
                        {"qualifier_type_id": "biolink:object_direction_qualifier",
                         "qualifier_value": "decreased"},
                        {"qualifier_type_id": "biolink:object_aspect_qualifier",
                         "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["PUBCHEM.COMPOUND:6323266"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert "NCBIGene:1890" in kg["nodes"]["n01"]


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
                "ids": ["PUBCHEM.COMPOUND:6323266"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
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
                "predicates": ["biolink:interacts_with"],  # This is the wrong regular predicate, but it shouldn't matter
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
                "ids": [CAUSES_INCREASE_CURIE]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert INCREASED_CURIE in kg["nodes"]["n01"]


def test_24():
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
                "ids": [CAUSES_INCREASE_CURIE]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert INCREASED_CURIE in kg["nodes"]["n01"]


def test_25():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:interacts_with"],  # This is the wrong regular predicate
            }
        },
        "nodes": {
            "n00": {
                "ids": [CAUSES_INCREASE_CURIE]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert INCREASED_CURIE not in kg["nodes"]["n01"]  # Its regular predicate is 'regulates'


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
                "ids": [CAUSES_INCREASE_CURIE]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert INCREASED_CURIE not in kg["nodes"]["n01"]  # Its regular predicate is 'regulates'


def test_27():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:regulates"],  # This is the correct regular predicate
            }
        },
        "nodes": {
            "n00": {
                "ids": [CAUSES_INCREASE_CURIE]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert INCREASED_CURIE in kg["nodes"]["n01"]


def test_28():
    # Test qualifiers
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:regulates"],  # This is the correct regular predicate
                "qualifier_constraints": [
                    {"qualifier_set": [
                        {"qualifier_type_id": "biolink:qualified_predicate",
                         "qualifier_value": "biolink:causes"},
                        {"qualifier_type_id": "biolink:object_direction_qualifier",
                         "qualifier_value": "decreased"},
                        {"qualifier_type_id": "biolink:object_aspect_qualifier",
                         "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["PUBCHEM.COMPOUND:6323266"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert "NCBIGene:1890" in kg["nodes"]["n01"]


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
                         "qualifier_value": "decreased"},
                        {"qualifier_type_id": "biolink:object_aspect_qualifier",
                         "qualifier_value": "activity_or_abundance"}
                    ]}
                ]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["PUBCHEM.COMPOUND:6323266"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert "NCBIGene:1890" in kg["nodes"]["n01"]


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
                "ids": ["PUBCHEM.COMPOUND:6323266"]
            },
            "n01": {
                "categories": ["biolink:NamedThing"]
            }
        },
        "include_metadata": True
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
                "predicates": ["biolink:treats"]
            }
        },
        "nodes": {
            "n00": {
                "ids": [BIPOLAR_CURIE]
            },
            "n01": {
                "categories": ["biolink:Drug"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n01"])


def test_version():
    # Print out the version of the KG2c being tested 
    query = {
        "edges": {},
        "nodes": {
            "n00": {
                "ids": ["RTX:KG2c"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    print(kg)
    assert kg["nodes"]["n00"]


if __name__ == "__main__":
    pytest.main(['-v', 'test.py'])
