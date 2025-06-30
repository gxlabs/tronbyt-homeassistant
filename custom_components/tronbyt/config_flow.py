"""Config flow for Tronbyt integration."""
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_BASE_URL, CONF_BEARER_TOKEN, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_BASE_URL): str,
    vol.Optional(CONF_USERNAME, default="admin"): str,
    vol.Optional(CONF_BEARER_TOKEN, default="bearer_token"): str,
})


class TronbytConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tronbyt."""

    VERSION = 1

    def __init__(self):
        """Initialize."""
        self.base_url: Optional[str] = None
        self.username: Optional[str] = None
        self.bearer_token: Optional[str] = None
        self.devices: list = []

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                # Validate and normalize the base URL
                base_url = self._normalize_url(user_input[CONF_BASE_URL])
                username = user_input[CONF_USERNAME]
                bearer_token = user_input[CONF_BEARER_TOKEN]

                # Test connection and get devices
                devices = await self._test_connection(base_url, username, bearer_token)
                
                if devices:
                    # Store the connection info
                    self.base_url = base_url
                    self.username = username
                    self.bearer_token = bearer_token
                    self.devices = devices
                    
                    # Check if already configured
                    await self.async_set_unique_id(f"{base_url}_{username}")
                    self._abort_if_unique_id_configured()
                    
                    # Show devices found
                    return await self.async_step_devices()
                else:
                    errors["base"] = "no_devices"

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "example_url": "https://tronbyt.gxlabs.co or http://192.168.1.100:8000"
            }
        )

    async def async_step_devices(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Show devices found and allow user to proceed."""
        if user_input is not None:
            # Create the config entry
            return self.async_create_entry(
                title=f"Tronbyt Server ({self.base_url})",
                data={
                    CONF_BASE_URL: self.base_url,
                    CONF_USERNAME: self.username,
                    CONF_BEARER_TOKEN: self.bearer_token,
                },
            )

        # Create device list for display
        device_list = []
        for device in self.devices:
            device_name = device.get('name', device.get('id', 'Unknown'))
            brightness = device.get('brightness', 'Unknown')
            device_list.append(f"• {device_name} (Brightness: {brightness}%)")

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema({}),
            description_placeholders={
                "device_count": str(len(self.devices)),
                "device_list": "\n".join(device_list),
                "base_url": self.base_url,
            }
        )

    def _normalize_url(self, url: str) -> str:
        """Normalize URL input."""
        url = url.strip().rstrip('/')
        
        # Add https:// if no scheme provided
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        # Parse URL to validate
        parsed = urlparse(url)
        if not parsed.hostname:
            raise ValueError("Invalid URL")
        
        return url

    async def _test_connection(self, base_url: str, username: str, bearer_token: str) -> list:
        """Test if we can authenticate with the server."""
        session = async_get_clientsession(self.hass)
        
        try:
            headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
            
            async with session.get(
                f"{base_url}/v0/users/{username}/devices",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 401:
                    raise InvalidAuth
                elif response.status != 200:
                    raise CannotConnect
                
                data = await response.json()
                devices = data.get("devices", [])
                
                # Transform devices to our format
                transformed_devices = []
                for device in devices:
                    transformed_devices.append({
                        "id": device["id"],
                        "name": device["displayName"],
                        "brightness": device.get("brightness", 50),
                    })
                
                return transformed_devices
                
        except aiohttp.ClientError:
            raise CannotConnect
        except Exception as err:
            _LOGGER.error("Error testing connection: %s", err)
            raise CannotConnect


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
