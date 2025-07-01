"""Support for Tronbyt lights."""
import logging
from typing import Any, Optional

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tronbyt light based on a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    api = data["api"]
    coordinators = data["coordinators"]
    devices = data["devices"]

    entities = []
    for device_id, coordinator in coordinators.items():
        device_info = devices[device_id]
        entities.append(TronbytLight(coordinator, api, device_id, device_info))

    async_add_entities(entities)


class TronbytLight(CoordinatorEntity, LightEntity):
    """Representation of a Tronbyt display as a light."""

    def __init__(self, coordinator, api, device_id: str, device_info: dict):
        """Initialize the light."""
        super().__init__(coordinator)
        self.api = api
        self.device_id = device_id
        self.device_info_data = device_info
        
        # Entity attributes
        self._attr_name = device_info.get("name", f"Tronbyt {device_id}")
        self._attr_unique_id = f"tronbyt_{device_id}_light"
        
        # Light specific attributes
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_supported_features = LightEntityFeature.TRANSITION

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_info_data.get("name", f"Tronbyt {self.device_id}"),
            manufacturer="Tronbyt",
            model=self.device_info_data.get("model", "Tronbyt Display"),
            sw_version=self.device_info_data.get("firmware_version"),
            configuration_url=self.api.base_url,
        )

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        # Consider the light "on" if brightness > 0
        brightness = self.coordinator.data.get("brightness", 0)
        return brightness > 0

    @property
    def brightness(self) -> Optional[int]:
        """Return the brightness of this light between 0..255."""
        # API already returns 0-255, so use directly
        api_brightness = self.coordinator.data.get("brightness", 0)
        if api_brightness is None:
            return None
        return int(api_brightness)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("online", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        attributes = {
            "device_id": self.device_id,
            "status": self.coordinator.data.get("status"),
        }
        
        # Add optional attributes if available
        if brightness := self.coordinator.data.get("brightness"):
            attributes["api_brightness"] = brightness  # 0-255 scale
        
        if current_app := self.coordinator.data.get("current_app"):
            attributes["current_app"] = current_app
            
        if auto_dim := self.coordinator.data.get("auto_dim"):
            attributes["auto_dim"] = auto_dim

        return attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        
        if brightness is not None:
            # Home Assistant brightness is 0-255, API expects 0-255, so use directly
            api_brightness = int(brightness)
            # Ensure minimum brightness when turning on
            api_brightness = max(api_brightness, 1)
        else:
            # Default brightness when no brightness specified
            current_brightness = self.coordinator.data.get("brightness", 0)
            api_brightness = 128 if current_brightness == 0 else current_brightness  # 50% = 128
        
        _LOGGER.info(f"Turning on {self.device_id} with brightness {api_brightness} (HA brightness: {brightness})")
                
        success = await self.api.set_device_brightness(self.device_id, api_brightness)
        if success:
            _LOGGER.info("Successfully set brightness, refreshing coordinator")
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn on device %s", self.device_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        _LOGGER.info(f"Turning off {self.device_id}")
                
        success = await self.api.set_device_brightness(self.device_id, 0)
        if success:
            _LOGGER.info("Successfully turned off, refreshing coordinator")
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn off device %s", self.device_id)
