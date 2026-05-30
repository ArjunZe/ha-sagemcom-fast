"""Helpers to help coordinate updates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
import re

from aiohttp.client_exceptions import ClientError
import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from sagemcom_api.client import SagemcomClient
from sagemcom_api.exceptions import (
    AccessRestrictionException,
    AuthenticationException,
    LoginRetryErrorException,
    MaximumSessionCountException,
    UnauthorizedException,
)
from sagemcom_api.models import Device


@dataclass
class RestoredDevice:
    """Minimal device restored from Home Assistant registries."""

    id: str
    active: bool = False
    name: str | None = None
    user_friendly_name: str | None = None
    phys_address: str | None = None
    ip_address: str | None = None
    interface_type: str | None = None
    user_host_name: str | None = None
    host_name: str | None = None


SagemcomDevice = Device | RestoredDevice


DEVICE_FILTER_FIELDS = (
    "id",
    "name",
    "user_friendly_name",
    "phys_address",
    "ip_address",
    "interface_type",
    "user_host_name",
    "host_name",
)


def compile_regex_rules(rules: str | None) -> list[re.Pattern]:
    """Compile newline-separated regex rules."""
    return [
        re.compile(rule.strip())
        for rule in (rules or "").splitlines()
        if rule.strip()
    ]


def device_filter_text(device: SagemcomDevice) -> str:
    """Return searchable text for a device."""
    values = []
    for field in DEVICE_FILTER_FIELDS:
        if value := getattr(device, field, None):
            values.append(str(value))
    return "\n".join(values)


class SagemcomDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Sagemcom data."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        *,
        name: str,
        client: SagemcomClient,
        update_interval: timedelta | None = None,
        include_regex: str | None = None,
        exclude_regex: str | None = None,
    ):
        """Initialize update coordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=update_interval,
        )
        self.data = {}
        self.hosts: dict[str, SagemcomDevice] = {}
        self.client = client
        self.logger = logger
        self._include_rules = compile_regex_rules(include_regex)
        self._exclude_rules = compile_regex_rules(exclude_regex)

    def restore_hosts(self, hosts: list[RestoredDevice]) -> None:
        """Restore known hosts as offline before the first router refresh."""
        for host in hosts:
            if self.device_allowed(host):
                self.hosts[host.id] = host

    def device_allowed(self, device: SagemcomDevice) -> bool:
        """Return whether a device is allowed by the configured filters."""
        device_text = device_filter_text(device)

        if self._include_rules and not any(
            rule.search(device_text) for rule in self._include_rules
        ):
            return False

        return not any(rule.search(device_text) for rule in self._exclude_rules)

    async def _async_update_data(self) -> dict[str, SagemcomDevice]:
        """Update hosts data."""
        try:
            async with async_timeout.timeout(25):
                try:
                    await self.client.login()
                    await asyncio.sleep(1)
                    hosts = await self.client.get_hosts(only_active=True)
                finally:
                    await self.client.logout()

                """Mark all device as non-active."""
                for idx, host in self.hosts.items():
                    host.active = False
                    self.hosts[idx] = host

                for host in hosts:
                    if not self.device_allowed(host):
                        self.hosts.pop(host.id, None)
                        continue

                    self.hosts[host.id] = host

                return self.hosts
        except AccessRestrictionException as exception:
            raise ConfigEntryAuthFailed("Access restricted") from exception
        except (AuthenticationException, UnauthorizedException) as exception:
            raise ConfigEntryAuthFailed("Invalid credentials") from exception
        except (TimeoutError, ClientError, ConnectionError) as exception:
            raise UpdateFailed("Failed to connect") from exception
        except LoginRetryErrorException as exception:
            raise UpdateFailed(
                "Too many login attempts. Retrying later."
            ) from exception
        except MaximumSessionCountException as exception:
            raise UpdateFailed("Maximum session count reached") from exception
        except Exception as exception:
            self.logger.exception(exception)
            raise UpdateFailed(f"Error communicating with API: {str(exception)}")
