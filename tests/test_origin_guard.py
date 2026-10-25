from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from cleaner.config import CleanerConfig
from cleaner.origin_guard import origin_allowed, parse_origin_list, request_allowed
from cleaner.server import CleanerHandler


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:8092", "http://localhost:5173", "https://localhost", "http://[::1]:8092", "HTTP://LOCALHOST:8092/"],
)
def test_loopback_origins_are_allowed(origin: str) -> None:
    assert origin_allowed(origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://127.0.0.1.evil.example",
        "http://localhost.evil.example:8092",
        "http://127.0.0.1@evil.example",
        "http://evil.example#@127.0.0.1",
        "http://192.168.1.50:8092",
        "null",
        "file://",
        "http://127.0.0.1:8092/path",
        "",
    ],
)
def test_other_origins_are_rejected(origin: str) -> None:
    assert not origin_allowed(origin)


def test_listed_origins_are_allowed_exactly() -> None:
    extra = parse_origin_list("http://192.168.1.50:8092/, https://nas.example.ts.net")
    assert origin_allowed("http://192.168.1.50:8092", extra)
    assert origin_allowed("https://NAS.example.ts.net", extra)
    assert not origin_allowed("http://192.168.1.50:9999", extra)


def test_only_changing_methods_are_checked_and_missing_origin_passes() -> None:
    assert request_allowed("GET", "https://evil.example", None) == (True, "")
    assert request_allowed("POST", "https://evil.example", None)[0] is False
    assert request_allowed("POST", None, None) == (True, "")
    assert request_allowed("POST", None, "cross-site")[0] is False


@contextmanager
def running_server(config: CleanerConfig):
    handler_cls = type("TestCleanerHandler", (CleanerHandler,), {"config": config})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(port: int, path: str, headers: dict[str, str] | None = None, body: bytes = b"") -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("POST", path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        connection.close()


def test_foreign_page_cannot_write_a_plan_or_start_an_execution(config, data_root: Path) -> None:
    with running_server(config) as port:
        status, payload = post(port, "/api/run-dry-plan", {"Origin": "https://evil.example"})
        assert status == 403 and payload["ok"] is False
        status, payload = post(
            port,
            "/api/execute",
            {"Origin": "http://evil.example:8092", "Content-Type": "application/json"},
            json.dumps({"run_id": "cleaner-20260101-000000"}).encode(),
        )
        assert status == 403 and payload["ok"] is False
        status, _ = post(port, "/api/ensure-folders", {"Origin": "null"})
        assert status == 403
    assert not config.cleaner_reports_dir.exists() or not any(config.cleaner_reports_dir.iterdir())


def test_refusing_a_request_that_has_a_body_is_always_a_clean_403(config, data_root: Path) -> None:
    # The server must read the body it is refusing; otherwise closing the socket with unread
    # data can reset the connection and the caller sees a network error instead of the 403.
    body = json.dumps({"run_id": "x" * 300_000}).encode()
    with running_server(config) as port:
        for _ in range(40):
            status, payload = post(
                port,
                "/api/execute",
                {"Origin": "https://evil.example", "Content-Type": "application/json"},
                body,
            )
            assert status == 403 and payload["ok"] is False


def test_dashboard_origin_and_plain_clients_still_work(config, data_root: Path) -> None:
    with running_server(config) as port:
        status, payload = post(port, "/api/run-dry-plan", {"Origin": f"http://127.0.0.1:{port}"})
        assert status == 200 and payload["ok"] is True
        status, _ = post(port, "/api/run-dry-plan")
        assert status == 200
        # Execution is disabled in this config; the guard lets it through to that answer.
        status, payload = post(port, "/api/execute", {"Origin": f"http://localhost:{port}"}, b"{}")
        assert status == 409 and "report-only" in payload["error"]


def test_listed_lan_origin_is_accepted(config, data_root: Path) -> None:
    from dataclasses import replace

    lan = replace(config, allowed_origins=parse_origin_list("http://192.168.1.50:8092"))
    with running_server(lan) as port:
        status, _ = post(port, "/api/run-dry-plan", {"Origin": "http://192.168.1.50:8092"})
        assert status == 200
        status, _ = post(port, "/api/run-dry-plan", {"Origin": "http://192.168.1.51:8092"})
        assert status == 403


def test_allowed_origins_setting_is_read_from_the_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://192.168.1.50:8092, https://nas.example.ts.net/")
    monkeypatch.chdir(tmp_path)
    assert CleanerConfig.from_env().allowed_origins == ("http://192.168.1.50:8092", "https://nas.example.ts.net")
