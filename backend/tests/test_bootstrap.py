import json
import logging

from egolabs import bootstrap
from egolabs.logs import JsonFormatter


def test_bootstrap_migrates_and_creates_buckets(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(bootstrap, "ensure_buckets", lambda: calls.append("buckets") or ["egolabs-raw"])
    bootstrap.main()  # database is already at head: the upgrade is a no-op, and must not fail
    assert calls == ["buckets"]


def test_bootstrap_retries_until_a_dependency_is_ready(monkeypatch):
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("not yet")
        return "ready"

    assert bootstrap._retry("storage", flaky, attempts=5) == "ready"
    assert attempts["n"] == 3


def test_json_log_lines_carry_extra_fields():
    record = logging.LogRecord("egolabs.jobs", logging.INFO, __file__, 1, "Job started", None, None)
    record.job_id = "abc"
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "Job started"
    assert line["level"] == "info"
    assert line["job_id"] == "abc"
