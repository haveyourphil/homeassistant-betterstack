"""Constants for the Better Stack error tracking integration."""

from __future__ import annotations

DOMAIN = "betterstack"

CONF_DSN = "dsn"
CONF_EVENT_CUSTOM_COMPONENTS = "event_custom_components"
CONF_EVENT_HANDLED = "event_handled"
CONF_EVENT_THIRD_PARTY_PACKAGES = "event_third_party_packages"

DEFAULT_ENVIRONMENT = "production"

ENTITY_COMPONENTS = [
    "air_quality",
    "alarm_control_panel",
    "binary_sensor",
    "calendar",
    "camera",
    "climate",
    "cover",
    "device_tracker",
    "event",
    "fan",
    "geo_location",
    "group",
    "humidifier",
    "image",
    "lawn_mower",
    "light",
    "lock",
    "media_player",
    "number",
    "remote",
    "scene",
    "select",
    "sensor",
    "siren",
    "switch",
    "text",
    "update",
    "vacuum",
    "valve",
    "water_heater",
    "weather",
]
