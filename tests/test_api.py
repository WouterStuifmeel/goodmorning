from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GOODMORNING_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("GOODMORNING_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    with TestClient(app) as c:
        yield c


def _poll_until_finished(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/episodes/{job_id}")
        assert resp.status_code == 200
        job = resp.json()["job"]
        if job["state"] in ("completed", "failed"):
            return job
        time.sleep(0.1)
    pytest.fail(f"job {job_id} did not finish within {timeout}s")


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_start_generation_and_poll_status(client: TestClient) -> None:
    source_facts = json.loads((FIXTURES_DIR / "source_facts.json").read_text())

    resp = client.post("/episodes", json={"source_facts": source_facts})
    assert resp.status_code == 200
    job_id = resp.json()["job"]["id"]

    job = _poll_until_finished(client, job_id)
    assert job["state"] == "completed", job.get("error")
    assert job["manifest"] is not None
    assert job["manifest"]["source_facts"]["location"] == "Utrecht"


def test_retry_without_force_returns_existing_job(client: TestClient) -> None:
    source_facts = json.loads((FIXTURES_DIR / "source_facts.json").read_text())

    first = client.post("/episodes", json={"source_facts": source_facts})
    first_job_id = first.json()["job"]["id"]
    _poll_until_finished(client, first_job_id)

    second = client.post("/episodes", json={"source_facts": source_facts})
    assert second.json()["job"]["id"] == first_job_id


def test_retry_with_force_starts_new_job(client: TestClient) -> None:
    source_facts = json.loads((FIXTURES_DIR / "source_facts.json").read_text())

    first = client.post("/episodes", json={"source_facts": source_facts})
    first_job_id = first.json()["job"]["id"]
    _poll_until_finished(client, first_job_id)

    second = client.post(
        "/episodes", json={"source_facts": source_facts, "force_regenerate": True}
    )
    second_job_id = second.json()["job"]["id"]
    assert second_job_id != first_job_id
    _poll_until_finished(client, second_job_id)


def test_unknown_job_returns_404(client: TestClient) -> None:
    resp = client.get("/episodes/does-not-exist")
    assert resp.status_code == 404
