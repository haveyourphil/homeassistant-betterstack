"""Test event filtering, privacy, and Better Stack title compatibility."""

from types import SimpleNamespace

import pytest

from custom_components.betterstack import EventContext, process_before_send
from homeassistant.helpers import entity_platform

from .conftest import DSN, INSTALLATION_ID


@pytest.fixture
def context() -> EventContext:
    """A precomputed event-loop snapshot."""
    return EventContext(
        channel="stable",
        installation_id=INSTALLATION_ID,
        system_info={"installation_type": "Home Assistant OS"},
        custom_components=frozenset({"example_custom"}),
        integrations=("light", "recorder"),
        secrets=(DSN, "test_application_key"),
    )


@pytest.mark.parametrize(
    ("logger", "options", "accepted", "tags"),
    [
        ("homeassistant", {}, True, {}),
        ("homeassistant.core", {}, True, {}),
        ("homeassistant.helpers.event", {}, True, {"helpers": "event"}),
        (
            "homeassistant.components.light.sensor",
            {},
            True,
            {"integration": "light", "platform": "sensor", "custom_component": "no"},
        ),
        ("custom_components.example_custom.sensor", {}, False, {}),
        (
            "custom_components.example_custom.sensor",
            {"event_custom_components": True},
            True,
            {"integration": "example_custom", "custom_component": "yes"},
        ),
        (
            "custom_components.new_custom.sensor",
            {"event_custom_components": True},
            True,
            {"integration": "new_custom", "custom_component": "yes"},
        ),
        ("homeassistant.components.example_custom", {}, False, {}),
        (
            "homeassistant.components.example_custom",
            {"event_custom_components": True},
            True,
            {"integration": "example_custom", "custom_component": "yes"},
        ),
        ("aiohttp.client", {}, False, {}),
        (
            "aiohttp.client",
            {"event_third_party_packages": True},
            True,
            {"package": "aiohttp"},
        ),
        ("custom_components.betterstack", {"event_custom_components": True}, False, {}),
        (
            "custom_components.betterstack.config_flow",
            {"event_custom_components": True},
            False,
            {},
        ),
        ("sentry_sdk.errors", {"event_third_party_packages": True}, False, {}),
    ],
)
def test_logger_filter(context, logger, options, accepted, tags) -> None:
    """Custom components and Python libraries have independent switches."""
    result = process_before_send(options, context, {"logger": logger}, {})
    assert (result is not None) is accepted
    if result:
        assert result["tags"].items() >= tags.items()


@pytest.mark.parametrize(
    "event",
    [
        {"tags": {"handled": "yes"}},
        {"exception": {"values": [{"mechanism": {"handled": True}}]}},
    ],
)
def test_handled_filter(context, event) -> None:
    """Respect both Home Assistant tags and Sentry exception mechanisms."""
    assert process_before_send({}, context, event, {}) is None
    assert process_before_send({"event_handled": True}, context, event, {}) is not None


def test_unhandled_exception_chain(context) -> None:
    event = {
        "exception": {
            "values": [
                {"mechanism": {"handled": True}},
                {"mechanism": {"handled": False}},
            ]
        }
    }
    assert process_before_send({}, context, event, {}) is not None


@pytest.mark.parametrize(
    ("module", "option"),
    [
        ("custom_components.example_custom", "event_custom_components"),
        ("aiohttp.client", "event_third_party_packages"),
    ],
)
def test_exception_without_logger(context, module, option) -> None:
    event = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {"module": "homeassistant.core"},
                            {"module": module},
                        ]
                    }
                }
            ]
        }
    }
    assert process_before_send({}, context, event, {}) is None
    assert process_before_send({option: True}, context, event, {}) is not None


def test_platform_context(context) -> None:
    token = entity_platform.current_platform.set(
        SimpleNamespace(platform_name="example_custom", domain="sensor")
    )
    try:
        assert (
            process_before_send({}, context, {"logger": "homeassistant.core"}, {})
            is None
        )
        result = process_before_send(
            {"event_custom_components": True},
            context,
            {"logger": "homeassistant.core"},
            {},
        )
        assert result["tags"]["integration"] == "example_custom"
        assert result["tags"]["custom_component"] == "yes"
    finally:
        entity_platform.current_platform.reset(token)


def test_privacy_and_formatted_title(context) -> None:
    event = {
        "logger": "homeassistant.core",
        "user": {"email": "private@example.test", "ip_address": "192.0.2.1"},
        "server_name": "private-host",
        "request": {"headers": {"Authorization": "secret"}},
        "extra": {
            "sys.argv": ["--password=private"],
            "dsn": DSN,
            "nested": [{"key": "test_application_key"}],
            "url": "https://unrelated:credential@example.test/path",
        },
        "logentry": {"message": "Error: %s", "formatted": f"Error: {DSN}"},
    }
    result = process_before_send({}, context, event, {})
    serialized = str(result)
    for secret in (
        DSN,
        "test_application_key",
        "private@example.test",
        "192.0.2.1",
        "private-host",
        "Authorization",
        "--password",
        "unrelated:credential",
    ):
        assert secret not in serialized
    assert result["user"] == {"id": INSTALLATION_ID}
    assert result["message"] == result["title"] == "Error: [redacted]"
    assert result["logentry"]["message"] == "Error: [redacted]"
    assert result["extra"]["log_template"] == "Error: %s"
    assert result["contexts"]["Home Assistant"]["integrations"] == "light\nrecorder"


def test_exception_title_unchanged(context) -> None:
    event = {
        "exception": {"values": []},
        "logentry": {"formatted": "keep exception title"},
    }
    result = process_before_send({}, context, event, {})
    assert "title" not in result


def test_empty_logentry(context) -> None:
    assert process_before_send({}, context, {"logentry": {}}, {}) is not None


def test_core_logger_with_custom_traceback(context) -> None:
    """A core logger cannot bypass the custom integration filter."""
    event = {
        "logger": "homeassistant.core",
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {"module": "homeassistant.core"},
                            {"module": "custom_components.example_custom.sensor"},
                        ]
                    }
                }
            ]
        },
    }
    assert process_before_send({}, context, event, {}) is None
    result = process_before_send({"event_custom_components": True}, context, event, {})
    assert result["tags"]["integration"] == "example_custom"
    assert result["tags"]["custom_component"] == "yes"


def test_hint_traceback_without_event_frames(context) -> None:
    """Exceptions without serialized frames still obey the Python-package filter."""
    import sys

    try:
        raise RuntimeError("synthetic exception")
    except RuntimeError:
        hint = {"exc_info": sys.exc_info()}
        assert process_before_send({}, context, {}, hint) is None
        result = process_before_send(
            {"event_third_party_packages": True}, context, {}, hint
        )
    assert result["tags"]["package"] == "tests"


def test_own_exception_from_core_logger_is_excluded(context) -> None:
    event = {
        "logger": "homeassistant.core",
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {"module": "custom_components.betterstack"},
                        ]
                    }
                }
            ]
        },
    }
    assert (
        process_before_send({"event_custom_components": True}, context, event, {})
        is None
    )
