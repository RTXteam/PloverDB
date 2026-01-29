import json
import os
import pwd
import sys
import traceback
from typing import Tuple

import flask
from flask import send_file
from flask_cors import CORS
import psutil
import pygit2
import datetime
import logging

from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
# adding this comment to trigger a rebuild 
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


def instrument(flask_app):
    """
    Adapted from Kevin Vizhalil's opentelemetry code in:
    github.com/RTXteam/RTX/blob/master/code/UI/OpenAPI/python-flask-server/KG2/openapi_server/__main__.py
    """
    # First figure out what to call this service in jaeger
    default_infores = plover_objs_map[default_endpoint_name].kp_infores_curie
    default_infores_val = default_infores.split(":")[-1]
    app_name = default_infores_val if len(plover_objs_map) == 1 else default_infores_val.split("-")[0]
    service_name = f"{app_name}-plover"
    logging.info(f"Service name for opentelemetry tracing is {service_name}")

    # Then figure out which jaeger host to use
    domain_name_file_path = f"{SCRIPT_DIR}/../domain_name.txt"
    if os.path.exists(domain_name_file_path):
        with open(domain_name_file_path, "r") as domain_name_file:
            domain_name = domain_name_file.read()
            logging.info(f"Domain name is: {domain_name}")
    else:
        domain_name = None
    jaeger_host = "jaeger.rtx.ai" if domain_name and "transltr.io" not in domain_name else "jaeger-otel-agent.sri"
    logging.info(f"jaeger host to use is {jaeger_host}")

    trace.set_tracer_provider(TracerProvider(
        resource=Resource.create({
            ResourceAttributes.SERVICE_NAME: service_name
        })
    ))
    trace.get_tracer_provider().add_span_processor(
        SimpleSpanProcessor(
            JaegerExporter(
                        agent_host_name=jaeger_host,
                        agent_port=6831
            )
        )
    )
    tracer_provider = trace.get_tracer(__name__)
    FlaskInstrumentor().instrument_app(app=flask_app, tracer_provider=trace, excluded_urls="docs,get_logs,logs,code_version,debug,healthcheck")


instrument(app)


@app.get("/")
def get_home_page():
    endpoints_info = [(f"<li>{plover_obj.kp_infores_curie}{'*' if plover_obj.endpoint_name == default_endpoint_name else ''}:"
                       f" <a href='/{kp_name}'>/{kp_name}</a></li>")
                      for kp_name, plover_obj in plover_objs_map.items()]
    return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Plover API</title>
        </head>
        <body>
            <h2>Plover API</h2>
            <h4>Querying</h4>
            <p>Individual TRAPI APIs for the <b>{len(plover_objs_map)} knowledge graph(s)</b> hosted on this Plover 
            instance are available at the following sub-endpoints:
            <ul>{"".join(kp_endpoint_info for kp_endpoint_info in endpoints_info)}</ul>
            <i>* Default KP (i.e., can be accessed via <code>/query</code> or 
            <code>/{default_endpoint_name}/query</code>)</i></p>
            <h4>Other endpoints</h4>
            <p>Instance-level (as opposed to KP-level) endpoints helpful in debugging include:
                <ul>
                    <li><a href="/healthcheck">/healthcheck</a> (GET)</li>
                    <li><a href="/logs">/logs</a> (GET)</li>
                    <li><a href="/code_version">/code_version</a> (GET)</li>
                    <li><a href="/debug">/debug</a> (GET) - process identity, memory, ownership info</li>
                </ul>
            </p>
        </body>
        </html>
    """


@app.post("/<kp_endpoint_name>/query")
@app.post("/query")
def run_query(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        query = flask.request.json
        logging.info(f"{kp_endpoint_name}: Received a TRAPI query")
        answer = plover_objs_map[kp_endpoint_name].answer_query(query)
        return flask.jsonify(answer)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.post("/<kp_endpoint_name>/get_edges")
@app.post("/<kp_endpoint_name>/edges")
@app.post("/get_edges")
@app.post("/edges")
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
@app.post("/<kp_endpoint_name>/neighbors")
@app.post("/get_neighbors")
@app.post("/neighbors")
def get_neighbors(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        query = flask.request.json
        node_ids = query["node_ids"]
        categories = query.get("categories", ["biolink:NamedThing"])
        predicates = query.get("predicates", ["biolink:related_to"])
        logging.info(f"{kp_endpoint_name}: Received a query to get neighbors for {len(node_ids)} nodes")
        answer = plover_objs_map[kp_endpoint_name].get_neighbors(node_ids, categories, predicates)
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
    # Minimal health check - verifies the app is running and data is loaded
    if plover_objs_map and len(plover_objs_map) > 0:
        return flask.jsonify({"status": "healthy", "endpoints_loaded": len(plover_objs_map)})
    return flask.jsonify({"status": "unhealthy", "error": "No endpoints loaded"}), 503


def get_process_identity() -> dict:
    # Collect identity and ownership details needed for permission debugging.
    uid = os.getuid()
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:
        username = f"unknown (uid {uid})"

    home_dir = os.environ.get("HOME", "not set")
    home_exists = os.path.isdir(home_dir) if home_dir != "not set" else False
    git_dir = os.path.join(home_dir, ".git") if home_dir != "not set" else None
    git_exists = os.path.isdir(git_dir) if git_dir else False

    # Read .git ownership only when it exists.
    git_owner_uid = None
    git_owner_name = None
    if git_exists:
        git_stat = os.stat(git_dir)
        git_owner_uid = git_stat.st_uid
        try:
            git_owner_name = pwd.getpwuid(git_owner_uid).pw_name
        except KeyError:
            git_owner_name = f"unknown (uid {git_owner_uid})"

    return {
        "uid": uid,
        "username": username,
        "home": home_dir,
        "home_exists": home_exists,
        "git_dir": git_dir,
        "git_exists": git_exists,
        "git_owner_uid": git_owner_uid,
        "git_owner_name": git_owner_name,
        "ownership_match": uid == git_owner_uid if git_owner_uid is not None else None
    }


@app.get("/debug")
def run_debug():
    # Returns diagnostic info for debugging ownership/memory issues without Kubernetes access
    try:
        # Keep identity information in one place so /code_version can log it too.
        process_identity = get_process_identity()

        # Memory info
        process = psutil.Process()
        mem_info = process.memory_info()
        
        # System/container memory limits (cgroup v1 and v2)
        memory_limit = None
        for cgroup_path in ["/sys/fs/cgroup/memory/memory.limit_in_bytes",
                            "/sys/fs/cgroup/memory.max"]:
            if os.path.exists(cgroup_path):
                try:
                    with open(cgroup_path, "r") as f:
                        val = f.read().strip()
                        if val != "max":
                            memory_limit = int(val)
                except Exception:
                    pass
                break
        
        response = {
            "process_identity": process_identity,
            "memory": {
                "process_rss_bytes": mem_info.rss,
                "process_rss_mb": round(mem_info.rss / (1024 * 1024), 2),
                "process_vms_bytes": mem_info.vms,
                "process_vms_mb": round(mem_info.vms / (1024 * 1024), 2),
                "container_limit_bytes": memory_limit,
                "container_limit_gb": round(memory_limit / (1024 * 1024 * 1024), 2) if memory_limit else None
            },
            "environment": {
                "python_version": sys.version,
                "working_directory": os.getcwd(),
                "pid": os.getpid()
            }
        }
        return flask.jsonify(response)
    except Exception as e:
        handle_internal_error(e)


def handle_internal_error(e: Exception):
    tb = traceback.format_exc()
    error_msg = f"{e}. Traceback: {tb}"
    logging.error(error_msg)
    flask.abort(500, f"500 ERROR: {error_msg}")


@app.get("/code_version")
def run_code_version():
    try:
        # Log identity and ownership details for debugging in restricted environments.
        logging.info("code_version identity: %s", get_process_identity())
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
@app.get("/logs")
def run_get_logs():
    try:
        num_lines = int(flask.request.args.get('num_lines', 100))
        with open(plover.LOG_FILE_PATH, "r") as f:
            log_data_plover = f.readlines()
        with open('/var/log/gunicorn.log', 'r') as f:
            log_data_gunicorn = f.readlines()
        response = {"description": f"The last {num_lines} lines from two logs (Plover and gunicorn) "
                                   f"are included below. You can control the number of lines shown with the "
                                   f"num_lines parameter (e.g., ?num_lines=500).",
                    "plover": log_data_plover[-num_lines:],
                    "gunicorn": log_data_gunicorn[-num_lines:]}
        return flask.jsonify(response)
    except Exception as e:
        handle_internal_error(e)


@app.get("/<kp_endpoint_name>")
def get_kp_home_page(kp_endpoint_name: str):
    if kp_endpoint_name in plover_objs_map:
        logging.info(f"{kp_endpoint_name}: Going to homepage.")
        return send_file(plover_objs_map[kp_endpoint_name].kp_home_html_path, as_attachment=False)
    else:
        flask.abort(404, f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")
