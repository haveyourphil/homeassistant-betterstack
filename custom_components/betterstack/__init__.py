"""The Better Stack error tracking integration."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.utils import BadDsn, Dsn

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.const import __version__ as current_version
from homeassistant.core import HomeAssistant, callback, get_release_channel
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_platform, instance_id
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.system_info import async_get_system_info
from homeassistant.loader import async_get_custom_components

from .const import (
    CONF_DSN,
    CONF_EVENT_CUSTOM_COMPONENTS,
    CONF_EVENT_HANDLED,
    CONF_EVENT_THIRD_PARTY_PACKAGES,
    DEFAULT_ENVIRONMENT,
    DOMAIN,
    ENTITY_COMPONENTS,
)

if TYPE_CHECKING:
    from sentry_sdk.types import Event as SentryEvent

# Exclude the OS username, timezone, and any future additions to the HA helper.
SYSTEM_INFO_FIELDS = frozenset(
    {
        "arch",
        "container_arch",
        "dev",
        "docker",
        "docker_version",
        "hassio",
        "host_os",
        "installation_type",
        "os_name",
        "os_version",
        "python_version",
        "supervisor",
        "version",
        "virtualenv",
        "chassis",
    }
)
CREDENTIAL_URL = re.compile(r"(https?://)[^\s/@]+@", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class EventContext:
    """A snapshot built on the HA event loop and read by SDK threads."""

    channel: str
    installation_id: str
    system_info: dict[str, Any]
    custom_components: frozenset[str]
    integrations: tuple[str, ...]
    secrets: tuple[str, ...] = field(repr=False)


@dataclass(slots=True)
class BetterStackRuntimeData:
    """Resources owned by this config entry; never persisted."""

    context: EventContext
    client: sentry_sdk.Client | None = None
    active: bool = True
    cancel_callbacks: list[Callable[[], None]] = field(default_factory=list)

    @callback
    def cancel_listeners(self) -> None:
        """Cancel listeners once, including before the SDK flush yields."""
        for cancel in self.cancel_callbacks:
            cancel()
        self.cancel_callbacks.clear()


type BetterStackConfigEntry = ConfigEntry[BetterStackRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: BetterStackConfigEntry) -> bool:
    """Set up Better Stack without changing the stored entry or its unique ID."""
    try:
        dsn = Dsn(entry.data[CONF_DSN])
    except BadDsn, KeyError, TypeError:
        raise ConfigEntryError("Invalid Better Stack DSN") from None

    if (
        any(
            candidate.disabled_by is None and candidate.source != SOURCE_IGNORE
            for candidate in hass.config_entries.async_entries("sentry")
        )
        or sentry_sdk.get_global_scope().client.is_active()
    ):
        raise ConfigEntryError(
            "Another Sentry SDK client is active. Disable the Sentry integration "
            "before enabling Better Stack."
        )

    installation_id = await instance_id.async_get(hass)
    channel = get_release_channel()
    secrets = tuple(
        value
        for value in (entry.data[CONF_DSN], dsn.public_key, dsn.secret_key)
        if value
    )

    async def get_context() -> EventContext:
        """Gather metadata outside SDK callbacks and omit personal fields."""
        system_info = await async_get_system_info(hass)
        custom_components = await async_get_custom_components(hass)
        return EventContext(
            channel=channel,
            installation_id=installation_id,
            system_info={
                key: value
                for key, value in system_info.items()
                if key in SYSTEM_INFO_FIELDS
            },
            custom_components=frozenset(custom_components),
            integrations=tuple(
                sorted(
                    name
                    for name in hass.config.components
                    if name != "auth" and "." not in name
                )
            ),
            secrets=secrets,
        )

    runtime = BetterStackRuntimeData(context=await get_context())

    def before_send(event: SentryEvent, hint: dict[str, Any]) -> SentryEvent | None:
        if not runtime.active:
            return None
        # HA replaces the options mapping atomically; no reload or HA API call here.
        # Better Stack accepts fields (such as title) outside Sentry's TypedDict.
        return cast(
            "SentryEvent | None",
            process_before_send(
                entry.options, runtime.context, cast("dict[str, Any]", event), hint
            ),
        )

    def create_sdk_client() -> sentry_sdk.Client:
        """SDK integrations import and patch modules on the import executor."""
        return sentry_sdk.Client(
            dsn=entry.data[CONF_DSN],
            environment=DEFAULT_ENVIRONMENT,
            integrations=[
                LoggingIntegration(
                    level=None, event_level=logging.ERROR, sentry_logs_level=None
                ),
                AioHttpIntegration(),
            ],
            auto_enabling_integrations=False,
            trace_propagation_targets=[],
            release=current_version,
            send_default_pii=False,
            include_local_variables=False,
            server_name="",
            max_breadcrumbs=0,
            auto_session_tracking=False,
            enable_logs=False,
            before_send=before_send,
        )

    def init_sdk() -> tuple[sentry_sdk.Client | None, str | None]:
        # A cancelled shielded future can log its exception independently of its
        # caller. Return only a safe error type, never the SDK's exception/DSN.
        try:
            return create_sdk_client(), None
        except Exception as err:
            return None, type(err).__name__

    # Shield the executor future so a cancelled setup can still close its new client.
    init_job = hass.async_add_import_executor_job(init_sdk)
    try:
        client, error_type = await asyncio.shield(init_job)
    except asyncio.CancelledError:
        client, _ = await init_job
        if client is not None:
            await hass.async_add_executor_job(client.close, 2.0)
        raise
    if client is None:
        raise ConfigEntryError(
            f"Unable to initialize the Better Stack SDK ({error_type})"
        )

    # A second integration may have bound a client while our import job was running.
    if sentry_sdk.get_global_scope().client.is_active():
        await hass.async_add_executor_job(client.close, 2.0)
        raise ConfigEntryError("Another Sentry SDK client became active during setup")

    runtime.client = client
    entry.runtime_data = runtime
    sentry_sdk.get_global_scope().set_client(client)

    async def close_sdk() -> None:
        """Detach only our global client, then flush off the event loop."""
        runtime.active = False
        runtime.cancel_listeners()
        if (client := runtime.client) is None:
            return
        runtime.client = None
        if sentry_sdk.get_global_scope().client is client:
            sentry_sdk.get_global_scope().set_client(None)
        await hass.async_add_executor_job(client.close, 2.0)

    # Also covers HA stopping and cleanup following a later setup failure.
    entry.async_on_unload(close_sdk)

    async def update_system_info() -> None:
        if runtime.active:
            context = await get_context()
            if runtime.active:
                runtime.context = context

    @callback
    def schedule_refresh(_now: datetime | HomeAssistant) -> None:
        if runtime.active:
            entry.async_create_background_task(
                hass, update_system_info(), "Refresh Better Stack system info"
            )

    async def stop_sdk(_event: Any) -> None:
        await close_sdk()

    runtime.cancel_callbacks.extend(
        [
            async_track_time_interval(hass, schedule_refresh, timedelta(hours=1)),
            async_at_started(hass, schedule_refresh),
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_sdk),
        ]
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BetterStackConfigEntry
) -> bool:
    """Unload the entry; async_on_unload owns listener and SDK cleanup."""
    return True


def process_before_send(
    options: Mapping[str, Any],
    context: EventContext,
    event: dict[str, Any],
    hint: dict[str, Any],
) -> dict[str, Any] | None:
    """Filter and enrich an event without network, disk, or mutable HA access."""
    exception_values = (event.get("exception") or {}).get("values", [])
    mechanisms = [
        value["mechanism"]["handled"]
        for value in exception_values
        if "handled" in (value.get("mechanism") or {})
    ]
    if not options.get(CONF_EVENT_HANDLED) and (
        (event.get("tags") or {}).get("handled") == "yes"
        or (mechanisms and all(mechanisms))
    ):
        return None

    logger = event.get("logger") or ""
    if not logger:
        # Unhandled exception events often have no logger. Use the innermost module.
        for value in exception_values:
            for frame in (value.get("stacktrace") or {}).get("frames", []):
                logger = frame.get("module") or logger
        if not logger and (exc_info := hint.get("exc_info")):
            traceback = exc_info[2]
            while traceback is not None:
                logger = traceback.tb_frame.f_globals.get("__name__", logger)
                traceback = traceback.tb_next

    parts = logger.split(".")
    if (
        logger == f"custom_components.{DOMAIN}"
        or logger.startswith((f"custom_components.{DOMAIN}.", "sentry_sdk."))
        or logger == "sentry_sdk"
    ):
        return None

    tags = {
        "channel": context.channel,
        "installation_type": context.system_info.get("installation_type", "Unknown"),
        "uuid": context.installation_id,
    }
    is_custom = False
    if len(parts) >= 2 and parts[0] == "custom_components":
        tags["integration"] = parts[1]
        is_custom = True
        if len(parts) >= 3 and parts[2] in ENTITY_COMPONENTS:
            tags["platform"] = parts[2]
    elif len(parts) >= 3 and parts[:2] == ["homeassistant", "components"]:
        tags["integration"] = parts[2]
        is_custom = parts[2] in context.custom_components
        if len(parts) >= 4 and parts[3] in ENTITY_COMPONENTS:
            tags["platform"] = parts[3]
    elif parts[0] == "homeassistant":
        if len(parts) >= 3:
            tags[parts[1]] = parts[2]
    elif logger:
        if not options.get(CONF_EVENT_THIRD_PARTY_PACKAGES):
            return None
        tags["package"] = parts[0]

    # HA can log an exception on behalf of a custom integration. Its traceback
    # still identifies that integration even without a platform context variable.
    for value in exception_values:
        for frame in (value.get("stacktrace") or {}).get("frames", []):
            module = (frame.get("module") or "").split(".")
            if len(module) >= 2 and module[0] == "custom_components":
                if module[1] == DOMAIN:
                    return None
                tags["integration"] = module[1]
                is_custom = True

    if (platform := entity_platform.current_platform.get()) is not None:
        tags.setdefault("integration", platform.platform_name)
        tags.setdefault("platform", platform.domain)
        is_custom |= platform.platform_name in context.custom_components

    if is_custom and not options.get(CONF_EVENT_CUSTOM_COMPONENTS):
        return None
    if "integration" in tags:
        tags["custom_component"] = "yes" if is_custom else "no"

    event.setdefault("tags", {}).update(tags)
    # Replace inherited user data instead of adding an ID to possible email/IP fields.
    event["user"] = {"id": context.installation_id}
    event.pop("server_name", None)
    event.pop("request", None)
    if isinstance(extra := event.get("extra"), dict):
        extra.pop("sys.argv", None)
    event.setdefault("contexts", {})["Home Assistant"] = {
        "channel": context.channel,
        "custom_components": "\n".join(sorted(context.custom_components)),
        "integrations": "\n".join(context.integrations),
        **context.system_info,
    }
    event = redact_secrets(event, context.secrets)
    normalize_logentry_title(event)
    return event


def redact_secrets(value: Any, secrets: tuple[str, ...]) -> Any:
    """Redact configured credentials, including in formatted messages and URLs."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return CREDENTIAL_URL.sub(r"\1[redacted]@", value)
    if isinstance(value, dict):
        return {
            redact_secrets(key, secrets): redact_secrets(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item, secrets) for item in value]
    return value


def normalize_logentry_title(event: dict[str, Any]) -> None:
    """Promote formatted log events into fields Better Stack uses for titles."""
    if "exception" in event or not isinstance(logentry := event.get("logentry"), dict):
        return
    formatted_message = logentry.get("formatted")
    if not isinstance(formatted_message, str) or not formatted_message:
        return
    template_message = logentry.get("message")
    if (
        isinstance(template_message, str)
        and template_message
        and template_message != formatted_message
    ):
        event.setdefault("extra", {}).setdefault("log_template", template_message)
    logentry["message"] = formatted_message
    event["message"] = formatted_message
    event["title"] = formatted_message
    event.setdefault("transaction", formatted_message)
