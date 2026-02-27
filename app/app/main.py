import datetime
import gc
import json
import logging
import os
import sys
import traceback
from typing import NoReturn

import flask
from flask import send_file
from flask_cors import CORS
import pygit2

from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from . import plover

# Reserved path segments — must not be treated as KP endpoint names
_RESERVED_PATHS = frozenset({"debug", "get_logs", "logs", "code_version", "healthcheck"})

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
hide_traceback_in_errors = False
debug_snapshots_enabled = False

app = flask.Flask(__name__)
CORS(app)
_last_debug_snapshot: dict | None = None
_last_debug_timestamp: str | None = None

try:
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(plover.LOG_FILE_PATH)])
except OSError:
    alt_log_file_path = os.path.join(SCRIPT_DIR, "ploverdb.log")
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(alt_log_file_path)])

def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}

def load_plovers() -> tuple[dict[str, plover.PloverDB], str]:
    # Load a Plover for each KP (each KP has its own Plover config file - e.g., 'config_kg2c.json')
    config_files = sorted(
        fn for fn in os.listdir(f"{SCRIPT_DIR}/../")
        if fn.startswith("config") and fn.endswith(".json")
    )
    logging.info("Plover config files are %s", config_files)
    plover_endpoints_map: dict[str, plover.PloverDB] = {}
    for config_file_name in config_files:
        plover_obj = plover.PloverDB(config_file_name=config_file_name)
        plover_obj.load_indexes()
        plover_endpoints_map[plover_obj.endpoint_name] = plover_obj
    if not plover_endpoints_map:
        raise RuntimeError("No Plover config files found / no endpoints loaded")
    default_endpoint = sorted(list(plover_endpoints_map.keys()))[0]
    return plover_endpoints_map, default_endpoint


# Load a Plover object per KP/endpoint; these will be shared amongst workers
plover_objs_map, default_endpoint_name = load_plovers()
logging.info("Plover objs map keys are: %s. Default endpoint is %s.",
             list(plover_objs_map), default_endpoint_name)

# Freeze all objects currently tracked by GC to preserve copy-on-write memory sharing.
# Without this, Python's reference counting modifies objects when they're accessed,
# causing copy-on-write pages to be copied to each worker's private memory.
# gc.freeze() moves objects to a permanent generation that GC ignores.
gc.freeze()
logging.info("Froze GC objects to preserve copy-on-write memory sharing across workers.")


def instrument(flask_app):
    """
    Adapted from Kevin Vizhalil's opentelemetry code in:
    RTXteam/RTX/code/UI/OpenAPI/python-flask-server/KG2/openapi_server/__main__.py
    """
    # First figure out what to call this service in jaeger
    default_infores = plover_objs_map[default_endpoint_name].kp_infores_curie
    default_infores_val = default_infores.split(":")[-1]
    app_name = default_infores_val \
        if len(plover_objs_map) == 1 else default_infores_val.split("-")[0]
    service_name = f"{app_name}-plover"
    logging.info("Service name for opentelemetry tracing is %s", service_name)

    # Then figure out which jaeger host to use
    domain_name_file_path = f"{SCRIPT_DIR}/../domain_name.txt"
    if os.path.exists(domain_name_file_path):
        with open(domain_name_file_path, "r", encoding="utf-8") as domain_name_file:
            domain_name = domain_name_file.read()
            logging.info("Domain name is: %s", domain_name)
    else:
        domain_name = None
    jaeger_host = "jaeger.rtx.ai" \
        if domain_name and "transltr.io" not in domain_name else "jaeger-otel-agent.sri"
    logging.info("jaeger host to use is %s", jaeger_host)

    tracer_provider = TracerProvider(
        resource=Resource.create({
            ResourceAttributes.SERVICE_NAME: service_name
        })
    )
    trace.set_tracer_provider(tracer_provider)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            JaegerExporter(
                agent_host_name=jaeger_host,
                agent_port=6831
            )
        )
    )
    # BatchSpanProcessor exports spans asynchronously, avoiding request-path stalls if the
    # collector/agent is slow/unreachable.
    FlaskInstrumentor().instrument_app(
        app=flask_app,
        tracer_provider=tracer_provider,
        excluded_urls="docs,get_logs,logs,code_version,debug,healthcheck"
    )



@app.get("/")
def get_home_page():
    endpoints_info = [
        (
            f"<li>"
            f"{plover_obj.kp_infores_curie}"
            f"{'*' if plover_obj.endpoint_name == default_endpoint_name else ''}: "
            f"<a href='/{kp_name}'>/{kp_name}</a>"
            f"</li>"
        )
        for kp_name, plover_obj in plover_objs_map.items()
    ]
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
            <p>Individual TRAPI APIs for the <b>{len(plover_objs_map)} knowledge graph(s)</b> hosted
            on this Plover instance are available at the following sub-endpoints:
            <ul>{"".join(kp_endpoint_info for kp_endpoint_info in endpoints_info)}</ul>
            <i>* Default KP (i.e., can be accessed via <code>/query</code> or 
            <code>/{default_endpoint_name}/query</code>)</i></p>
            <h4>Other endpoints</h4>
            <p>Instance-level (as opposed to KP-level) endpoints helpful in debugging include:
                <ul>
                    <li><a href="/healthcheck">/healthcheck</a> (GET)</li>
                    <li><a href="/logs">/logs</a> (GET)</li>
                    <li><a href="/code_version">/code_version</a> (GET)</li>
                    <li><a href="/debug">/debug</a> (GET) - ownership, memory, kernel network, environment
                        info</li>
                    <li><a href="/debug/last">/debug/last</a> (GET) - cached snapshot (lightweight)</li>
                </ul>
            </p>
        </body>
        </html>
    """


def _tail_text_file(
        file_path: str,
        num_lines: int,
        *,
        max_bytes: int = 8 * 1024 * 1024
) -> list[str]:
    # Return last N lines without reading the full file into memory.
    # Used by /logs to avoid large allocations on big log files.
    if num_lines <= 0:
        return []

    try:
        # this seems weird for a text file, but "rb" is intentional since we are doing
        # byte-level chunk reads from the file; don't open as "rt" in this case
        with open(file_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            if file_size == 0:
                return []

            chunk_size = 64 * 1024
            bytes_read = 0
            data = b""

            # Read backwards until we have enough newlines or we hit the safety cap.
            read_limit = min(file_size, max_bytes)
            while bytes_read < read_limit and data.count(b"\n") < num_lines:
                to_read = min(chunk_size, file_size - bytes_read)
                bytes_read += to_read
                f.seek(file_size - bytes_read)
                data = f.read(to_read) + data

            lines = data.splitlines()
            tail = lines[-num_lines:]
            return [line.decode("utf-8", errors="replace") for line in tail]
    except OSError as e:
        return [f"[error reading file] {file_path}: {e}"]


@app.post("/<kp_endpoint_name>/query")
@app.post("/query")
def run_query(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        query = flask.request.json
        logging.info("%s: Received a TRAPI query", kp_endpoint_name)
        answer = plover_objs_map[kp_endpoint_name].answer_query(query)
        return flask.jsonify(answer)
    flask.abort(404,
                f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.post("/<kp_endpoint_name>/get_edges")
@app.post("/<kp_endpoint_name>/edges")
@app.post("/get_edges")
@app.post("/edges")
def get_edges(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        query = flask.request.json
        pairs = query['pairs']
        logging.info("%s: Received a query to get edges for %s node pairs",
                     kp_endpoint_name, len(pairs))
        answer = plover_objs_map[kp_endpoint_name].get_edges(pairs)
        return flask.jsonify(answer)
    flask.abort(404,
                f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


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
        logging.info("%s: Received a query to get neighbors for %s nodes",
                     kp_endpoint_name, len(node_ids))
        answer = plover_objs_map[kp_endpoint_name].get_neighbors(node_ids, categories, predicates)
        return flask.jsonify(answer)
    flask.abort(404,
                f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.get("/<kp_endpoint_name>/sri_test_triples")
@app.get("/sri_test_triples")
def get_sri_test_triples(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        with open(plover_objs_map[kp_endpoint_name].sri_test_triples_path,
                  "r", encoding="utf-8") as sri_test_file:
            sri_test_triples = json.load(sri_test_file)
        return flask.jsonify(sri_test_triples)
    flask.abort(404,
                f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.get("/<kp_endpoint_name>/meta_knowledge_graph")
@app.get("/meta_knowledge_graph")
def get_meta_knowledge_graph(kp_endpoint_name: str = default_endpoint_name):
    if kp_endpoint_name in plover_objs_map:
        return flask.jsonify(plover_objs_map[kp_endpoint_name].meta_kg)
    flask.abort(404,
                f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")


@app.get("/healthcheck")
def run_health_check():
    # Minimal health check - verifies the app is running and data is loaded
    if plover_objs_map and len(plover_objs_map) > 0:
        return flask.jsonify({"status": "healthy", "endpoints_loaded": len(plover_objs_map)})
    return flask.jsonify({"status": "unhealthy", "error": "No endpoints loaded"}), 503


def _read_proc_file(path: str) -> str | None:
    # Read a /proc file safely, return None if not available.
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def _get_memory_from_status(status_content: str) -> dict[str, float|int] | None:
    # Parse VmRSS and VmSize from /proc/<pid>/status content.
    if not status_content:
        return None

    mem_info: dict[str, float|int] = {}
    for line in status_content.split("\n"):
        if line.startswith("VmRSS:"):  # Resident Set Size (physical memory)
            rss_kb = int(line.split()[1])
            mem_info["rss_kb"] = rss_kb
            mem_info["rss_mb"] = round(rss_kb / 1024, 2)
        elif line.startswith("VmSize:"):  # Virtual memory size
            vms_kb = int(line.split()[1])
            mem_info["vms_kb"] = vms_kb
            mem_info["vms_mb"] = round(vms_kb / 1024, 2)
    return mem_info if mem_info else None


def _get_pss_kb(pid: int) -> int | None:
    # Read Proportional Set Size from /proc/<pid>/smaps_rollup (Linux 4.14+).
    # PSS divides shared pages proportionally among all processes that share
    # them, giving a much more accurate per-process memory picture than RSS
    # (which counts every shared page in full for every process).
    content = _read_proc_file(f"/proc/{pid}/smaps_rollup")
    if not content:
        return None
    for line in content.split("\n"):
        if line.startswith("Pss:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _get_all_workers_info(include_pss: bool = False) -> dict:
    # Get memory info for all uWSGI workers by reading /proc directly.
    # This avoids psutil overhead and keeps memory usage low.
    #
    # RSS is always included (fast — reads /proc/<pid>/status).
    # PSS is opt-in (slow — reads /proc/<pid>/smaps_rollup which forces the
    # kernel to walk every VMA; for 90 GB workers this can take 10+ seconds
    # per worker).  Request via /debug?pss=true.
    #
    #   RSS = includes shared CoW pages in every worker (inflated for forks)
    #   PSS = shared pages divided proportionally (accurate physical cost)
    my_pid = os.getpid()
    parent_pid = os.getppid()

    workers = []
    total_rss_kb = 0
    total_pss_kb = 0
    pss_available = False

    try:
        # Scan /proc for all process directories
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue

            pid = int(entry)
            stat_path = f"/proc/{pid}/stat"
            stat_content = _read_proc_file(stat_path)

            if not stat_content:
                continue

            # /proc/<pid>/stat format: pid (comm) state ppid ...
            # We need field 4 (ppid). Handle comm containing spaces/parens.
            try:
                # Find the closing paren of comm, then split the rest
                close_paren = stat_content.rfind(")")
                if close_paren == -1:
                    continue
                fields_after_comm = stat_content[close_paren + 2:].split()
                ppid = int(fields_after_comm[1])  # state is [0], ppid is [1]
            except (IndexError, ValueError):
                continue

            # Check if this process is a child of our parent (sibling worker)
            if ppid != parent_pid:
                continue

            # Get memory info for this worker
            status_content = _read_proc_file(f"/proc/{pid}/status")
            if status_content is not None:
                mem_info = _get_memory_from_status(status_content)
            else:
                mem_info = None
            if mem_info:
                rss_kb = int(mem_info.get("rss_kb", 0))
                total_rss_kb += rss_kb
                worker_info = {
                    "pid": pid,
                    "is_self": pid == my_pid,
                    "rss_mb": float(mem_info.get("rss_mb", 0.0)),
                }

                # PSS from smaps_rollup — only when explicitly requested
                # (very slow for large-memory workers: kernel walks all VMAs)
                if include_pss:
                    pss_kb = _get_pss_kb(pid)
                    if pss_kb is not None:
                        pss_available = True
                        total_pss_kb += pss_kb
                        worker_info["pss_mb"] = round(pss_kb / 1024, 2)

                workers.append(worker_info)
    except OSError:
        # /proc not available (non-Linux), return empty
        pass

    # Sort by PID for consistent output
    workers.sort(key=lambda w: w["pid"])

    result = {
        "master_pid": parent_pid,
        "worker_count": len(workers),
        "total_rss_mb": round(total_rss_kb / 1024, 2),
        "total_rss_gb": round(total_rss_kb / (1024 * 1024), 2),
        "workers": workers,
        "note": ("RSS is inflated for forked workers (shared CoW pages counted per-worker). "
                 "Use /debug?pss=true for PSS (proportional, accurate) — slow for large workers."),
    }

    if pss_available:
        result["total_pss_mb"] = round(total_pss_kb / 1024, 2)
        result["total_pss_gb"] = round(total_pss_kb / (1024 * 1024), 2)

    return result


def _get_container_memory_info() -> dict:
    # Read container memory limits and usage from cgroup files.
    cgroup_info: dict[str, int|float|str] = {}

    # Try cgroup v2 paths first, then v1
    paths = {
        "limit": ["/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"],
        "usage": ["/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"],
    }

    for key, path_list in paths.items():
        for path in path_list:
            val = _read_proc_file(path)
            if val:
                # "max" means unlimited in cgroup v2
                if val == "max":
                    cgroup_info[f"{key}_bytes"] = "unlimited"
                elif val.isdigit():
                    bytes_val = int(val)
                    cgroup_info[f"{key}_bytes"] = bytes_val
                    cgroup_info[f"{key}_gb"] = round(bytes_val / (1024 ** 3), 2)
                break

    return cgroup_info


def _get_ownership_info() -> dict:
    # Get ownership details for debugging permission issues (e.g., /code_version).
    uid = os.getuid()
    gid = os.getgid()
    home_dir = os.environ.get("HOME", "not set")
    git_dir = os.path.join(home_dir, ".git") if home_dir != "not set" else None

    info = {
        "process_uid": uid,
        "process_gid": gid,
        "home_dir": home_dir,
        "home_exists": os.path.isdir(home_dir) if home_dir != "not set" else False,
        "git_dir": git_dir,
        "git_exists": False,
        "git_owner_uid": None,
        "ownership_match": None,
    }

    if git_dir and os.path.isdir(git_dir):
        info["git_exists"] = True
        try:
            git_stat = os.stat(git_dir)
            info["git_owner_uid"] = git_stat.st_uid
            info["ownership_match"] = uid == git_stat.st_uid
        except OSError:
            pass

    return info


def _get_kernel_network_info() -> dict[str, str|int]:
    # Read kernel network parameters relevant to backpressure tuning.
    params = {
        "somaxconn": "/proc/sys/net/core/somaxconn",
        "tcp_max_syn_backlog": "/proc/sys/net/ipv4/tcp_max_syn_backlog",
        "netdev_max_backlog": "/proc/sys/net/core/netdev_max_backlog",
    }
    result: dict[str, str|int] = {}
    for name, path in params.items():
        val = _read_proc_file(path)
        if val and val.isdigit():
            result[name] = int(val)
        elif val:
            result[name] = val
    return result


def _capture_debug_snapshot(include_pss: bool = False) -> dict:
    # Capture a debug info snapshot. Used by /debug and startup cache.
    ownership = _get_ownership_info()
    all_workers = _get_all_workers_info(include_pss=include_pss)
    container_memory = _get_container_memory_info()
    kernel_network = _get_kernel_network_info()

    return {
        "ownership": ownership,
        "workers": all_workers,
        "container_limits": container_memory,
        "kernel_network": kernel_network,
        "environment": {
            "python_version": sys.version,
            "working_directory": os.getcwd(),
            "uwsgi_processes": os.environ.get("UWSGI_PROCESSES", "not set"),
            "uwsgi_cheaper": os.environ.get("UWSGI_CHEAPER", "not set"),
        },
        "app": {
            "endpoints_loaded": len(plover_objs_map),
            "endpoint_names": list(plover_objs_map.keys()),
        },
    }


@app.get("/debug")
def run_debug():
    # Debug endpoint providing ownership, memory, environment, and kernel network info.
    # Uses /proc and /sys reads to avoid psutil-related memory overhead.
    # Caches the result for the lightweight /debug/last endpoint.
    global _last_debug_snapshot, _last_debug_timestamp  # pylint: disable=global-statement
    if not debug_snapshots_enabled:
        flask.abort(404, "404 ERROR: debug snapshots are disabled by configuration.")
    try:
        include_pss = flask.request.args.get("pss", "").lower() in ("true", "1", "yes")
        snapshot = _capture_debug_snapshot(include_pss=include_pss)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        snapshot["captured_at"] = timestamp

        # Cache for /debug/last
        _last_debug_snapshot = snapshot
        _last_debug_timestamp = timestamp

        return flask.jsonify(snapshot)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return handle_internal_error(e)


@app.get("/debug/last")
def run_debug_last():
    if not debug_snapshots_enabled:
        flask.abort(404, "404 ERROR: debug snapshots are disabled.")
    if _last_debug_snapshot is None or \
       _last_debug_timestamp is None:
        flask.abort(404, "404 ERROR: no last debug snapshot available.")
    # Return the last cached debug snapshot. Lightweight -- no /proc scanning.
    # Useful when the server is under heavy load and /debug might be slow.
    return flask.jsonify({
        "snapshot": _last_debug_snapshot,
        "captured_at": _last_debug_timestamp,
        "note": "Cached from last /debug call (or startup). Call /debug for fresh data.",
    })


def handle_internal_error(e: Exception) -> NoReturn:
    if hide_traceback_in_errors:
        logging.exception("Internal error: %s", e)
        flask.abort(500, f"500 ERROR: {e}")
    tb = traceback.format_exc()
    logging.exception("Internal error (debug): %s", e)
    flask.abort(500, f"500 ERROR: {e}. Traceback: {tb}")


@app.get("/code_version")
def run_code_version():
    repo_path = pygit2.discover_repository(SCRIPT_DIR)
    if repo_path is None:
        return flask.jsonify({"code_info": "git repo not found"}), 200

    try:
        repo = pygit2.Repository(repo_path)
    except pygit2.GitError:
        return flask.jsonify({"code_info": "git repo could not be opened"}), 200

    # Branch / head label
    repo_head_name = "DETACHED" if repo.head_is_detached else repo.head.shorthand

    # Commit date (may be unavailable in empty repos)
    try:
        ts = repo.revparse_single("HEAD").commit_time
        date_str = str(datetime.date.fromtimestamp(ts))
    except pygit2.GitError:
        date_str = "UNKNOWN"

    response = {
        "code_info": f"HEAD: {repo_head_name}; Date: {date_str}",
        "endpoint_build_nodes": {
            endpoint_name: plover_obj.node_lookup_map["PloverDB"]
            for endpoint_name, plover_obj in plover_objs_map.items()
        },
    }
    return flask.jsonify(response), 200


@app.get("/get_logs")
@app.get("/logs")
def run_get_logs():
    try:
        requested_lines = flask.request.args.get("num_lines", "200")
        try:
            num_lines = int(requested_lines)
        except ValueError:
            num_lines = 200
        num_lines = max(1, min(num_lines, 2000))

        log_data_plover = _tail_text_file(plover.LOG_FILE_PATH, num_lines)
        log_data_uwsgi = _tail_text_file("/var/log/uwsgi.log", num_lines)
        response = {"description": f"The last {num_lines} lines from two logs (Plover and uwsgi) "
                                   f"are included below. You can control the number of lines shown "
                                   "with the "
                                   f"num_lines parameter (e.g., ?num_lines=500). Max is 2000.",
                    "plover": log_data_plover,
                    "uwsgi": log_data_uwsgi}
        return flask.jsonify(response)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return handle_internal_error(e)



@app.get("/<kp_endpoint_name>")
def get_kp_home_page(kp_endpoint_name: str):
    if kp_endpoint_name in _RESERVED_PATHS:
        flask.abort(404, f"404 ERROR: '{kp_endpoint_name}' is a reserved path segment.")
    if kp_endpoint_name in plover_objs_map:
        logging.info("%s: Going to homepage.", kp_endpoint_name)
        return send_file(plover_objs_map[kp_endpoint_name].kp_home_html_path, as_attachment=False)
    flask.abort(404,
                f"404 ERROR: Endpoint specified in request ('/{kp_endpoint_name}') does not exist")

if __name__ == "__main__":
    logging.info("Running as __main__ (dev server mode)")
    # Dev/test server only. In production use uWSGI/gunicorn.
    port = int(os.environ.get("PLOVER_PORT", "9990"))
    host = os.environ.get("PLOVER_HOST", "0.0.0.0")
    do_otel = _env_flag("PLOVER_OTEL", default=False)
    logging.info("PLOVER_OTEL=%r -> %s",
                 os.environ.get("PLOVER_OTEL"), do_otel)
    # when running the dev server (python -m / direct run), turn off telemetry by default
    if do_otel:
        logging.info("Enabling OpenTelemetry instrumentation")
        instrument(app)
    logging.info("Starting dev server (Flask built-in)")
    app.run(host=host, port=port, debug=False, use_reloader=False)
else:
    logging.info("Running under WSGI (imported module)")
    hide_traceback_in_errors = True
    logging.info("Traceback will be hidden from errors (production mode)")
    debug_snapshots_enabled = _env_flag("PLOVER_DEBUG_SNAPSHOTS", default=True)
    logging.info("PLOVER_DEBUG_SNAPSHOTS=%r -> %s",
                 os.environ.get("PLOVER_DEBUG_SNAPSHOTS"), debug_snapshots_enabled)
    # Cache for /debug/last: stores the most recent debug snapshot per worker.
    # Populated at startup and refreshed on each /debug call.
    if debug_snapshots_enabled:
        _last_debug_snapshot = _capture_debug_snapshot()
        _last_debug_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        logging.info("Captured startup debug snapshot for /debug/last.")
    do_otel = _env_flag("PLOVER_OTEL", default=True)
    logging.info("PLOVER_OTEL=%r -> %s",
                 os.environ.get("PLOVER_OTEL"), do_otel)
    # when running from docker, turn on telemetry by default, but
    # it can be turned off using the PLOVER_OTEL environment variable
    if do_otel:
        logging.info("Enabling OpenTelemetry instrumentation")
        instrument(app)
    logging.info("WSGI init complete (app object ready)")
