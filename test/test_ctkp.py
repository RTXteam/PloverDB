import json
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover_tester import PloverTester

tester = PloverTester(endpoint=pytest.endpoint, subendpoint="ctkp")


def test_1():
    # Simplest one-hop
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
             "ids": ["MONDO:0011438"]
          },
          "n01": {
             "categories": ["biolink:ChemicalEntity"]
          }
       }
    }
    response = tester.run_query(query)

    # Verify at least some edges have multiple supporting studies listed
    assert any(len(tester.get_supporting_study_attributes(edge)) > 1
               for edge in response["message"]["knowledge_graph"]["edges"].values())


if __name__ == "__main__":
    pytest.main(['-v', 'test.py'])
