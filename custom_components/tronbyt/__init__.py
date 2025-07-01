"""
Home Assistant integration for Tronbyt devices with automatic device discovery.
"""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_API_KEY, CONF_BASE_URL, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]
SCAN_INTERVAL = timedelta(seconds=30)


class TronbytAPI:
    """API client for Tronbyt server."""

    def __init__(self, base_url: str, username: str, api_key: str, session: aiohttp.ClientSession):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.api_key = api_key
        self.session = session
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
    async def test_connection(self) -> bool:
        """Test connection to Tronbyt server."""
        try:
            async with self.session.get(
                f"{self.base_url}/v0/devices",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status == 200
        except Exception as e:
            _LOGGER.error(f"Connection test failed: {e}")
            return False
    
    async def get_devices(self) -> List[Dict[str, Any]]:
        """Get list of all devices from Tronbyt server."""
        try:
            async with self.session.get(
                f"{self.base_url}/v0/devices",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    devices = data.get("devices", [])
                    # Transform the API response to our internal format
                    transformed_devices = []
                    for device in devices:
                        transformed_devices.append({
                            "id": device["id"],
                            "name": device["displayName"],
                            "brightness": device.get("brightness", 50),
                            "auto_dim": device.get("autoDim", False),
                            "model": "Tronbyt Display",
                            "online": True  # Assume online if returned by API
                        })
                    return transformed_devices
                else:
                    _LOGGER.error(f"Failed to get devices: HTTP {response.status}")
                    return []
        except Exception as e:
            _LOGGER.error(f"Error getting devices: {e}")
            return []
    
    async def _get_devices_fallback(self) -> List[Dict[str, Any]]:
        """Removed fallback method."""
        return []
    
    async def _get_devices_fallback(self) -> List[Dict[str, Any]]:
        """Fallback method to discover devices."""
        try:
            # Try to check if server responds and create a default device
            async with self.session.get(
                f"{self.base_url}/next",
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    # Create a default device entry if no device API exists
                    return [{
                        "id": "default",
                        "name": f"Tronbyt Display ({self.host})",
                        "host": self.host,
                        "model": "Tronbyt Display",
                        "online": True
                    }]
        except Exception:
            pass
        return []
    
    async def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """Get device status information."""
        try:
            # Always get updated device info from the user devices endpoint
            async with self.session.get(
                f"{self.base_url}/v0/devices",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    devices = data.get("devices", [])
                    
                    # Find our specific device
                    for device in devices:
                        if device["id"] == device_id:
                            return {
                                "online": True,
                                "status": "connected", 
                                "brightness": device.get("brightness", 50),  # This is 0-255 from API
                                "auto_dim": device.get("autoDim", False),
                                "current_app": await self._get_current_app(device_id),
                            }
                    
                    # Device not found
                    return {"online": False, "status": "not_found"}
                else:
                    return {"online": False, "status": "api_error"}
        except Exception as e:
            _LOGGER.error(f"Error getting device status for {device_id}: {e}")
            return {"online": False, "status": "error", "error": str(e)}
    
    async def _get_current_app(self, device_id: str) -> Optional[str]:
        """Get currently running app information."""
        try:
            async with self.session.get(
                f"{self.base_url}/v0/devices/{device_id}/installations",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    installations = data.get("installations", [])
                    if installations:
                        # Return the first installation's appID
                        return installations[0].get("appID", "Unknown")
        except Exception:
            pass
        
        return None
    
    async def set_device_power(self, device_id: str, state: bool) -> bool:
        """Turn device on or off."""
        try:
            # Use the brightness API to simulate power control
            # Set brightness to 0 for "off", restore previous brightness for "on"
            brightness = 50 if state else 0  # Default to 50% when turning on
            return await self.set_device_brightness(device_id, brightness)
        except Exception as e:
            _LOGGER.error(f"Error setting power state for {device_id}: {e}")
            return False

    async def set_device_brightness(self, device_id: str, brightness: int) -> bool:
        """Set device brightness (0-255)."""
        try:
            headers = self._headers
            url = f"{self.base_url}/v0/devices/{device_id}"
            
            # API expects brightness 0-255, not 0-100
            payload = {"brightness": brightness}
            
            _LOGGER.debug(f"Setting brightness for {device_id} to {brightness}")
            _LOGGER.debug(f"URL: {url}")
            _LOGGER.debug(f"Payload: {payload}")
            
            async with self.session.patch(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response_text = await response.text()
                _LOGGER.debug(f"Response status: {response.status}")
                _LOGGER.debug(f"Response headers: {dict(response.headers)}")
                _LOGGER.debug(f"Response body: {response_text}")
                
                if response.status in [200, 204]:
                    _LOGGER.info(f"Successfully set brightness for {device_id} to {brightness}")
                    return True
                else:
                    _LOGGER.error(f"Failed to set brightness for {device_id}: HTTP {response.status} - {response_text}")
                    return False
                    
        except Exception as e:
            _LOGGER.error(f"Error setting brightness for {device_id}: {e}")
            return False
    
    async def get_apps(self, device_id: str = None) -> List[Dict[str, Any]]:
        """Get list of available apps."""
        try:
            if device_id:
                # Get installed apps for specific device
                async with self.session.get(
                    f"{self.base_url}/v0/devices/{device_id}/installations",
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("installations", [])
            else:
                # Get all available apps
                async with self.session.get(
                    f"{self.base_url}/v0/apps",
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("apps", data) if isinstance(data, dict) else data
        except Exception as e:
            _LOGGER.error(f"Error getting apps: {e}")
        return []
    
    async def set_device_app(self, device_id: str, app_id: str) -> bool:
        """Set active app for device."""
        try:
            url = f"{self.base_url}/v0/devices/{device_id}/installations"
            
            async with self.session.post(
                url,
                json={"appId": app_id},
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status in [200, 201, 204]
        except Exception as e:
            _LOGGER.error(f"Error setting app for {device_id}: {e}")
            return False


class TronbytDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Tronbyt API."""
    
    def __init__(self, hass: HomeAssistant, api: TronbytAPI, device_id: str, device_name: str):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Tronbyt {device_name}",
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self.device_id = device_id
    
    async def _async_update_data(self):
        """Update data via library."""
        try:
            return await self.api.get_device_status(self.device_id)
        except Exception as exception:
            raise UpdateFailed(f"Error communicating with API: {exception}")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tronbyt integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tronbyt from a config entry."""
    base_url = entry.data[CONF_BASE_URL]
    username = entry.data[CONF_USERNAME]
    api_key = entry.data[CONF_API_KEY]
    
    session = async_get_clientsession(hass)
    api = TronbytAPI(base_url, username, api_key, session)
    
    # Test connection
    if not await api.test_connection():
        _LOGGER.error("Failed to connect to Tronbyt server")
        return False
    
    # Get devices from config entry (with API keys) or fetch fresh if not available
    stored_devices = entry.data.get("devices")
    if stored_devices:
        devices = stored_devices
        _LOGGER.info(f"Using stored devices with API keys: {len(devices)} devices")
    else:
        # Fallback: fetch devices if not stored in config (for older config entries)
        devices = await api.get_devices()
        if not devices:
            _LOGGER.error("No devices found on Tronbyt server")
            return False
    
    # Create coordinators for each device
    coordinators = {}
    for device in devices:
        device_id = device["id"]
        device_name = device["name"]
        
        coordinator = TronbytDataUpdateCoordinator(hass, api, device_id, device_name)
        await coordinator.async_config_entry_first_refresh()
        coordinators[device_id] = coordinator
    
    # Store data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinators": coordinators,
        "devices": {device["id"]: device for device in devices},
    }
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services
    await async_setup_services(hass, entry.entry_id)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        
        # Remove services if this was the last entry
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "set_brightness")
            hass.services.async_remove(DOMAIN, "set_app")
    
    return unload_ok


async def async_setup_services(hass: HomeAssistant, entry_id: str):
    """Set up services for Tronbyt integration."""
    
    async def handle_set_brightness(call):
        """Handle set brightness service call."""
        entity_id = call.data.get("entity_id")
        brightness = call.data.get("brightness", 50)
        
        # Extract device ID from entity ID
        if entity_id and entity_id.startswith("light.tronbyt_"):
            device_id = entity_id.replace("light.tronbyt_", "").replace("_light", "")
            
            # Get API and device info from the entry data
            entry_data = hass.data[DOMAIN][entry_id]
            api = entry_data["api"]
            await api.set_device_brightness(device_id, brightness)
    
    async def handle_set_app(call):
        """Handle set app service call."""
        entity_id = call.data.get("entity_id")
        app_id = call.data.get("app_id")
        
        # Extract device ID from entity ID
        if entity_id and entity_id.startswith("light.tronbyt_") and app_id:
            device_id = entity_id.replace("light.tronbyt_", "").replace("_light", "")
            
            # Get API and device info from the entry data
            entry_data = hass.data[DOMAIN][entry_id]
            api = entry_data["api"]
            await api.set_device_app(device_id, app_id)
    
    # Only register services if they don't exist yet
    if not hass.services.has_service(DOMAIN, "set_brightness"):
        hass.services.async_register(
            DOMAIN,
            "set_brightness",
            handle_set_brightness,
            schema=vol.Schema({
                vol.Required("entity_id"): str,
                vol.Required("brightness"): vol.All(int, vol.Range(min=0, max=100)),
            })
        )
    
    if not hass.services.has_service(DOMAIN, "set_app"):
        hass.services.async_register(
            DOMAIN,
            "set_app",
            handle_set_app,
            schema=vol.Schema({
                vol.Required("entity_id"): str,
                vol.Required("app_id"): str,
            })
        )
