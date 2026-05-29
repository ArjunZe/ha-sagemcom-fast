"""Diagnostic sensors for Sagemcom F@st tracked devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from sagemcom_api.models import Device

from . import HomeAssistantSagemcomFastData
from .const import DOMAIN
from .coordinator import SagemcomDataUpdateCoordinator
from .device_tracker import device_display_name


@dataclass(frozen=True)
class SagemcomDeviceSensorDescription:
    """Describe a diagnostic sensor backed by a Sagemcom device field."""

    key: str
    name: str
    value_fn: Callable[[Device], str | None]


SENSOR_DESCRIPTIONS: tuple[SagemcomDeviceSensorDescription, ...] = (
    SagemcomDeviceSensorDescription(
        "ip_address", "IP address", lambda device: device.ip_address
    ),
    SagemcomDeviceSensorDescription(
        "mac_address", "MAC address", lambda device: device.phys_address
    ),
    SagemcomDeviceSensorDescription(
        "interface_type", "Interface", lambda device: device.interface_type
    ),
    SagemcomDeviceSensorDescription(
        "friendly_name", "Friendly name", lambda device: device.user_friendly_name
    ),
    SagemcomDeviceSensorDescription(
        "user_hostname", "User hostname", lambda device: device.user_host_name
    ),
    SagemcomDeviceSensorDescription(
        "hostname", "Hostname", lambda device: device.host_name
    ),
    SagemcomDeviceSensorDescription(
        "router_name", "Router name", lambda device: device.name
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensors from config entry."""
    data: HomeAssistantSagemcomFastData = hass.data[DOMAIN][entry.entry_id]
    tracked: set[tuple[str, str]] = set()

    @callback
    def async_update_router() -> None:
        """Add sensors for newly discovered filtered devices."""
        newly_discovered: list[SagemcomDeviceSensor] = []
        for idx in data.coordinator.data:
            for description in SENSOR_DESCRIPTIONS:
                sensor_key = (idx, description.key)
                if sensor_key in tracked:
                    continue

                tracked.add(sensor_key)
                newly_discovered.append(
                    SagemcomDeviceSensor(
                        data.coordinator,
                        idx,
                        data.gateway.serial_number,
                        description,
                    )
                )
        async_add_entities(newly_discovered)

    entry.async_on_unload(data.coordinator.async_add_listener(async_update_router))
    async_update_router()


class SagemcomDeviceSensor(
    CoordinatorEntity[SagemcomDataUpdateCoordinator], SensorEntity
):
    """Diagnostic sensor for a tracked Sagemcom device."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: SagemcomDataUpdateCoordinator,
        idx: str,
        parent: str,
        description: SagemcomDeviceSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._idx = idx
        self._via_device = parent
        self._description = description
        self._attr_unique_id = f"{idx}_{description.key}"

    @property
    def device(self) -> Device:
        """Return the device backing this sensor."""
        return self.coordinator.data[self._idx]

    @property
    def name(self) -> str:
        """Return the sensor name."""
        return f"{device_display_name(self.device)} {self._description.name}"

    @property
    def native_value(self) -> str | None:
        """Return the sensor value."""
        value = self._description.value_fn(self.device)
        return str(value) if value else None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this sensor."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._idx)},
            connections={(CONNECTION_NETWORK_MAC, self.device.phys_address)},
            name=device_display_name(self.device),
            via_device=(DOMAIN, self._via_device),
        )
