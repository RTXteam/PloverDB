import pytest
import requests
from typing import Dict, Union, List


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
        return response.json()
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
             "ids": ["CHEMBL.COMPOUND:CHEMBL25"],
             "categories": ["biolink:ChemicalEntity"]
          },
          "n01": {
             "categories": ["biolink:ChemicalEntity"]
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


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
             "ids": ["CHEMBL.COMPOUND:CHEMBL25"],
             "categories": ["biolink:ChemicalEntity"]
          },
          "n01": {
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


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
             "ids": ["CHEMBL.COMPOUND:CHEMBL25"],
             "categories": ["biolink:ChemicalEntity"]
          },
          "n01": {
              "categories": ["biolink:ChemicalEntity"]
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


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
             "ids": ["CHEMBL.COMPOUND:CHEMBL25"]
          },
          "n01": {
              "categories": ["biolink:Protein", "biolink:Procedure"]
          }
       }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


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
                "ids": ["CHEMBL.COMPOUND:CHEMBL25"]
            },
            "n01": {
                "categories": ["biolink:Protein", "biolink:Gene"]
            }
        }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


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
                "ids": ["CHEMBL.COMPOUND:CHEMBL25"]
            },
            "n01": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL833", "CHEMBL.COMPOUND:CHEMBL4128999", "CHEMBL.COMPOUND:CHEMBL112"]
            }
        }
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


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
                "ids": ["CHEMBL.COMPOUND:CHEMBL25", "UniProtKB:P04070"]
            },
            "n01": {
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


def test_8():
    # Single-node query
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL25"]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) == 1
    _print_kg(kg)


def test_9():
    # Single-node query with multiple curies
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL25", "CHEMBL.COMPOUND:CHEMBL112"]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) == 2
    _print_kg(kg)


def test_10():
    # Edgeless query with multiple nodes
    query = {
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL25"]
            },
            "n01": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) == 1
    assert len(kg["nodes"]["n01"]) == 1
    _print_kg(kg)


def test_11():
    # Verify catches larger than one-hop query
    query = {
        "edges": {
            "e00": {},
            "e01": {}
        },
        "nodes": {
            "n00": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL25"]
            },
            "n01": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL411"]
            }
        }
    }
    kg = _run_query(query)
    assert not kg


def test_12():
    ids = ["CHEMBL.COMPOUND:CHEMBL25", "CHEMBL.COMPOUND:CHEMBL2106453"]
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
                "ids": ["UniProtKB:Q9BYZ6"]
            },
            "n01": {
                "categories": ["biolink:ChemicalEntity"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


def test_14():
    # Test subclass_of reasoning
    query_subclass = {
        "include_metadata": True,
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": ["MONDO:0005015"],  # Diabetes mellitus
                "allow_subclasses": True
            }
        }
    }
    kg = _run_query(query_subclass)
    assert len(kg["nodes"]["n00"]) > 1
    _print_kg(kg)
    query_no_subclass = {
        "include_metadata": True,
        "edges": {
        },
        "nodes": {
            "n00": {
                "ids": ["MONDO:0005015"]  # Diabetes mellitus
            }
        }
    }
    kg = _run_query(query_no_subclass)
    assert len(kg["nodes"]["n00"]) == 1
    _print_kg(kg)


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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        }
    }
    kg = _run_query(query)

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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
            },
            "n01": {
                "categories": ["biolink:Disease"]
            }
        },
        "respect_predicate_symmetry": True
    }
    kg_symmetry = _run_query(query_respecting_symmetry)

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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
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
                "ids": ["CHEMBL.COMPOUND:CHEMBL112"]
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
    diabetes_curie = "MONDO:0005015"
    type_1_diabetes_curie = "MONDO:0005147"
    type_2_diabetes_curie = "MONDO:0005148"
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
                "ids": [diabetes_curie, type_2_diabetes_curie],
                "allow_subclasses": True
            },
            "n01": {
                "categories": ["biolink:ChemicalEntity"]
            }
        }
    }
    kg = _run_query(query)
    assert len(kg["nodes"]["n00"]) > 1
    assert {diabetes_curie, type_1_diabetes_curie, type_2_diabetes_curie}.issubset(set(kg["nodes"]["n00"]))
    diabetes_node_tuple = kg["nodes"]["n00"][diabetes_curie]
    type_1_diabetes_node_tuple = kg["nodes"]["n00"][type_1_diabetes_curie]
    type_2_diabetes_node_tuple = kg["nodes"]["n00"][type_2_diabetes_curie]
    # Curies that appear in the QG should have no query_id listed
    assert not diabetes_node_tuple[-1]
    assert not type_2_diabetes_node_tuple[-1]
    # Descendant curies should indicate which QG curie they correspond to
    assert type_1_diabetes_node_tuple[-1] == [diabetes_curie]


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


# def test_qualifiers():
#     query = {
#         "include_metadata": True,
#         "edges": {
#             "e00": {
#                 "subject": "n00",
#                 "object": "n01",
#                 "predicates": ["biolink:interacts_with"],
#                 "qualifier_constraints": [
#                     {"qualifier_set": [
#                         # {"qualifier_type_id": "biolink:qualified_predicate",
#                         #  "qualifier_value": "biolink:causes"},
#                         # {"qualifier_type_id": "biolink:object_direction_qualifier",
#                         #  "qualifier_value": "increased"},
#                         {"qualifier_type_id": "biolink:object_aspect_qualifier",
#                          "qualifier_value": "localization"}
#                     ]}
#                 ]
#             }
#         },
#         "nodes": {
#             "n00": {
#                 "ids": ["MONDO:0005148"]
#             },
#             "n01": {
#                 "categories": ["biolink:BiologicalEntity"]
#             }
#         }
#     }
#     kg = _run_query(query)
#     print(kg)


if __name__ == "__main__":
    pytest.main(['-v', 'test.py'])
