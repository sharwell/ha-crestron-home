"""Home Assistant entity identities for Crestron shades."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST


def shade_entity_unique_id(entry: ConfigEntry, shade_id: str) -> str:
    """Return the stable cover registry ID for a controller shade."""
    host = entry.data.get(CONF_HOST, entry.unique_id or entry.entry_id)
    if host is None:
        host = entry.entry_id
    return f"shade:{str(host).lower()}:{shade_id}"
