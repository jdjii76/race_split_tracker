"""Narrow Streamlit browser component for rerun-independent pack capture."""
from pathlib import Path
import streamlit.components.v1 as components

_component = components.declare_component("pack_capture", path=str(Path(__file__).parent / "frontend"))

def pack_capture(**kwargs):
    return _component(default={"events": [], "action": ""}, **kwargs)
