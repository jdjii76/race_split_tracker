"""Streamlit regression tests for roster checkbox widget initialization."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).parent / "fixtures/roster_checkbox_app.py"


def _button(app, label):
    return next(item for item in app.button if item.label == label)


def _checks(app):
    return {item.label: item.value for item in app.checkbox}


def test_checkbox_workflow_never_mutates_an_instantiated_widget_key():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not app.exception
    assert _checks(app) == {"a1": True, "a2": False, "a3": False}

    app.run()
    assert not app.exception
    assert _checks(app)["a1"] is True

    _button(app, "Select All").click().run()
    assert not app.exception
    assert all(_checks(app).values())

    _button(app, "Clear").click().run()
    assert not app.exception
    assert not any(_checks(app).values())

    _button(app, "Reload Saved Race Roster").click().run()
    assert not app.exception
    assert _checks(app) == {"a1": True, "a2": False, "a3": False}


def test_race_switch_and_clean_persisted_refresh_are_isolated():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.selectbox(key="test_race").select("race-b").run()

    assert not app.exception
    assert _checks(app) == {"a1": False, "a2": True, "a3": False}

    app.session_state["test_persisted:race-b"] = ["a3"]
    app.run()

    assert not app.exception
    assert _checks(app) == {"a1": False, "a2": False, "a3": True}
