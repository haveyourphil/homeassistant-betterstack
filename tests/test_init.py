"""Exercise real HA entry setup/unload, timers, and global SDK ownership."""

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
import sentry_sdk
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.betterstack import async_setup_entry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util

from .conftest import DSN, INSTALLATION_ID


async def test_setup_reload_unload(hass, config_entry, sdk_client, metadata) -> None:
    original = config_entry.as_dict()
    factory = sentry_sdk.Client
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    runtime = config_entry.runtime_data
    assert runtime.client is sdk_client
    assert sentry_sdk.get_global_scope().client is sdk_client
    assert "betterstack" not in hass.data
    assert runtime.context.installation_id == INSTALLATION_ID
    assert "user" not in runtime.context.system_info
    assert "timezone" not in runtime.context.system_info
    assert len(runtime.cancel_callbacks) == 3
    kwargs = factory.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["include_local_variables"] is False
    assert kwargs["auto_enabling_integrations"] is False
    assert kwargs["trace_propagation_targets"] == []
    assert kwargs["max_breadcrumbs"] == 0
    assert kwargs["enable_logs"] is False
    assert {integration.identifier for integration in kwargs["integrations"]} == {
        "logging",
        "aiohttp",
    }

    before_send = kwargs["before_send"]
    assert before_send({"logger": "custom_components.example_custom"}, {}) is None
    hass.config_entries.async_update_entry(
        config_entry, options={"event_custom_components": True}
    )
    assert before_send({"logger": "custom_components.example_custom"}, {}) is not None
    assert factory.call_count == 1  # Options don't reload the SDK.

    for _ in range(3):
        assert await hass.config_entries.async_reload(config_entry.entry_id)
        assert not runtime.active
        assert runtime.client is None
        assert not runtime.cancel_callbacks
        assert before_send({"logger": "homeassistant.core"}, {}) is None
        runtime = config_entry.runtime_data
    assert factory.call_count == 4
    assert sdk_client.close.call_count == 3
    assert config_entry.unique_id == original["unique_id"]
    assert config_entry.data == original["data"]
    assert config_entry.version == original["version"]
    assert config_entry.options == {"event_custom_components": True}
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert sdk_client.close.call_count == 4
    assert not sentry_sdk.get_global_scope().client.is_active()


async def test_timers_and_startup_cleanup(
    hass, config_entry, sdk_client, metadata
) -> None:
    hass.set_state(CoreState.starting)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    runtime = config_entry.runtime_data
    baseline = metadata["system_info"].call_count
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert metadata["system_info"].call_count == baseline + 1
    for hour in range(1, 4):
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(hours=hour, seconds=10)
        )
        await hass.async_block_till_done()
    assert metadata["system_info"].call_count == baseline + 4
    assert len(runtime.cancel_callbacks) == 3
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    count = metadata["system_info"].call_count
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=24))
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert metadata["system_info"].call_count == count


async def test_shutdown(hass, config_entry, sdk_client) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert sdk_client.close.call_count == 1
    assert not config_entry.runtime_data.cancel_callbacks
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert sdk_client.close.call_count == 1


async def test_dont_detach_another_client(hass, config_entry, sdk_client) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    other = MagicMock()
    sentry_sdk.get_global_scope().set_client(other)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert sentry_sdk.get_global_scope().client is other
    other.close.assert_not_called()
    sdk_client.close.assert_called_once()


async def test_conflicting_client(hass, config_entry, sdk_client) -> None:
    other = MagicMock()
    sentry_sdk.get_global_scope().set_client(other)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert sentry_sdk.get_global_scope().client is other
    sentry_sdk.Client.assert_not_called()


@pytest.mark.parametrize("dsn", ["invalid", "https://secret@example.test/no-project"])
async def test_invalid_stored_dsn(hass, sdk_client, caplog, dsn) -> None:
    entry = MockConfigEntry(domain="betterstack", data={"dsn": dsn})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert dsn not in caplog.text
    assert "Invalid Better Stack DSN" in caplog.text
    sentry_sdk.Client.assert_not_called()


async def test_sdk_failure_hides_credentials(
    hass, config_entry, sdk_client, caplog
) -> None:
    sentry_sdk.Client.side_effect = ValueError(f"Do not log {DSN}")
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert DSN not in caplog.text
    assert "Unable to initialize" in caplog.text
    assert not sentry_sdk.get_global_scope().client.is_active()


async def test_cancelled_setup_closes_client(hass, config_entry, sdk_client) -> None:
    started = asyncio.Event()
    finish = hass.loop.create_future()

    def delayed_init(_init):
        started.set()
        return finish

    with patch.object(hass, "async_add_import_executor_job", side_effect=delayed_init):
        task = hass.async_create_task(async_setup_entry(hass, config_entry))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        finish.set_result((sdk_client, None))
        with pytest.raises(asyncio.CancelledError):
            await task
    sdk_client.close.assert_called_once_with(2.0)
    assert not sentry_sdk.get_global_scope().client.is_active()


async def test_real_sdk_reload(hass, config_entry) -> None:
    """Actual SDK hooks install once and retired transports never receive events."""
    import logging

    from sentry_sdk.transport import Transport

    client_class = sentry_sdk.Client
    transports = []

    class MemoryTransport(Transport):
        def __init__(self):
            super().__init__({"dsn": DSN})
            self.events = []
            self.killed = False

        def capture_envelope(self, envelope):
            self.events.extend(
                item.get_event() for item in envelope.items if item.type == "event"
            )

        def kill(self):
            self.killed = True

    def create_client(**kwargs):
        transport = MemoryTransport()
        transports.append(transport)
        return client_class(transport=transport, **kwargs)

    logger = logging.getLogger("homeassistant.components.light")
    with patch(
        "custom_components.betterstack.sentry_sdk.Client", side_effect=create_client
    ):
        patched_handler = None
        for _ in range(3):
            assert await hass.config_entries.async_setup(config_entry.entry_id)
            client = config_entry.runtime_data.client
            assert client.options["traces_sample_rate"] is None
            if patched_handler is None:
                patched_handler = logging.Logger.callHandlers
            assert logging.Logger.callHandlers is patched_handler
            # SDK callbacks can run on worker threads while HA keeps running.
            await hass.async_add_executor_job(logger.error, "Failure: %s", DSN)
            (event,) = transports[-1].events
            assert "test_application_key" not in str(event)
            assert event["user"] == {"id": INSTALLATION_ID}
            assert "request" not in event
            assert "server_name" not in event
            assert event["message"] == "Failure: [redacted]"
            assert not event.get("breadcrumbs", {}).get("values")
            assert "sys.argv" not in event.get("extra", {})
            assert await hass.config_entries.async_unload(config_entry.entry_id)
            assert client.transport is None
            assert transports[-1].killed
            logger.error("After unload")
        assert [len(transport.events) for transport in transports] == [1, 1, 1]


async def test_conflict_during_sdk_import(hass, config_entry, sdk_client) -> None:
    """A newly initialized client is closed if another client wins the race."""
    other = MagicMock()

    def initialize(**_kwargs):
        sentry_sdk.get_global_scope().set_client(other)
        return sdk_client

    sentry_sdk.Client.side_effect = initialize
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    sdk_client.close.assert_called_once_with(2.0)
    assert sentry_sdk.get_global_scope().client is other


async def test_configured_sentry_blocks_both_setup_orders(
    hass, config_entry, sdk_client
) -> None:
    """Do not take over logging while the built-in integration is still setting up."""
    other_entry = MockConfigEntry(domain="sentry", data={"dsn": DSN})
    other_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    sentry_sdk.Client.assert_not_called()


async def test_unload_cancels_pending_refresh(
    hass, config_entry, sdk_client, metadata
) -> None:
    """An in-flight refresh belongs to the entry and cannot outlive unload."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    pending = hass.loop.create_future()
    started = asyncio.Event()

    async def slow_refresh(_hass):
        started.set()
        return await pending

    metadata["system_info"].side_effect = slow_refresh
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, seconds=10))
    await started.wait()
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert pending.cancelled()


async def test_cancelled_initialization_failure_is_sanitized(
    hass, config_entry, sdk_client, caplog
) -> None:
    """The executor sanitizes failures before a cancelled future can log them."""
    started = asyncio.Event()
    finish = hass.loop.create_future()
    initialize = None
    sentry_sdk.Client.side_effect = ValueError(f"Do not log {DSN}")

    def delayed_init(init):
        nonlocal initialize
        initialize = init
        started.set()
        return finish

    with patch.object(hass, "async_add_import_executor_job", side_effect=delayed_init):
        task = hass.async_create_task(async_setup_entry(hass, config_entry))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        finish.set_result(initialize())
        with pytest.raises(asyncio.CancelledError):
            await task
    assert DSN not in caplog.text
    assert not sentry_sdk.get_global_scope().client.is_active()
