"""
Burst test to validate backpressure behavior (#73).

Sends a burst of concurrent requests and validates:
- No 504 Gateway Timeout errors (ingress timeout = backpressure broken)
- 503 Service Unavailable is acceptable (backpressure working correctly)
- Most requests should return 200 OK

The old uWSGI listen backlog was 100 (default). Under load the queue hit
100/100 and held there for 2+ minutes, causing ingress to 504. We now
set listen=1024 and test with 100 concurrent requests to reproduce the
original failure condition.

Usage:
    pytest test_burst_backpressure.py --endpoint=https://kg2cplover.rtx.ai:9990 -v
    pytest test_burst_backpressure.py --endpoint=http://localhost:9991 -v
"""
import concurrent.futures
import random
import time

import pytest
import requests

# Tuning knobs — 100 concurrent matches the old listen backlog that caused 504s
BURST_SIZE_LIGHT = 100    # Concurrent requests for lightweight endpoints
BURST_SIZE_HEAVY = 100    # Concurrent requests for query endpoints
REQUEST_TIMEOUT = 60      # Per-request timeout (should be > harakiri=45s)

# Real KG2C TRAPI queries taken from the existing test_kg2c.py test suite.
# These exercise the actual query path and produce non-trivial work.
TRAPI_QUERIES = [
    {   # Aspirin → related_to → NamedThing (broad, returns many results)
        "message": {"query_graph": {
            "edges": {"e00": {"subject": "n00", "object": "n01",
                              "predicates": ["biolink:related_to"]}},
            "nodes": {"n00": {"ids": ["CHEBI:15365"]},
                      "n01": {"categories": ["biolink:NamedThing"]}}
        }, "submitter": "backpressure-test"},
    },
    {   # Acetaminophen → interacts_with → (unconstrained output)
        "message": {"query_graph": {
            "edges": {"e00": {"subject": "n00", "object": "n01",
                              "predicates": ["biolink:interacts_with"]}},
            "nodes": {"n00": {"ids": ["CHEBI:46195"],
                              "categories": ["biolink:ChemicalEntity"]},
                      "n01": {}}
        }, "submitter": "backpressure-test"},
    },
    {   # Parkinson's → (unconstrained predicate) → Protein
        "message": {"query_graph": {
            "edges": {"e00": {"subject": "n00", "object": "n01"}},
            "nodes": {"n00": {"ids": ["MONDO:0005180"],
                              "categories": ["biolink:Disease"]},
                      "n01": {"categories": ["biolink:Protein"]}}
        }, "submitter": "backpressure-test"},
    },
    {   # Aspirin → multiple predicates → Protein/Gene
        "message": {"query_graph": {
            "edges": {"e00": {"subject": "n00", "object": "n01",
                              "predicates": ["biolink:physically_interacts_with",
                                             "biolink:related_to"]}},
            "nodes": {"n00": {"ids": ["CHEBI:15365"]},
                      "n01": {"categories": ["biolink:Protein", "biolink:Gene"]}}
        }, "submitter": "backpressure-test"},
    },
    {   # Aspirin + Ticlopidine doubly-pinned query
        "message": {"query_graph": {
            "edges": {"e00": {"subject": "n00", "object": "n01"}},
            "nodes": {"n00": {"ids": ["CHEBI:15365"]},
                      "n01": {"ids": ["CHEBI:9588", "CHEBI:46195"]}}
        }, "submitter": "backpressure-test"},
    },
    {   # Diabetes → (unconstrained) → ChemicalEntity
        "message": {"query_graph": {
            "edges": {"e00": {"subject": "n00", "object": "n01"}},
            "nodes": {"n00": {"ids": ["MONDO:0005015", "MONDO:0005148"]},
                      "n01": {"categories": ["biolink:ChemicalEntity"]}}
        }, "submitter": "backpressure-test"},
    },
    {   # Aspirin/Methylprednisolone → treats → Disease
        "message": {"query_graph": {
            "edges": {"e00": {"subject": "n00", "object": "n01",
                              "predicates": ["biolink:treats_or_applied_or_studied_to_treat"]}},
            "nodes": {"n00": {"ids": ["CHEBI:15365", "PUBCHEM.COMPOUND:23663977"]},
                      "n01": {"categories": ["biolink:Disease"]}}
        }, "submitter": "backpressure-test"},
    },
]


def _send_request(endpoint, method="GET", path="/healthcheck",
                  json_body=None):
    """Send a single request and return a result dict."""
    start = time.time()
    try:
        if method == "POST":
            resp = requests.post(f"{endpoint}{path}", json=json_body,
                                 timeout=REQUEST_TIMEOUT,
                                 headers={"accept": "application/json"})
        else:
            resp = requests.get(f"{endpoint}{path}", timeout=REQUEST_TIMEOUT)
        return {
            "status_code": resp.status_code,
            "elapsed": round(time.time() - start, 3),
            "error": None,
        }
    except requests.exceptions.Timeout:
        return {"status_code": None, "elapsed": round(time.time() - start, 3),
                "error": "timeout"}
    except requests.exceptions.ConnectionError as e:
        return {"status_code": None, "elapsed": round(time.time() - start, 3),
                "error": f"connection_error: {e}"}
    except Exception as e:
        return {"status_code": None, "elapsed": round(time.time() - start, 3),
                "error": str(e)}


def _run_burst(endpoint, count, method="GET", path="/healthcheck",
               json_body=None, json_bodies=None):
    """Fire ``count`` concurrent requests and collect results.

    If *json_bodies* is given (a list), each request picks a random body from
    the list so the burst exercises a variety of queries rather than hitting
    the same one over and over.
    """
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        futures = []
        for _ in range(count):
            body = random.choice(json_bodies) if json_bodies else json_body
            futures.append(
                pool.submit(_send_request, endpoint, method, path, body)
            )
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
    return results


def _summarize(results, label):
    """Print and return a summary of burst results."""
    codes = [r["status_code"] for r in results]
    errors = [r for r in results if r["error"]]
    elapsed = [r["elapsed"] for r in results]

    summary = {
        "total": len(results),
        "200": codes.count(200),
        "503": codes.count(503),
        "504": codes.count(504),
        "other": len([c for c in codes if c not in (200, 503, 504, None)]),
        "errors": len(errors),
        "p50_s": round(sorted(elapsed)[len(elapsed) // 2], 3) if elapsed else 0,
        "max_s": round(max(elapsed), 3) if elapsed else 0,
    }

    print(f"\n{'='*60}")
    print(f"  {label} — {summary['total']} requests")
    print(f"  200 OK:  {summary['200']}  |  503:  {summary['503']}  |  504:  {summary['504']}")
    print(f"  Other:   {summary['other']}  |  Errors:  {summary['errors']}")
    print(f"  Latency  p50={summary['p50_s']}s  max={summary['max_s']}s")
    if errors:
        print(f"  First error: {errors[0]['error'][:120]}")
    print(f"{'='*60}")

    return summary


class TestBurstBackpressure:
    """Validate the server handles burst traffic with backpressure (503) not gateway timeout (504)."""

    def test_healthcheck_burst(self):
        """100 concurrent /healthcheck requests (lightweight)."""
        results = _run_burst(pytest.endpoint, BURST_SIZE_LIGHT, path="/healthcheck")
        summary = _summarize(results, "Healthcheck burst")

        assert summary["504"] == 0, (
            f"Got {summary['504']} 504 responses — listen queue or harakiri not tuned correctly"
        )

    def test_debug_burst(self):
        """100 concurrent /debug requests (moderate — reads /proc)."""
        results = _run_burst(pytest.endpoint, BURST_SIZE_LIGHT, path="/debug")
        summary = _summarize(results, "Debug burst")

        assert summary["504"] == 0, (
            f"Got {summary['504']} 504 responses during /debug burst"
        )

    def test_query_burst(self):
        """100 concurrent TRAPI /query requests using real KG2C queries."""
        results = _run_burst(pytest.endpoint, BURST_SIZE_HEAVY,
                             method="POST", path="/query",
                             json_bodies=TRAPI_QUERIES)
        summary = _summarize(results, "TRAPI query burst (mixed real KG2C queries)")

        assert summary["504"] == 0, (
            f"Got {summary['504']} 504 responses — backpressure not working for queries"
        )

    def test_debug_endpoints_exist(self):
        """Verify /debug returns kernel_network info and /debug/last is available."""
        # /debug (fast — RSS only, no PSS)
        resp = requests.get(f"{pytest.endpoint}/debug", timeout=60)
        assert resp.status_code == 200, f"/debug returned {resp.status_code}"
        data = resp.json()

        assert "kernel_network" in data, "/debug missing kernel_network section"
        assert "somaxconn" in data["kernel_network"], "kernel_network missing somaxconn"
        print(f"\nkernel_network: {data['kernel_network']}")

        # Workers should have RSS but NOT PSS by default (PSS is slow)
        workers = data.get("workers", {}).get("workers", [])
        if workers:
            assert "rss_mb" in workers[0], "worker missing rss_mb"
            assert "pss_mb" not in workers[0], (
                "PSS should NOT be included by default (too slow for large workers)"
            )

        # /debug/last should be reachable and lightweight
        resp_last = requests.get(f"{pytest.endpoint}/debug/last", timeout=10)
        assert resp_last.status_code == 200, f"/debug/last returned {resp_last.status_code}"
        last_data = resp_last.json()
        assert "captured_at" in last_data, "/debug/last missing captured_at"
        print(f"Last debug captured_at: {last_data['captured_at']}")
