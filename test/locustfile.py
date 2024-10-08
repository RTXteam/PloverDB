import argparse
import json
import random

import jsonlines
from locust import HttpUser, between, task


print(f"Loading all node IDs from file..")
with jsonlines.open(f"kg2c-2.10.1-v1.0-nodes-lite.jsonl") as reader:
    ALL_NODE_IDS = [row["id"] for row in reader]
print(f"Nodes file contains {len(ALL_NODE_IDS)} nodes")


class APIUser(HttpUser):
    @task
    def run_random_query(self):
        random_node_ids = random.sample(ALL_NODE_IDS, 10)
        qg = {"nodes": {"n00": {"ids": list(random_node_ids)}, "n01": {"categories": ["biolink:NamedThing"]}},
              "edges": {"e00": {"subject": "n00", "object": "n01"}}}
        query = {"message": {"query_graph": qg}}
        response = self.client.post(f"/query", data=json.dumps(query), headers={'content-type': 'application/json'})
        neighbor_ids = set(response.json().get("message", dict()).get("knowledge_graph", dict()).get("nodes",
                                                                                                     dict())) if response.ok else set()

    wait_time = between(5, 20)
