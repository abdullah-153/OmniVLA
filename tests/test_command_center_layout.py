from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "cogniagent" / "gui" / "web"


def test_command_center_uses_focused_workspaces_instead_of_a_dashboard():
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    behavior = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for workspace in ("command", "live", "history", "safety", "runtime"):
        assert f'data-view="{workspace}"' in markup
        assert f'data-view-target="{workspace}"' in markup

    assert 'data-view="workbench"' not in markup
    assert 'data-view="activity"' not in markup
    assert "Execution signal" in markup
    assert "Reviewed intent" in markup
    assert '["command", "live", "history", "safety", "runtime"]' in behavior
    assert 'openView("live")' in behavior


def test_execution_overlay_exposes_live_phase_signals_without_fake_progress():
    overlay_markup = (ROOT / "overlay-app" / "index.html").read_text(encoding="utf-8")
    renderer = (ROOT / "overlay-app" / "renderer.js").read_text(encoding="utf-8")

    assert 'id="phase-duration"' in overlay_markup
    assert "edge-runner" in overlay_markup
    assert "formatElapsed" in renderer
    assert "data.steps" in renderer
    assert "max_steps" not in renderer


def test_service_worker_tracks_the_current_versioned_shell_assets():
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    worker = (WEB_ROOT / "sw.js").read_text(encoding="utf-8")

    assert "/assets/app.css?v=4" in markup
    assert "/assets/app.js?v=4" in markup
    assert "/assets/app.css?v=4" in worker
    assert "/assets/app.js?v=4" in worker
