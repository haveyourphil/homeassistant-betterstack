"""Config flow for Better Stack error tracking."""

from __future__ import annotations

from typing import Any

import probatio
from sentry_sdk.utils import BadDsn, Dsn

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorType

from .const import (
    CONF_DSN,
    CONF_EVENT_CUSTOM_COMPONENTS,
    CONF_EVENT_HANDLED,
    CONF_EVENT_THIRD_PARTY_PACKAGES,
    DOMAIN,
)

DATA_SCHEMA = probatio.Schema(
    {probatio.Required(CONF_DSN): TextSelector({"type": TextSelectorType.PASSWORD})}
)


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
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                Dsn(user_input[CONF_DSN])
            except BadDsn:
                errors["base"] = "bad_dsn"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Better Stack", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace a rotated or mistyped DSN while keeping the existing entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                Dsn(user_input[CONF_DSN])
            except BadDsn:
                errors["base"] = "bad_dsn"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates=user_input
                )

        return self.async_show_form(
            step_id="reconfigure", data_schema=DATA_SCHEMA, errors=errors
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
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_EVENT_HANDLED,
                        default=self.config_entry.options.get(
                            CONF_EVENT_HANDLED, False
                        ),
                    ): bool,
                    probatio.Optional(
                        CONF_EVENT_CUSTOM_COMPONENTS,
                        default=self.config_entry.options.get(
                            CONF_EVENT_CUSTOM_COMPONENTS, False
                        ),
                    ): bool,
                    probatio.Optional(
                        CONF_EVENT_THIRD_PARTY_PACKAGES,
                        default=self.config_entry.options.get(
                            CONF_EVENT_THIRD_PARTY_PACKAGES, False
                        ),
                    ): bool,
                }
            ),
        )
