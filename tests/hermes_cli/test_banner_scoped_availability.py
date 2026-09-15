import pytest

import model_tools
import tools.registry as registry_module
from hermes_cli.banner import compute_toolset_availability
from tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "selection, expected_calls, expected_names",
    [
        (["selected"], ["selected"], ["selected"]),
        ([], [], []),
        (None, ["other", "selected"], ["other", "selected"]),
    ],
)
def test_banner_only_probes_selected_toolsets(
    monkeypatch, selection, expected_calls, expected_names
):
    registry_module.invalidate_check_fn_cache()
    monkeypatch.setattr(registry_module, "check_fn_cache_scope", lambda: None)
    registry = ToolRegistry()
    calls = []

    def register(name):
        def probe():
            calls.append(name)
            return False

        registry.register(
            name=name,
            toolset=name,
            schema={
                "name": name,
                "description": "Banner availability test",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda args, **kwargs: "{}",
            check_fn=probe,
        )

    register("selected")
    register("other")
    monkeypatch.setattr(model_tools, "registry", registry)
    monkeypatch.setattr(model_tools, "TOOLSET_REQUIREMENTS", {})
    try:
        result = compute_toolset_availability(selection)
        assert calls == expected_calls
        assert [row["name"] for row in result["unavailable_toolsets"]] == expected_names
        assert result["disabled_tools"] == expected_names
    finally:
        registry_module.invalidate_check_fn_cache()
