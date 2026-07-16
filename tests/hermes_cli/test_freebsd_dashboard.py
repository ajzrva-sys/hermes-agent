"""Native headless behavior adapted from macosxgeek's PR #33487."""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.freebsd_only


@pytest.mark.parametrize("display", [None, "DISPLAY", "WAYLAND_DISPLAY"])
def test_dashboard_opens_only_with_a_display(monkeypatch, display):
    from hermes_cli import web_server_lifecycle as lifecycle

    for key in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(key, raising=False)
    if display:
        monkeypatch.setenv(display, "fixture-display")
    started = []
    monkeypatch.setattr(lifecycle.threading, "Thread", lambda **kw:
                        SimpleNamespace(start=lambda: started.append(kw)))
    lifecycle._maybe_open_browser("127.0.0.1", 8080, True, "")
    assert bool(started) is (display is not None)
    started.clear()
    lifecycle._maybe_open_browser("127.0.0.1", 8080, False, "")
    assert not started
