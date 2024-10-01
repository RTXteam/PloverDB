import json
import os
import sys
import traceback
from typing import Tuple

import flask
from flask import send_file
from flask_cors import CORS
import pygit2
import datetime
import logging

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import plover

SCRIPT_DIR = f"{os.path.dirname(os.path.abspath(__file__))}"

app = flask.Flask(__name__)
cors = CORS(app)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(plover.LOG_FILE_PATH)])


def load_plovers() -> Tuple[dict, str]:
    # Load a Plover for each KP (each KP has its own Plover config file - e.g., 'config_kg2c.json')
    config_files = {file_name for file_name in os.listdir(f"{SCRIPT_DIR}/../")
                    if file_name.startswith("config") and file_name.endswith(".json")}
    logging.info(f"Plover config files are {config_files}")
    plover_endpoints_map = dict()
    for config_file_name in config_files:
        plover_obj = plover.PloverDB(config_file_name=config_file_name)
        plover_obj.load_indexes()
        plover_endpoints_map[plover_obj.endpoint_name] = plover_obj
    default_endpoint = sorted(list(plover_endpoints_map.keys()))[0]
    return plover_endpoints_map, default_endpoint


# Load a Plover object per KP/endpoint; these will be shared amongst workers
plover_objs_map, default_endpoint_name = load_plovers()
logging.info(f"Plover objs map is: {plover_objs_map}. Default endpoint is {default_endpoint_name}.")


@app.post("/<kp_endpoint_name>/query")
@app.post("/query")
def run_query(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        query = flask.request.json
        logging.info(f"{kp_endpoint_name}: Received a query: {query}")
        answer = plover_objs_map[kp_endpoint_name].answer_query(query)
        return flask.jsonify(answer)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.post("/<kp_endpoint_name>/get_edges")
@app.post("/get_edges")
def get_edges(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        query = flask.request.json
        pairs = query['pairs']
        logging.info(f"{kp_endpoint_name}: Received a query to get edges for {len(pairs)} node pairs")
        answer = plover_objs_map[kp_endpoint_name].get_edges(pairs)
        return flask.jsonify(answer)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.post("/<kp_endpoint_name>/get_neighbors")
@app.post("/get_neighbors")
def get_neighbors(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        query = flask.request.json
        node_ids = query["node_ids"]
        categories = query.get("categories", ["biolink:NamedThing"])
        logging.info(f"{kp_endpoint_name}: Received a query to get neighbors for {len(node_ids)} nodes")
        answer = plover_objs_map[kp_endpoint_name].get_neighbors(node_ids, categories)
        return flask.jsonify(answer)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.get("/<kp_endpoint_name>/sri_test_triples")
@app.get("/sri_test_triples")
def get_sri_test_triples(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        with open(plover_objs_map[kp_endpoint_name].sri_test_triples_path, "r") as sri_test_file:
            sri_test_triples = json.load(sri_test_file)
        return flask.jsonify(sri_test_triples)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.get("/<kp_endpoint_name>/meta_knowledge_graph")
@app.get("/meta_knowledge_graph")
def get_meta_knowledge_graph(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        return flask.jsonify(plover_objs_map[kp_endpoint_name].meta_kg)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.get("/healthcheck")
def run_health_check():
    return ""


def handle_internal_error(e: Exception):
    tb = traceback.format_exc()
    error_msg = f"{e}. Traceback: {tb}"
    logging.error(error_msg)
    flask.abort(500, f"500 ERROR: {error_msg}")


@app.get("/code_version")
def run_code_version():
    try:
        print(f"HOME: {os.environ['HOME']}", file=sys.stderr)
        repo = pygit2.Repository(os.environ["HOME"])
        repo_head_name = repo.head.name
        timestamp_int = repo.revparse_single("HEAD").commit_time
        date_str = str(datetime.date.fromtimestamp(timestamp_int))
        response = {"code_info": f"HEAD: {repo_head_name}; Date: {date_str}",
                    "endpoint_build_nodes": {endpoint_name: plover_obj.node_lookup_map["PloverDB"]
                                             for endpoint_name, plover_obj in plover_objs_map.items()}}
        return response
    except Exception as e:
        handle_internal_error(e)


@app.get("/get_logs")
def run_get_logs(num_lines: int = 100):
    try:
        with open(plover.LOG_FILE_PATH, "r") as f:
            log_data_plover = f.readlines()
        with open('/var/log/uwsgi.log', 'r') as f:
            log_data_uwsgi = f.readlines()
        response = {"description": f"The last {num_lines} lines from each of three logs (Plover, Gunicorn error, and "
                                   "Gunicorn access) are included below.",
                    "plover": log_data_plover[-num_lines:],
                    "uwsgi": log_data_uwsgi[-num_lines:]}
        return flask.jsonify(response)
    except Exception as e:
        handle_internal_error(e)


@app.get("/<kp_endpoint_name>")
def get_home_page(kp_endpoint_name: str):
    if kp_endpoint_name in plover_objs_map:
        logging.info(f"{kp_endpoint_name}: Going to homepage.")
        return send_file(plover_objs_map[kp_endpoint_name].home_html_path, as_attachment=False)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")
