"""The Better Stack error tracking integration."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    __version__ as current_version,
)
from homeassistant.core import HomeAssistant, get_release_channel
from homeassistant.helpers import entity_platform, instance_id
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.system_info import async_get_system_info
from homeassistant.loader import Integration, async_get_custom_components
from homeassistant.setup import SetupPhases, async_pause_setup

from .const import (
    CONF_DSN,
    CONF_ENVIRONMENT,
    CONF_EVENT_CUSTOM_COMPONENTS,
    CONF_EVENT_HANDLED,
    CONF_EVENT_THIRD_PARTY_PACKAGES,
    CONF_LOGGING_EVENT_LEVEL,
    DEFAULT_LOGGING_EVENT_LEVEL,
    DOMAIN,
    ENTITY_COMPONENTS,
)

type BetterStackConfigEntry = ConfigEntry[dict[str, Any]]

LOGGER_INFO_REGEX = re.compile(r"^(\w+)\.?(\w+)?\.?(\w+)?\.?(\w+)?(?:\..*)?$")


async def async_setup_entry(
    hass: HomeAssistant, entry: BetterStackConfigEntry
) -> bool:
    """Set up Better Stack error tracking from a config entry."""
    sentry_logging = LoggingIntegration(
        level=None,
        event_level=entry.options.get(
            CONF_LOGGING_EVENT_LEVEL, DEFAULT_LOGGING_EVENT_LEVEL
        ),
    )

    channel = get_release_channel()
    huuid = await instance_id.async_get(hass)
    system_info = await async_get_system_info(hass)
    custom_components = await async_get_custom_components(hass)

    with async_pause_setup(hass, SetupPhases.WAIT_IMPORT_PACKAGES):

        def _init_sdk() -> Any:
            """Initialize the Sentry-compatible Better Stack SDK transport."""
            sentry_sdk.init(
                dsn=entry.data[CONF_DSN],
                environment=entry.options.get(CONF_ENVIRONMENT),
                integrations=[
                    sentry_logging,
                    AioHttpIntegration(),
                    SqlalchemyIntegration(),
                ],
                release=current_version,
                send_default_pii=False,
                before_send=lambda event, hint: process_before_send(
                    hass,
                    entry.options,
                    channel,
                    huuid,
                    system_info,
                    custom_components,
                    event,
                    hint,
                ),
            )
            return sentry_sdk.get_client()

        client = await hass.async_add_import_executor_job(_init_sdk)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client

    async def update_system_info(now: Any) -> None:
        nonlocal system_info
        system_info = await async_get_system_info(hass)

    async def update_system_info_later(now: Any) -> None:
        await update_system_info(now)
        entry.async_on_unload(
            async_call_later(hass, 3600, update_system_info_later)
        )

    entry.async_on_unload(async_call_later(hass, 3600, update_system_info_later))
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, update_system_info)
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BetterStackConfigEntry
) -> bool:
    """Unload Better Stack error tracking."""
    client = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if client is not None:

        def _close_sdk() -> None:
            if sentry_sdk.get_client() is client:
                sentry_sdk.get_global_scope().set_client(None)
            client.close(timeout=2.0)

        await hass.async_add_executor_job(_close_sdk)

    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)

    return True


def process_before_send(
    hass: HomeAssistant,
    options: Mapping[str, Any],
    channel: str,
    huuid: str,
    system_info: dict[str, bool | str],
    custom_components: dict[str, Integration],
    event: dict[str, Any],
    hint: dict[str, Any],
) -> dict[str, Any] | None:
    """Process a Better Stack error event before sending it."""
    if (
        "tags" in event
        and event["tags"].get("handled", "no") == "yes"
        and not options.get(CONF_EVENT_HANDLED)
    ):
        return None

    additional_tags = {
        "channel": channel,
        "installation_type": system_info["installation_type"],
        "uuid": huuid,
    }

    integrations = [
        integration
        for integration in hass.config.components
        if integration != "auth" and "." not in integration
    ]

    if (platform := entity_platform.current_platform.get()) is not None:
        additional_tags["custom_component"] = "no"
        additional_tags["integration"] = platform.platform_name
        additional_tags["platform"] = platform.domain
    elif "logger" in event:
        matches = LOGGER_INFO_REGEX.findall(event["logger"])
        if matches:
            group1, group2, group3, group4 = matches[0]
            if group1 == "homeassistant" and group2 and group3:
                if group2 == "components":
                    additional_tags["custom_component"] = "no"
                    additional_tags["integration"] = group3
                    if group4 and group4 in ENTITY_COMPONENTS:
                        additional_tags["platform"] = group4
                else:
                    additional_tags[group2] = group3
            else:
                if not options.get(CONF_EVENT_THIRD_PARTY_PACKAGES):
                    return None
                additional_tags["package"] = group1

    if (
        "integration" in additional_tags
        and additional_tags["integration"] in custom_components
    ):
        if not options.get(CONF_EVENT_CUSTOM_COMPONENTS):
            return None
        additional_tags["custom_component"] = "yes"

    event.setdefault("tags", {}).update(additional_tags)
    event.setdefault("user", {}).update({"id": huuid})
    event.setdefault("contexts", {}).update(
        {
            "Home Assistant": {
                "channel": channel,
                "custom_components": "\n".join(sorted(custom_components)),
                "integrations": "\n".join(sorted(integrations)),
                **system_info,
            },
        }
    )

    return event
