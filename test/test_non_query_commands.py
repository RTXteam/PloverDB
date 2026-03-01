import pytest
import re
import requests
import datetime as dt


def _assert_iso8601(s: str) -> None:
    assert isinstance(s, str)
    # Your example is RFC3339-ish with a trailing "Z"/offset; fromisoformat handles "+00:00"
    # (If service ever returns "Z", you'll need s.replace("Z", "+00:00") here.)
    parsed = dt.datetime.fromisoformat(s)
    assert parsed.tzinfo is not None


def test_code_version():
    endpoint = pytest.endpoint
    response = requests.get(f"{endpoint}/code_version",
                            headers = {'accept': 'application/json'})
    assert response.ok
    json_response = response.json()
    # ---- top-level shape ----
    assert isinstance(json_response, dict)
    assert set(json_response.keys()) >= {"code_info", "endpoint_build_nodes"}

    code_info = json_response["code_info"]
    assert isinstance(code_info, str)
    assert code_info.strip()  # non-empty

    # Lightly validate code_info format (don't overfit)
    # Example: "HEAD: issue-66-steve-python3.12; Date: 2026-02-28"
    assert "HEAD:" in code_info
    assert "Date:" in code_info
    m = re.search(r"\bDate:\s*(\d{4}-\d{2}-\d{2})\b", code_info)
    assert m, f"code_info missing expected Date: YYYY-MM-DD pattern: {code_info!r}"

    endpoint_build_nodes_response = json_response["endpoint_build_nodes"]
    assert isinstance(endpoint_build_nodes_response, dict)
    assert endpoint_build_nodes_response  # not empty
    assert "kg2c" in endpoint_build_nodes_response

    kg2c_response = endpoint_build_nodes_response["kg2c"]
    assert isinstance(kg2c_response, dict)

    # ---- required keys and types ----
    for k in ("category", "description", "name", "biolink_version"):
        assert k in kg2c_response, f"Missing {k} in kg2c build node"
        assert isinstance(kg2c_response[k], str), f"{k} must be a string"

    # ---- stable invariants ----
    assert kg2c_response["category"] == "biolink:InformationContentEntity"
    assert kg2c_response["name"].startswith("Plover deployment of ")
    assert kg2c_response["biolink_version"]  # non-empty

    # biolink_version: keep it format-based, not pinned to a specific version
    assert re.fullmatch(r"\d+\.\d+\.\d+", kg2c_response["biolink_version"]), (
        f"Unexpected biolink_version format: {kg2c_response['biolink_version']!r}"
    )

    desc = kg2c_response["description"]
    assert desc.strip()

    # Description should mention "This Plover build was done on YYYY-MM-DD"
    assert "This Plover build was done on" in desc
    assert re.search(r"\bon\s+\d{4}-\d{2}-\d{2}\b", desc), (
        f"Description missing date: {desc!r}"
    )

    # Description should mention two input files (your service uses two quoted URLs/paths)
    # We'll just check that there are at least two quoted substrings.
    quoted = re.findall(r"'([^']+)'", desc)
    assert len(quoted) >= 2, f"Expected >=2 quoted file paths/URLs in description: {desc!r}"

    # Optional but useful: assert those look like URLs or absolute paths
    for q in quoted[:2]:
        assert q.startswith(("http://", "https://", "/")), f"Unexpected input file reference: {q!r}"

    # Optional: check that at least one looks like conflated nodes/edges (don’t overfit exact names)
    assert any("nodes" in q for q in quoted), f"No quoted input looks like nodes: {quoted!r}"
    assert any("edges" in q for q in quoted), f"No quoted input looks like edges: {quoted!r}"


def _validate_debug_response(json_response: dict) -> None:
    # Top-level shape
    assert isinstance(json_response, dict)
    for key in (
        "app",
        "captured_at",
        "container_limits",
        "environment",
        "kernel_network",
        "ownership",
        "workers",
    ):
        assert key in json_response

    # captured_at: present and parseable, timezone-aware
    _assert_iso8601(json_response["captured_at"])

    # app
    app = json_response["app"]
    assert isinstance(app, dict)
    assert isinstance(app.get("endpoint_names"), list)
    assert all(isinstance(x, str) for x in app["endpoint_names"])
    assert isinstance(app.get("endpoints_loaded"), int)
    assert app["endpoints_loaded"] >= 0
    # relationship check (safe)
    assert app["endpoints_loaded"] <= len(app["endpoint_names"])

    # container_limits
    cl = json_response["container_limits"]
    assert isinstance(cl, dict)
    assert "limit_bytes" in cl and "usage_bytes" in cl and "usage_gb" in cl
    assert isinstance(cl["limit_bytes"], str)  # often "unlimited"
    assert isinstance(cl["usage_bytes"], int)
    assert cl["usage_bytes"] >= 0
    assert isinstance(cl["usage_gb"], (int, float))
    assert cl["usage_gb"] >= 0

    # environment
    env = json_response["environment"]
    assert isinstance(env, dict)
    assert isinstance(env.get("python_version"), str)
    assert "3.12" in env["python_version"]  # if you want this strict; otherwise just assert non-empty
    assert isinstance(env.get("working_directory"), str)
    assert env["working_directory"].startswith("/")
    # uWSGI config values often come through as strings; accept either
    for k in ("uwsgi_cheaper", "uwsgi_processes"):
        assert k in env
        assert isinstance(env[k], (str, int))
        # if string, ensure it looks numeric
        if isinstance(env[k], str):
            assert env[k].isdigit()

    # kernel_network
    kn = json_response["kernel_network"]
    assert isinstance(kn, dict)
    for k in ("somaxconn", "tcp_max_syn_backlog"):
        assert k in kn
        assert isinstance(kn[k], int)
        assert kn[k] > 0

    # ownership
    own = json_response["ownership"]
    assert isinstance(own, dict)
    for k in (
        "git_dir",
        "git_exists",
        "home_dir",
        "home_exists",
        "ownership_match",
        "process_uid",
        "process_gid",
        "git_owner_uid",
    ):
        assert k in own
    assert isinstance(own["git_dir"], str)
    assert own["git_dir"].startswith("/")
    assert isinstance(own["git_exists"], bool)
    assert isinstance(own["home_dir"], str)
    assert own["home_dir"].startswith("/")
    assert isinstance(own["home_exists"], bool)
    assert isinstance(own["ownership_match"], bool)
    for k in ("process_uid", "process_gid", "git_owner_uid"):
        assert isinstance(own[k], int)
        assert own[k] >= 0

    # workers
    workers = json_response["workers"]
    assert isinstance(workers, dict)
    assert isinstance(workers.get("master_pid"), int)
    assert workers["master_pid"] > 0
    assert isinstance(workers.get("worker_count"), int)
    assert workers["worker_count"] >= 1

    worker_list = workers.get("workers")
    assert isinstance(worker_list, list)
    assert len(worker_list) == workers["worker_count"]

    # Validate each worker entry
    seen_self = 0
    pids = set()
    for w in worker_list:
        assert isinstance(w, dict)
        assert set(w.keys()) >= {"is_self", "pid", "rss_mb"}
        assert isinstance(w["is_self"], bool)
        assert isinstance(w["pid"], int)
        assert w["pid"] > 0
        assert isinstance(w["rss_mb"], (int, float))
        assert w["rss_mb"] >= 0
        pids.add(w["pid"])
        if w["is_self"]:
            seen_self += 1

    # Exactly one worker should be marked as "self"
    assert seen_self == 1
    # No duplicate PIDs
    assert len(pids) == len(worker_list)

    # Aggregate sanity checks (avoid exact numbers; just ensure types and non-negative)
    for k in ("total_rss_mb", "total_rss_gb"):
        assert k in workers
        assert isinstance(workers[k], (int, float))
        assert workers[k] >= 0

    # Optional: total_rss_mb should be >= max individual rss (should always hold)
    max_rss = max(w["rss_mb"] for w in worker_list) if worker_list else 0
    assert workers["total_rss_mb"] >= max_rss


def test_debug():
    endpoint = pytest.endpoint
    response = requests.get(f"{endpoint}/debug",
                            headers = {'accept': 'application/json'})
    assert response.ok
    json_response = response.json()
    _validate_debug_response(json_response)


def test_debug_last():
    endpoint = pytest.endpoint
    response = requests.get(f"{endpoint}/debug/last",
                            headers = {'accept': 'application/json'})
    assert response.ok
    json_response = response.json()
    assert 'captured_at' in json_response
    _assert_iso8601(json_response['captured_at'])
    assert 'note' in json_response
    assert 'snapshot' in json_response
    _validate_debug_response(json_response['snapshot'])
    
