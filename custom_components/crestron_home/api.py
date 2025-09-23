from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CrestronHomeClient:
    """Placeholder API client (Milestone 0)."""

    host: str
    api_token: str
    verify_ssl: bool = True

    # Future milestones will add: login(), request(), logout(), etc.
