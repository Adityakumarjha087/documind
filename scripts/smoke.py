#!/usr/bin/env python3
"""End-to-end smoke test of every major feature against a running DocuMind stack.

Usage:  python3 scripts/smoke.py [--api http://localhost:8000] [--web http://localhost:3000]
Stdlib only. Exits non-zero on the first failed check.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

PASS, FAIL = "\033[32m✔\033[0m", "\033[31m✘\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{PASS if ok else FAIL} {name}{' — ' + detail if detail else ''}")
    if not ok:
        summary()
        sys.exit(1)


def summary() -> None:
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def req(self, method: str, path: str, body: Any = None, raw: bytes | None = None,
            ctype: str | None = None) -> tuple[int, dict[str, str], bytes]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if ctype:
            headers["Content-Type"] = ctype
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()

    def json(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        code, _, data = self.req(method, path, body)
        return code, (json.loads(data) if data else None)

    def upload(self, path: str, name: str, content: bytes, strategy: str = "recursive") -> tuple[int, Any]:
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="chunk_strategy"\r\n\r\n{strategy}\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n".encode() + content + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        code, _, data = self.req("POST", path, raw=b"".join(parts),
                                 ctype=f"multipart/form-data; boundary={boundary}")
        return code, json.loads(data)

    def ask(self, ws: str, conv: str, q: str) -> list[tuple[str, Any]]:
        code, _, data = self.req("POST", f"/api/workspaces/{ws}/conversations/{conv}/messages",
                                 {"content": q})
        assert code == 200, (code, data[:200])
        events = []
        for block in data.decode().strip().split("\n\n"):
            fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
            events.append((fields["event"], json.loads(fields["data"])))
        return events


DOC = b"""# Smoke Test Handbook

## Leave
Employees receive 24 days of annual leave. Unused leave expires on March 31.

## Security
Lost laptops must be reported to the security desk within two hours.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--web", default="http://localhost:3000")
    args = ap.parse_args()
    api = Client(args.api)
    t0 = time.time()

    code, _, body = api.req("GET", "/health/ready")
    check("readiness probe (db + redis)", code == 200, body.decode()[:120])
    code, headers, _ = api.req("GET", "/health")
    check("security headers present", headers.get("x-content-type-options") == "nosniff")
    code, _, body = api.req("GET", "/openapi.json")
    check("OpenAPI schema served", code == 200 and b'"paths"' in body)

    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    code, tok = api.json("POST", "/api/auth/register",
                         {"email": email, "password": "smoke-pass-123", "full_name": "Smoke Test"})
    check("register", code == 201)
    code, again = api.json("POST", "/api/auth/register",
                           {"email": email, "password": "smoke-pass-123", "full_name": "X"})
    check("duplicate email rejected (409)", code == 409)
    api.token = tok["access_token"]
    code, rot = api.json("POST", "/api/auth/refresh", {"refresh_token": tok["refresh_token"]})
    check("refresh token rotation", code == 200 and rot["refresh_token"] != tok["refresh_token"])
    code, _ = api.json("POST", "/api/auth/refresh", {"refresh_token": tok["refresh_token"]})
    check("refresh token reuse detected (401)", code == 401)
    code, login = api.json("POST", "/api/auth/login", {"email": email, "password": "smoke-pass-123"})
    api.token = login["access_token"]
    check("login", code == 200)

    code, wss = api.json("GET", "/api/workspaces")
    ws = wss[0]["id"]
    check("default workspace created (owner)", code == 200 and wss[0]["role"] == "owner")

    code, doc = api.upload(f"/api/workspaces/{ws}/documents", "smoke.md", DOC)
    check("upload accepted (202)", code == 202)
    status = doc["status"]
    for _ in range(60):
        _, d = api.json("GET", f"/api/workspaces/{ws}/documents/{doc['id']}")
        status = d["status"]
        if status in ("ready", "failed"):
            break
        time.sleep(0.5)
    check("async ingestion via worker reaches ready", status == "ready",
          f"{d['num_chunks']} chunks, strategy={d['chunk_strategy']}")
    code, sem = api.upload(f"/api/workspaces/{ws}/documents", "smoke-semantic.md", DOC, "semantic")
    check("semantic chunking upload accepted", code == 202)
    code, _ = api.upload(f"/api/workspaces/{ws}/documents", "evil.exe", b"MZ")
    check("unsupported file type rejected (422)", code == 422)

    code, hits = api.json("POST", f"/api/workspaces/{ws}/search",
                          {"query": "how long to report a lost laptop", "top_k": 3})
    check("hybrid search returns relevant chunk", code == 200 and "two hours" in hits[0]["content"],
          f"score={hits[0]['score']}")

    _, conv = api.json("POST", f"/api/workspaces/{ws}/conversations", {})
    ev = api.ask(ws, conv["id"], "How many days of annual leave do employees receive?")
    answer = "".join(d["text"] for e, d in ev if e == "token")
    done = ev[-1][1]
    check("streamed answer is correct", "24 days" in answer, answer[:90])
    check("answer cites its source", any(c["cited"] for c in done["citations"]))
    ev = api.ask(ws, conv["id"], "and what about security?")
    rewrite = [d["query"] for e, d in ev if e == "rewrite"]
    answer = "".join(d["text"] for e, d in ev if e == "token")
    check("follow-up rewritten and answered", bool(rewrite) and "two hours" in answer, rewrite[0] if rewrite else "")
    ev = api.ask(ws, conv["id"], "What is the speed of light in a vacuum?")
    check("guardrail refuses out-of-scope question", ev[-1][1]["grounded"] is False)

    code, _ = api.json("PUT", f"/api/workspaces/{ws}/messages/{done['message_id']}/feedback", {"rating": 1})
    check("feedback stored", code == 204)

    code, run = api.json("POST", f"/api/workspaces/{ws}/evals", {
        "name": "smoke eval",
        "questions": [{"question": "How many days of annual leave do employees receive?",
                       "ground_truth": "Employees receive 24 days of annual leave."},
                      {"question": "Who won the 1966 world cup?"}]})
    check("evaluation run started", code == 202)
    for _ in range(60):
        _, r = api.json("GET", f"/api/workspaces/{ws}/evals/{run['id']}")
        if r["status"] != "running":
            break
        time.sleep(0.5)
    check("evaluation completed with metrics", r["status"] == "completed", json.dumps(r["summary"]))

    code, a = api.json("GET", f"/api/workspaces/{ws}/analytics?days=7")
    check("analytics reflect usage", code == 200 and a["total_queries"] >= 3 and a["feedback_up"] == 1,
          f"queries={a['total_queries']} p95={a['p95_latency_ms']}ms grounded={a['grounded_rate']}")

    other = Client(args.api)
    _, t2 = other.json("POST", "/api/auth/register", {"email": f"o-{uuid.uuid4().hex[:8]}@example.com",
                                                      "password": "smoke-pass-123", "full_name": "Other"})
    other.token = t2["access_token"]
    code, _ = other.json("GET", f"/api/workspaces/{ws}/documents/{doc['id']}")
    check("tenant isolation: other user gets 404", code == 404)

    code, _ = api.json("DELETE", f"/api/workspaces/{ws}/documents/{doc['id']}")
    check("document delete", code == 204)

    code, _, page = Client(args.web).req("GET", "/login")
    check("frontend serves login page", code == 200 and b"DocuMind" in page)

    print(f"\nTotal time {time.time() - t0:.1f}s")
    summary()


if __name__ == "__main__":
    main()
