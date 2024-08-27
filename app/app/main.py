import json
import os
import sys
import time
import pygit2
import datetime
import logging

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import plover


SCRIPT_DIR = f"{os.path.dirname(os.path.abspath(__file__))}"


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

plover_objs_map = dict()
config_files = {file_name for file_name in os.listdir(SCRIPT_DIR)
                if file_name.startswith("config") and file_name.endswith(".json")}
for config_file_name in config_files:
    plover_obj = plover.PloverDB(config_file_name=config_file_name)
    plover_obj.load_indexes()
    with open(f"{SCRIPT_DIR}/../{config_file_name}") as config_file:
        config_info = json.load(config_file)
    endpoint_name = config_info["endpoint_name"]
    plover_objs_map[endpoint_name] = plover_obj
logging.info(f"Plover objs map is: {plover_objs_map}")


@app.post("/{kp_endpoint_name}/query")
def run_query_for_endpoint(kp_endpoint_name: str, query: dict):
    logging.info(f"KP endpoint name is: {kp_endpoint_name}")
    logging.info(f"Query is: {query}")
    # TODO: Throw error if endpoint name isn't in map
    answer = plover_objs_map[kp_endpoint_name].answer_query(query)
    return answer


@app.post("/query")
def run_query_default(query: dict):
    logging.info(f"Query is: {query}")
    # Use the alphabetically-first endpoint
    kp_endpoint_name = sorted(list(plover_objs_map.keys()))[0]
    answer = plover_objs_map[kp_endpoint_name].answer_query(query)
    return answer


@app.get("/meta_knowledge_graph")
def get_meta_knowledge_graph():
    return plover_obj.meta_kg


@app.get("/healthcheck")
def run_health_check():
    return ''


def handle_internal_error(e: Exception):
    error_msg = str(e)
    logging.error(error_msg)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"500 ERROR: {error_msg}")


@app.get("/code_version")
def run_code_version():
    try:
        print(f"HOME: {os.environ['HOME']}", file=sys.stderr)
        repo = pygit2.Repository(os.environ["HOME"])
        repo_head_name = repo.head.name
        timestamp_int = repo.revparse_single("HEAD").commit_time
        date_str = str(datetime.date.fromtimestamp(timestamp_int))
        response = {"code_info": f"HEAD: {repo_head_name}; Date: {date_str}",
                    "build_node": plover_obj.node_lookup_map["PloverDB"]}
        return response
    except Exception as e:
        handle_internal_error(e)


@app.get("/{kp_endpoint_name}/get_logs")
def run_get_logs(kp_endpoint_name: str, num_lines: int = 100):
    try:
        with open(plover_objs_map[kp_endpoint_name].log_path, "r") as f:
            log_data_plover = f.readlines()
        with open("/var/log/gunicorn_error.log", "r") as f:
            log_data_gunicorn_error = f.readlines()
        with open("/var/log/gunicorn_access.log", "r") as f:
            log_data_gunicorn_access = f.readlines()
        response = {"description": f"The last {num_lines} lines from each of three logs (Plover, Gunicorn error, and "
                                   "Gunicorn access) are included below.",
                    "plover": log_data_plover[-num_lines:],
                    "gunicorn_error": log_data_gunicorn_error[-num_lines:],
                    "gunicorn_access": log_data_gunicorn_access[-num_lines:]}
        return response
    except Exception as e:
        handle_internal_error(e)


@app.get("/sri_test_triples")
def get_sri_test_triples():
    with open(plover_obj.sri_test_triples_path, "r") as sri_test_file:
        sri_test_triples = json.load(sri_test_file)
    return sri_test_triples
