import pytest

import tools.registry as registry_module
from tools.registry import ToolRegistry


@pytest.fixture
def isolated_registry(monkeypatch):
    monkeypatch.setattr(registry_module, "check_fn_cache_scope", lambda: None)
    registry_module.invalidate_check_fn_cache()
    yield ToolRegistry()
    registry_module.invalidate_check_fn_cache()


def register_probe(registry, name, probe):
    registry.register(
        name=name,
        toolset=name,
        schema={
            "name": name,
            "description": "Availability selection test",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=lambda args, **kwargs: "{}",
        check_fn=probe,
    )


def test_selected_toolsets_are_filtered_before_probing(isolated_registry):
    calls = []

    def included():
        calls.append("included")
        return True

    def excluded():
        calls.append("excluded")
        raise AssertionError("excluded probe must not execute")

    register_probe(isolated_registry, "included", included)
    register_probe(isolated_registry, "excluded", excluded)
    available, unavailable = isolated_registry.check_tool_availability(
        quiet=True, enabled_toolsets=["included"]
    )
    assert available == ["included"]
    assert unavailable == []
    assert calls == ["included"]


@pytest.mark.parametrize("selection", [[], ["not-registered"]])
def test_empty_or_unknown_selection_runs_no_probes(isolated_registry, selection):
    calls = []

    def probe():
        calls.append("called")
        return False

    register_probe(isolated_registry, "optional", probe)
    assert isolated_registry.check_tool_availability(
        enabled_toolsets=selection
    ) == ([], [])
    assert calls == []


def test_omitted_selection_keeps_global_diagnostics(isolated_registry):
    register_probe(isolated_registry, "available", lambda: True)
    register_probe(isolated_registry, "unavailable", lambda: False)
    available, unavailable = isolated_registry.check_tool_availability()
    assert available == ["available"]
    assert [item["name"] for item in unavailable] == ["unavailable"]
