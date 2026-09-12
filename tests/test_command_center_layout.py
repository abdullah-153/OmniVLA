from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "cogniagent" / "gui" / "web"


def test_app_uses_chat_first_sessions_with_scoped_execution():
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    behavior = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for workspace in ("chat", "skills", "settings"):
        assert f'data-workspace-view="{workspace}"' in markup
    assert 'id="new-chat"' in markup
    assert 'id="chat-list"' in markup
    assert 'id="execution-panel"' in markup
    assert 'id="conversation"' in markup
    assert "isSelectedExecution" in behavior
    assert "execution_live" in behavior
    assert "DDR5" not in markup
    assert "RTX" not in markup
    assert "Holo" not in markup
    assert "Qwen" not in markup
    assert '<strong>OmniVLA</strong>' not in markup.split('<aside class="sidebar"', 1)[1].split('</aside>', 1)[0]
    assert "chat-row-delete" in behavior
    assert "data-plan-index" in behavior
    assert '"/api/plans/select"' in behavior


def test_execution_overlay_exposes_live_phase_signals_without_fake_progress():
    overlay_markup = (ROOT / "overlay-app" / "index.html").read_text(encoding="utf-8")
    renderer = (ROOT / "overlay-app" / "renderer.js").read_text(encoding="utf-8")

    assert 'id="phase-duration"' in overlay_markup
    assert 'id="beacon-toggle"' in overlay_markup
    assert overlay_markup.count('class="screen-edge ') == 4
    assert 'class="screen-edges"' in overlay_markup
    assert "formatElapsed" in renderer
    assert "data.steps" in renderer
    assert "max_steps" not in renderer


def test_service_worker_tracks_the_current_versioned_shell_assets():
    markup = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    worker = (WEB_ROOT / "sw.js").read_text(encoding="utf-8")

    assert "/assets/app.css?v=18" in markup
    assert "/assets/app.js?v=18" in markup
    assert "/assets/app.css?v=18" in worker
    assert "/assets/app.js?v=18" in worker


def test_overlay_is_excluded_from_capture_without_hide_show_flicker():
    overlay_main = (ROOT / "overlay-app" / "main.js").read_text(encoding="utf-8")
    vlm_engine = (ROOT / "cogniagent" / "perception" / "vlm_engine.py").read_text(encoding="utf-8")

    assert "setContentProtection(true)" in overlay_main
    assert "8082" not in overlay_main
    assert '127.0.0.1:8082' not in vlm_engine
    assert 'win.hide()' not in overlay_main
