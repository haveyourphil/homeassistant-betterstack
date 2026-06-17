"""Config flow for Better Stack error tracking."""

from __future__ import annotations

import logging
from typing import Any

from sentry_sdk.utils import BadDsn, Dsn
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_DSN,
    CONF_ENVIRONMENT,
    CONF_EVENT_CUSTOM_COMPONENTS,
    CONF_EVENT_HANDLED,
    CONF_EVENT_THIRD_PARTY_PACKAGES,
    CONF_LOGGING_EVENT_LEVEL,
    DEFAULT_LOGGING_EVENT_LEVEL,
    DOMAIN,
    LOGGING_LEVELS,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({vol.Required(CONF_DSN): str})


class BetterStackConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Better Stack config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> BetterStackOptionsFlow:
        """Get the options flow for this handler."""
        return BetterStackOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a user config flow."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                Dsn(user_input[CONF_DSN])
            except BadDsn:
                errors["base"] = "bad_dsn"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Better Stack", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class BetterStackOptionsFlow(OptionsFlow):
    """Handle Better Stack options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Better Stack options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LOGGING_EVENT_LEVEL,
                        default=self.config_entry.options.get(
                            CONF_LOGGING_EVENT_LEVEL, DEFAULT_LOGGING_EVENT_LEVEL
                        ),
                    ): vol.In(LOGGING_LEVELS),
                    vol.Optional(
                        CONF_ENVIRONMENT,
                        default=self.config_entry.options.get(CONF_ENVIRONMENT),
                    ): str,
                    vol.Optional(
                        CONF_EVENT_HANDLED,
                        default=self.config_entry.options.get(
                            CONF_EVENT_HANDLED, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_EVENT_CUSTOM_COMPONENTS,
                        default=self.config_entry.options.get(
                            CONF_EVENT_CUSTOM_COMPONENTS, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_EVENT_THIRD_PARTY_PACKAGES,
                        default=self.config_entry.options.get(
                            CONF_EVENT_THIRD_PARTY_PACKAGES, False
                        ),
                    ): bool,
                }
            ),
        )
