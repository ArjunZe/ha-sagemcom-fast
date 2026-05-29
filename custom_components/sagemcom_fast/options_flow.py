"""Options flow for Sagemcom integration."""

import re

from homeassistant import config_entries
from homeassistant.const import CONF_SCAN_INTERVAL
import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.selector as selector
import voluptuous as vol

from .const import (
    CONF_DEVICE_EXCLUDE_REGEX,
    CONF_DEVICE_INCLUDE_REGEX,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


def validate_regex_rules(rules: str) -> str:
    """Validate newline-separated regex rules."""
    try:
        for rule in rules.splitlines():
            if rule.strip():
                re.compile(rule.strip())
    except re.error as exception:
        raise ValueError("invalid_regex") from exception
    return rules


class OptionsFlow(config_entries.OptionsFlow):
    """Handle a options flow for Sagemcom."""

    def __init__(self, config_entry):
        """Initialize Sagemcom options flow."""
        self._data = dict(config_entry.data)
        self._options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            errors = {}
            for option in (CONF_DEVICE_INCLUDE_REGEX, CONF_DEVICE_EXCLUDE_REGEX):
                try:
                    validate_regex_rules(user_input.get(option, ""))
                except ValueError:
                    errors[option] = "invalid_regex"

            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._get_options_schema(user_input),
                    errors=errors,
                )

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_options_schema(self._options),
        )

    def _get_options_schema(self, options):
        """Return options schema."""
        return vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(
                        CONF_SCAN_INTERVAL,
                        self._data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(cv.positive_int, vol.Clamp(min=MIN_SCAN_INTERVAL)),
                vol.Optional(
                    CONF_DEVICE_INCLUDE_REGEX,
                    default=options.get(
                        CONF_DEVICE_INCLUDE_REGEX,
                        self._data.get(CONF_DEVICE_INCLUDE_REGEX, ""),
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Optional(
                    CONF_DEVICE_EXCLUDE_REGEX,
                    default=options.get(
                        CONF_DEVICE_EXCLUDE_REGEX,
                        self._data.get(CONF_DEVICE_EXCLUDE_REGEX, ""),
                    ),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )
