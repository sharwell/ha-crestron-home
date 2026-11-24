"""Aliases and outcome labels for exported and logged troubleshooting data."""

from secrets import token_hex


class IdentifierAliases:
    """Allocate independent aliases for one export or one loaded entry."""

    def __init__(self) -> None:
        self._shades: dict[str, str] = {}
        self._groups: dict[str, str] = {}

    def shade(self, shade_id: str) -> str:
        """Return the same alias for this shade throughout this instance."""
        if shade_id not in self._shades:
            self._shades[shade_id] = f"shade-{token_hex(8)}"
        return self._shades[shade_id]

    def group(self, group_id: str) -> str:
        """Return the same alias for this group throughout this instance."""
        if group_id not in self._groups:
            self._groups[group_id] = f"group-{token_hex(8)}"
        return self._groups[group_id]


def write_status_label(status: str) -> str:
    """Return an approved outcome label for a controller or batch status."""
    if status in {"success", "partial", "failure", "error"}:
        return status
    return "unknown"
