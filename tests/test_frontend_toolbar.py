from __future__ import annotations

from pathlib import Path

EXTENSION_PATH = Path(__file__).parents[1] / "web" / "character_reference.js"


def test_character_manager_uses_supported_comfy_topbar_button_api():
    source = EXTENSION_PATH.read_text(encoding="utf-8")

    assert 'from "../../scripts/ui/components/button.js"' in source
    assert "new ComfyButton({" in source
    assert "app.menu?.settingsGroup" in source
    assert "buttonGroup.append(button)" in source
    assert 'icon: "account-multiple"' in source
    assert 'tooltip: "Character Manager"' in source


def test_character_manager_topbar_button_is_safe_and_idempotent():
    source = EXTENSION_PATH.read_text(encoding="utf-8")

    assert 'TOPBAR_BUTTON_ID = "h3-character-manager-topbar-button"' in source
    assert "buttonGroup.buttons?.some" in source
    assert "document.getElementById(TOPBAR_BUTTON_ID)" in source
    assert 'window.open(url, "_blank", "noopener,noreferrer")' in source
    assert source.count("registerManagerTopbarButton();") == 1
