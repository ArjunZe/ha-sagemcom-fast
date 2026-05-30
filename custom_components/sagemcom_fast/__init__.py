"""The Sagemcom F@st integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from aiohttp.client_exceptions import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client, device_registry, entity_registry
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from sagemcom_api.client import SagemcomClient
from sagemcom_api.enums import EncryptionMethod
from sagemcom_api.exceptions import (
    AccessRestrictionException,
    AuthenticationException,
    LoginRetryErrorException,
    MaximumSessionCountException,
    UnauthorizedException,
)
from sagemcom_api.models import DeviceInfo as GatewayDeviceInfo

from .const import (
    CONF_DEVICE_EXCLUDE_REGEX,
    CONF_DEVICE_INCLUDE_REGEX,
    CONF_ENCRYPTION_METHOD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    PLATFORMS,
)
from .coordinator import RestoredDevice, SagemcomDataUpdateCoordinator


@dataclass
class HomeAssistantSagemcomFastData:
    """SagemcomFast data stored in the Home Assistant data object."""

    coordinator: SagemcomDataUpdateCoordinator
    gateway: GatewayDeviceInfo


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Sagemcom F@st from a config entry."""
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    encryption_method = entry.data[CONF_ENCRYPTION_METHOD]
    ssl = entry.data[CONF_SSL]
    verify_ssl = entry.data[CONF_VERIFY_SSL]

    session = aiohttp_client.async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = SagemcomClient(
        host=host,
        username=username,
        password=password,
        authentication_method=EncryptionMethod(encryption_method),
        session=session,
        ssl=ssl,
    )

    try:
        await client.login()
    except AccessRestrictionException as exception:
        LOGGER.error("Access restricted")
        raise ConfigEntryAuthFailed("Access restricted") from exception
    except (AuthenticationException, UnauthorizedException) as exception:
        LOGGER.error("Invalid_auth")
        raise ConfigEntryAuthFailed("Invalid credentials") from exception
    except (TimeoutError, ClientError, ConnectionError) as exception:
        LOGGER.error("Failed to connect")
        raise ConfigEntryNotReady("Failed to connect") from exception
    except MaximumSessionCountException as exception:
        LOGGER.error("Maximum session count reached")
        raise ConfigEntryNotReady("Maximum session count reached") from exception
    except LoginRetryErrorException as exception:
        LOGGER.error("Too many login attempts. Retry later.")
        raise ConfigEntryNotReady(
            "Too many login attempts. Retry later."
        ) from exception
    except Exception as exception:  # pylint: disable=broad-except
        LOGGER.exception(exception)
        return False

    try:
        gateway = await client.get_device_info()
    finally:
        await client.logout()

    update_interval = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    include_regex = entry.options.get(
        CONF_DEVICE_INCLUDE_REGEX, entry.data.get(CONF_DEVICE_INCLUDE_REGEX)
    )
    exclude_regex = entry.options.get(
        CONF_DEVICE_EXCLUDE_REGEX, entry.data.get(CONF_DEVICE_EXCLUDE_REGEX)
    )

    coordinator = SagemcomDataUpdateCoordinator(
        hass,
        LOGGER,
        name="sagemcom_hosts",
        client=client,
        update_interval=timedelta(seconds=update_interval),
        include_regex=include_regex,
        exclude_regex=exclude_regex,
    )
    coordinator.restore_hosts(_restore_registered_hosts(hass, entry))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = HomeAssistantSagemcomFastData(
        coordinator=coordinator, gateway=gateway
    )

    # Create gateway device in Home Assistant
    dev_registry = device_registry.async_get(hass)

    dev_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_NETWORK_MAC, gateway.mac_address)},
        identifiers={(DOMAIN, gateway.serial_number)},
        manufacturer=gateway.manufacturer,
        name=f"{gateway.manufacturer} {gateway.model_number}",
        model=gateway.model_name,
        sw_version=gateway.software_version,
        configuration_url=f"{'https' if ssl else 'http'}://{host}",
    )

    await coordinator.async_config_entry_first_refresh()
    if include_regex or exclude_regex:
        _cleanup_filtered_device_entries(
            hass,
            entry,
            allowed_device_ids=set(coordinator.data),
            gateway_id=gateway.serial_number,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update when entry options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def _cleanup_filtered_device_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    allowed_device_ids: set[str],
    gateway_id: str,
) -> None:
    """Remove registry entries for device trackers blocked by current filters."""
    dev_registry = device_registry.async_get(hass)
    blocked_registry_device_ids: set[str] = set()
    for device_entry in device_registry.async_entries_for_config_entry(
        dev_registry, entry.entry_id
    ):
        device_ids = {
            identifier[1]
            for identifier in device_entry.identifiers
            if identifier[0] == DOMAIN
        }
        if not device_ids or gateway_id in device_ids:
            continue

        if not device_ids & allowed_device_ids:
            blocked_registry_device_ids.add(device_entry.id)
            dev_registry.async_remove_device(device_entry.id)

    ent_registry = entity_registry.async_get(hass)
    for entity_entry in entity_registry.async_entries_for_config_entry(
        ent_registry, entry.entry_id
    ):
        if (
            entity_entry.device_id in blocked_registry_device_ids
            or entity_entry.domain == "device_tracker"
            and entity_entry.unique_id not in allowed_device_ids
        ):
            ent_registry.async_remove(entity_entry.entity_id)


def _restore_registered_hosts(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> list[RestoredDevice]:
    """Restore previously registered device trackers as offline hosts."""
    ent_registry = entity_registry.async_get(hass)
    dev_registry = device_registry.async_get(hass)
    restored_hosts: list[RestoredDevice] = []

    for entity_entry in entity_registry.async_entries_for_config_entry(
        ent_registry, entry.entry_id
    ):
        if entity_entry.domain != "device_tracker":
            continue

        device_entry = None
        if entity_entry.device_id:
            device_entry = dev_registry.async_get(entity_entry.device_id)

        mac_address = None
        device_name = None
        if device_entry is not None:
            mac_address = next(
                (
                    connection[1]
                    for connection in device_entry.connections
                    if connection[0] == CONNECTION_NETWORK_MAC
                ),
                None,
            )
            device_name = getattr(device_entry, "name_by_user", None) or getattr(
                device_entry, "name", None
            )
        entity_name = getattr(entity_entry, "original_name", None) or getattr(
            entity_entry, "name", None
        )

        restored_hosts.append(
            RestoredDevice(
                id=entity_entry.unique_id,
                name=entity_name,
                user_friendly_name=device_name,
                phys_address=mac_address,
                user_host_name=device_name,
                host_name=entity_name,
            )
        )

    return restored_hosts
