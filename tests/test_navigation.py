"""Static tests for Streamlit callable-page navigation configuration."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _keyword_value(call: ast.Call, keyword_name: str):
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def test_streamlit_pages_have_unique_url_paths_and_meet_setup_default():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    page_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Page"]

    url_paths = [ast.literal_eval(_keyword_value(call, "url_path")) for call in page_calls]
    defaults = [_keyword_value(call, "default") for call in page_calls]

    assert url_paths == ["meet-setup", "live-timing", "results"]
    assert len(url_paths) == len(set(url_paths))
    assert isinstance(defaults[0], ast.Constant) and defaults[0].value is True
    assert all(default is None for default in defaults[1:])


def test_callable_page_switches_use_registered_page_objects_not_file_paths():
    for relative_path in ["pages/meet_setup.py", "pages/live_timing.py"]:
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        switch_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "switch_page"
        ]
        assert switch_calls, f"Expected at least one switch_page call in {relative_path}"
        for call in switch_calls:
            assert call.args, "switch_page should receive a page argument"
            assert not isinstance(call.args[0], ast.Constant) or not str(call.args[0].value).startswith("pages/")
