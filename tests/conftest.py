"""Shared fixtures for Better Stack tests; all network access is blocked by HA."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sentry_sdk
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

pytest_plugins = "pytest_homeassistant_custom_component"

DSN = "https://test_application_key@test.ingest.example/123"
INSTALLATION_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading this repository's custom integration."""


@pytest.fixture(autouse=True)
def restore_sentry_scope() -> Generator[None]:
    """Keep process-wide SDK state isolated between tests."""
    scope = sentry_sdk.get_global_scope()
    previous = scope.client
    scope.set_client(None)
    yield
    scope.set_client(previous)


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """An existing manually installed version-one entry."""
    entry = MockConfigEntry(
        domain="betterstack",
        title="Better Stack",
        version=1,
        unique_id="betterstack",
        data={"dsn": DSN},
        options={},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def sdk_client() -> Generator[MagicMock]:
    """Avoid starting a transport in tests that exercise HA lifecycle."""
    with patch("custom_components.betterstack.sentry_sdk.Client") as factory:
        yield factory.return_value


@pytest.fixture(autouse=True)
def metadata() -> Generator[dict[str, AsyncMock]]:
    """Make metadata deterministic and verify personal fields are excluded."""
    with (
        patch(
            "custom_components.betterstack.instance_id.async_get",
            return_value=INSTALLATION_ID,
        ) as installation_id,
        patch(
            "custom_components.betterstack.async_get_system_info",
            return_value={
                "installation_type": "Home Assistant OS",
                "version": "2026.10.4",
                "user": "private_username",
                "timezone": "Europe/London",
            },
        ) as system_info,
        patch(
            "custom_components.betterstack.async_get_custom_components",
            return_value={"example_custom": MagicMock()},
        ) as components,
    ):
        yield {
            "installation_id": installation_id,
            "system_info": system_info,
            "components": components,
        }
