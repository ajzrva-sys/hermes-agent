import logging

import pytest

import tools.registry as registry_module


@pytest.fixture(autouse=True)
def isolated_checks(monkeypatch):
    monkeypatch.setattr(registry_module, "check_fn_cache_scope", lambda: None)
    registry_module.invalidate_check_fn_cache()
    yield
    registry_module.invalidate_check_fn_cache()


def verdict_records(caplog):
    return [r for r in caplog.records if r.name == "tools.registry"]


def test_ordinary_unavailability_is_debug_and_cached(caplog):
    calls = []

    def probe():
        calls.append(1)
        return False

    with caplog.at_level(logging.DEBUG, logger="tools.registry"):
        assert registry_module._check_fn_cached(probe) is False
        assert registry_module._check_fn_cached(probe) is False
    records = verdict_records(caplog)
    assert calls == [1]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert records[0].exc_info is None
    assert "returned False" in records[0].getMessage()


def test_probe_exception_keeps_warning_and_traceback(caplog):
    def probe():
        raise RuntimeError("probe failure canary")

    with caplog.at_level(logging.DEBUG, logger="tools.registry"):
        assert registry_module._check_fn_cached(probe) is False
    records = verdict_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info[0] is RuntimeError


def test_transient_false_keeps_warning_and_last_good(monkeypatch, caplog):
    def probe():
        return False

    monkeypatch.setattr(registry_module.time, "monotonic", lambda: 100.0)
    registry_module._check_fn_last_good[(probe, None)] = 100.0
    with caplog.at_level(logging.DEBUG, logger="tools.registry"):
        assert registry_module._check_fn_cached(probe) is True
    records = verdict_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "transient" in records[0].getMessage()
