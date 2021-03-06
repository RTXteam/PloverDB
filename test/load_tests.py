import json

from locust import HttpUser, between, task


class APIUser(HttpUser):
    wait_time = between(5, 15)

    @task
    def query(self):
        query = {
            "edges": {
                "e00": {
                    "subject": "n00",
                    "object": "n01",
                    "predicate": "related_to"
                }
            },
            "nodes": {
                "n00": {
                    "id": ["CHEMBL.COMPOUND:CHEMBL411", "CHEMBL.COMPOUND:CHEMBL:25"],
                    "category": "chemical_substance"
                },
                "n01": {
                }
            }
        }
        response = self.client.post("/query", data=json.dumps(query), headers={'content-type': 'application/json'},
                                    catch_response=True)
        print(response)
