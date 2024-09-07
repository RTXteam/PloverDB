import json
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from plover_tester import PloverTester

tester = PloverTester(pytest.endpoint)


def test_1():
    # Simplest one-hop
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
             "ids": ["CHEBI:21563"]
          },
          "n01": {
             "categories": ["biolink:NamedThing"]
          }
       }
    }
    response = tester.run_query(query)


if __name__ == "__main__":
    pytest.main(['-v', 'test.py'])
