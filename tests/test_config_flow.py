"""Tests for the Crestron Home config and options flow helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import types
from typing import Any

from home_assistant_stubs import home_assistant_stubs

with home_assistant_stubs():
    from homeassistant.config_entries import ConfigEntry

    from custom_components.crestron_home.config_flow import CrestronHomeOptionsFlowHandler


@dataclass
class _SelectorValue:
    """Simple stand-in for Home Assistant selector option objects."""

    value: str
    label: str


def test_normalize_shade_id_from_string() -> None:
    """A plain string should be returned unchanged after stripping."""

    assert (
        CrestronHomeOptionsFlowHandler._normalize_shade_id("  shade-123  ")
        == "shade-123"
    )


def test_normalize_shade_id_from_mapping() -> None:
    """Mappings from selectors should prefer the 'value' entry."""

    assert (
        CrestronHomeOptionsFlowHandler._normalize_shade_id(
            {"value": "shade-456", "label": "Living Room"}
        )
        == "shade-456"
    )


def test_normalize_shade_id_from_object_value_attribute() -> None:
    """Selector option objects expose the identifier via the value attribute."""

    assert (
        CrestronHomeOptionsFlowHandler._normalize_shade_id(
            _SelectorValue("shade-789", "Kitchen")
        )
        == "shade-789"
    )


def test_normalize_shade_id_from_none() -> None:
    """None should be treated as an empty selection."""

    assert CrestronHomeOptionsFlowHandler._normalize_shade_id(None) == ""


def test_selector_value_from_mapping() -> None:
    """Selector helper should read the value entry when provided."""

    assert (
        CrestronHomeOptionsFlowHandler._selector_value(
            {"value": "option-123", "label": "Option"}
        )
        == "option-123"
    )


def test_selector_value_from_object_attribute() -> None:
    """Selector helper should read the value attribute on option objects."""

    option = _SelectorValue("option-456", "Label")
    assert CrestronHomeOptionsFlowHandler._selector_value(option) == "option-456"


def test_invert_from_form_handles_selector_mapping() -> None:
    """Selector payloads should be normalized before interpreting the invert choice."""

    assert (
        CrestronHomeOptionsFlowHandler._invert_from_form(
            {"value": "normal", "label": "Normal axis"}
        )
        is False
    )
    assert (
        CrestronHomeOptionsFlowHandler._invert_from_form(
            {"value": "inverted", "label": "Invert axis"}
        )
        is True
    )
    assert (
        CrestronHomeOptionsFlowHandler._invert_from_form(
            {"value": "default", "label": "Use global default"}
        )
        is None
    )


def test_options_root_menu_has_translations() -> None:
    """Each root menu option should have a matching translation entry."""

    config_entry = ConfigEntry()
    config_entry.options = {}
    config_entry.entry_id = "test-entry"

    handler = CrestronHomeOptionsFlowHandler(config_entry)
    handler.hass = types.SimpleNamespace(data={})

    captured: dict[str, Any] = {}

    def _capture_menu(**kwargs: Any) -> dict[str, str]:
        captured.update(kwargs)
        return {"type": "menu"}

    handler.async_show_menu = _capture_menu  # type: ignore[assignment]

    result = asyncio.run(handler.async_step_init())
    assert result == {"type": "menu"}
    assert captured["step_id"] == "init"

    menu_options = captured["menu_options"]
    assert isinstance(menu_options, list)
    assert "select_shade" in menu_options

    integration_root = Path(__file__).resolve().parents[1] / "custom_components" / "crestron_home"
    strings_path = integration_root / "strings.json"
    translations_path = integration_root / "translations" / "en.json"

    strings_data = json.loads(strings_path.read_text())
    en_data = json.loads(translations_path.read_text())
    step_strings = strings_data["options"]["step"]["init"]
    step_en = en_data["options"]["step"]["init"]
    menu_strings = step_strings["menu_options"]
    menu_en = step_en["menu_options"]
    descriptions_strings = step_strings.get("menu_option_descriptions", {})
    descriptions_en = step_en.get("menu_option_descriptions", {})

    for option in menu_options:
        assert option in menu_strings
        assert isinstance(menu_strings[option], str) and menu_strings[option]
        assert option in menu_en
        assert isinstance(menu_en[option], str) and menu_en[option]

    assert descriptions_strings["select_shade"] == "Open the manual calibration editor for one shade."
    assert descriptions_en["select_shade"] == "Open the manual calibration editor for one shade."
