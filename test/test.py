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
    response = requests.post("http://localhost:9990/query/", json=trapi_qg, headers={'accept': 'application/json'})
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
             "predicate": "biolink:related_to"
          }
       },
       "nodes": {
          "n00": {
             "id": "CHEMBL.COMPOUND:CHEMBL411",
             "category": "biolink:ChemicalSubstance"
          },
          "n01": {
             "category": "biolink:ChemicalSubstance"
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
             "predicate": "biolink:related_to"
          }
       },
       "nodes": {
          "n00": {
             "id": "CHEMBL.COMPOUND:CHEMBL411",
             "category": "biolink:ChemicalSubstance"
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
             "id": "CHEMBL.COMPOUND:CHEMBL411",
             "category": "biolink:ChemicalSubstance"
          },
          "n01": {
              "category": "biolink:ChemicalSubstance"
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
             "id": "CHEMBL.COMPOUND:CHEMBL411"
          },
          "n01": {
              "category": ["biolink:Protein", "biolink:Procedure"]
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
                "predicate": ["biolink:physically_interacts_with", "biolink:related_to"]
            }
        },
        "nodes": {
            "n00": {
                "id": "CHEMBL.COMPOUND:CHEMBL25"
            },
            "n01": {
                "category": ["biolink:Protein", "biolink:Gene"]
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
                "id": "CHEMBL.COMPOUND:CHEMBL25"
            },
            "n01": {
                "id": "CHEMBL.COMPOUND:CHEMBL833"
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
                "id": ["CHEMBL.COMPOUND:CHEMBL25", "UniProtKB:P04070"]
            },
            "n01": {
            }
        }
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
                "id": "CHEMBL.COMPOUND:CHEMBL25"
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
                "id": ["CHEMBL.COMPOUND:CHEMBL25", "CHEMBL.COMPOUND:CHEMBL411"]
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
                "id": "CHEMBL.COMPOUND:CHEMBL25"
            },
            "n01": {
                "id": "CHEMBL.COMPOUND:CHEMBL411"
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
                "id": "CHEMBL.COMPOUND:CHEMBL25"
            },
            "n01": {
                "id": "CHEMBL.COMPOUND:CHEMBL411"
            }
        }
    }
    kg = _run_query(query)
    assert not kg


def test_12():
    # Test subject as input node with enforced direction
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01"
            }
        },
        "nodes": {
            "n00": {
                "id": "CHEMBL.COMPOUND:CHEMBL650"
            },
            "n01": {
            }
        },
        "include_metadata": True,
        "enforce_directionality": True
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    num_edges_enforce_direction_subject = len(kg['edges']['e00'])
    print(f"Got back {num_edges_enforce_direction_subject} edges")
    assert all(edge for edge in kg["edges"]["e00"].items() if edge[0] == "CHEMBL.COMPOUND:CHEMBL650")

    # Test object as input node with enforced direction
    query = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00"
            }
        },
        "nodes": {
            "n00": {
                "id": "CHEMBL.COMPOUND:CHEMBL650"
            },
            "n01": {
            }
        },
        "include_metadata": True,
        "enforce_directionality": True
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    num_edges_enforce_direction_object = len(kg['edges']['e00'])
    print(f"Got back {num_edges_enforce_direction_object} edges")
    assert all(edge for edge in kg["edges"]["e00"].items() if edge[1] == "CHEMBL.COMPOUND:CHEMBL650")

    # Test subject as input node with ignored direction
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01"
            }
        },
        "nodes": {
            "n00": {
                "id": "CHEMBL.COMPOUND:CHEMBL650"
            },
            "n01": {
            }
        },
        "include_metadata": True,
        "enforce_directionality": False
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    num_edges_ignore_direction_subject = len(kg['edges']['e00'])
    print(f"Got back {num_edges_ignore_direction_subject} edges")
    assert any(edge for edge in kg["edges"]["e00"].values() if edge[0] == "CHEMBL.COMPOUND:CHEMBL650")
    assert any(edge for edge in kg["edges"]["e00"].values() if edge[1] == "CHEMBL.COMPOUND:CHEMBL650")

    # Test object as input node with ignored direction
    query = {
        "edges": {
            "e00": {
                "subject": "n01",
                "object": "n00"
            }
        },
        "nodes": {
            "n00": {
                "id": "CHEMBL.COMPOUND:CHEMBL650"
            },
            "n01": {
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    num_edges_ignore_direction_object = len(kg['edges']['e00'])
    print(f"Got back {num_edges_ignore_direction_object} edges")
    assert any(edge for edge in kg["edges"]["e00"].values() if edge[0] == "CHEMBL.COMPOUND:CHEMBL650")
    assert any(edge for edge in kg["edges"]["e00"].values() if edge[1] == "CHEMBL.COMPOUND:CHEMBL650")

    # Final checks on edge counts to make sure all makes sense
    assert num_edges_ignore_direction_subject == num_edges_ignore_direction_object
    assert num_edges_enforce_direction_subject + num_edges_enforce_direction_object == num_edges_ignore_direction_object


def test_13():
    # TRAPI 1.1 property names
    query = {
        "edges": {
            "e00": {
                "subject": "n00",
                "object": "n01",
                "predicates": ["biolink:physically_interacts_with"]
            }
        },
        "nodes": {
            "n00": {
                "ids": ["CHEMBL.COMPOUND:CHEMBL25", "UniProtKB:P04070"]
            },
            "n01": {
                "categories": ["biolink:Protein"]
            }
        },
        "include_metadata": True
    }
    kg = _run_query(query)
    assert kg["nodes"]["n00"] and kg["nodes"]["n01"] and kg["edges"]["e00"]
    _print_kg(kg)


if __name__ == "__main__":
    pytest.main(['-v', 'test.py'])
