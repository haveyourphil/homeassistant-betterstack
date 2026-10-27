"""Test config flow compatibility and immediate options."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, UnknownFlow

from .conftest import DSN


async def test_user_flow(hass: HomeAssistant) -> None:
    """Keep the original data schema, version, and unique ID for new entries."""
    result = await hass.config_entries.flow.async_init(
        "betterstack", context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.betterstack.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"dsn": DSN}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"dsn": DSN}
    assert result["result"].unique_id == "betterstack"
    assert result["result"].version == 1


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "not-a-dsn",
        "https://example.com/123",
        "https://key@example.com/not-a-project",
        "ftp://key@example.com/1",
    ],
)
async def test_invalid_dsn(hass: HomeAssistant, dsn: str) -> None:
    """Invalid DSNs stay in the form without including credentials in errors."""
    result = await hass.config_entries.flow.async_init(
        "betterstack", context={"source": config_entries.SOURCE_USER}, data={"dsn": dsn}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "bad_dsn"}


@pytest.mark.parametrize("unique_id", ["betterstack", None, "existing-legacy-id"])
async def test_single_entry(hass: HomeAssistant, unique_id: str | None) -> None:
    """The manifest enforces single-instance even for existing legacy entries."""
    entry = MockConfigEntry(
        domain="betterstack", data={"dsn": DSN}, unique_id=unique_id
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "betterstack", context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert entry.unique_id == unique_id


async def test_simultaneous_flows(hass: HomeAssistant) -> None:
    """Two open forms cannot create two entries."""
    flows = [
        await hass.config_entries.flow.async_init(
            "betterstack", context={"source": config_entries.SOURCE_USER}
        )
        for _ in range(2)
    ]
    with patch("custom_components.betterstack.async_setup_entry", return_value=True):
        first = await hass.config_entries.flow.async_configure(
            flows[0]["flow_id"], {"dsn": DSN}
        )
        # HA proactively aborts the other open single-instance flow.
        with pytest.raises(UnknownFlow):
            await hass.config_entries.flow.async_configure(
                flows[1]["flow_id"], {"dsn": DSN}
            )
        await hass.async_block_till_done()
    assert first["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries("betterstack")) == 1


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """The existing three boolean options retain their names and defaults."""
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    schema = result["data_schema"]
    defaults = schema({})
    assert defaults == {
        "event_handled": False,
        "event_custom_components": False,
        "event_third_party_packages": False,
    }
    options = dict.fromkeys(defaults, True)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == options
    assert config_entry.data == {"dsn": DSN}


async def test_reconfigure_dsn(hass, config_entry, sdk_client) -> None:
    """Rotate credentials without recreating the entry or changing its options."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    hass.config_entries.async_update_entry(
        config_entry, options={"event_handled": True}
    )
    old_id = config_entry.entry_id
    old_unique_id = config_entry.unique_id
    result = await hass.config_entries.flow.async_init(
        "betterstack",
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": old_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"dsn": "invalid"}
    )
    assert result["errors"] == {"base": "bad_dsn"}
    assert config_entry.data == {"dsn": DSN}
    new_dsn = "https://rotated_test_key@test.ingest.example/456"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"dsn": new_dsn}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.entry_id == old_id
    assert config_entry.unique_id == old_unique_id
    assert config_entry.data == {"dsn": new_dsn}
    assert config_entry.options == {"event_handled": True}
    sdk_client.close.assert_called_once()
