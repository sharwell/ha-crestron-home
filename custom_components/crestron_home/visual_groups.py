"""Utilities for managing visual groups of Crestron Home shades."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import logging
from typing import Iterable, Mapping, MutableMapping, Sequence

_LOGGER = logging.getLogger(__name__)


OPT_VISUAL_GROUPS = "visual_groups"
VISUAL_GROUPS_VERSION = 1
IMPLICIT_GROUP_ID = "__implicit__"
STANDALONE_PREFIX = "shade:"


@dataclass
class VisualGroupEntry:
    """Metadata describing a configured visual group."""

    name: str


@dataclass
class VisualGroupsConfig:
    """Collection of configured groups and shade memberships."""

    version: int = VISUAL_GROUPS_VERSION
    groups: dict[str, VisualGroupEntry] = field(default_factory=dict)
    membership: dict[str, str] = field(default_factory=dict)

    @property
    def has_explicit_groups(self) -> bool:
        return bool(self.groups)

    def group_name(self, group_id: str | None, *, shade_ids: Sequence[str] | None = None) -> str:
        if not group_id or group_id == IMPLICIT_GROUP_ID:
            return "All shades"
        if group_id.startswith(STANDALONE_PREFIX):
            shade = group_id[len(STANDALONE_PREFIX) :]
            if shade_ids and len(shade_ids) == 1 and shade_ids[0] == shade:
                return f"Standalone ({shade})"
            return f"Standalone ({shade})"
        entry = self.groups.get(group_id)
        if entry is not None:
            return entry.name
        return group_id

    def standalone_group_id(self, shade_id: str) -> str:
        return f"{STANDALONE_PREFIX}{shade_id}"

    def partition_shades(
        self, shade_ids: Sequence[str]
    ) -> tuple[OrderedDict[str, list[str]], set[str]]:
        """Partition shade identifiers into their effective groups."""

        partitions: OrderedDict[str, list[str]] = OrderedDict()
        invalid_groups: set[str] = set()

        for shade_id in shade_ids:
            if not shade_id:
                continue

            configured_group = self.membership.get(shade_id)
            if configured_group and configured_group in self.groups:
                group_id = configured_group
            elif configured_group:
                invalid_groups.add(configured_group)
                group_id = self.standalone_group_id(shade_id)
            elif not self.has_explicit_groups:
                group_id = IMPLICIT_GROUP_ID
            else:
                group_id = self.standalone_group_id(shade_id)

            partitions.setdefault(group_id, []).append(shade_id)

        return partitions, invalid_groups

    def as_options(self) -> dict[str, object]:
        if not self.groups and not self.membership:
            return {}

        return {
            "version": self.version,
            "groups": {
                group_id: {"name": entry.name}
                for group_id, entry in sorted(self.groups.items())
            },
            "membership": dict(sorted(self.membership.items())),
        }

    def diagnostics(self) -> dict[str, object]:
        options = self.as_options()
        if not options:
            return {"version": self.version, "groups": {}, "membership": {}}
        return options


def _normalize_group_id(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip()


def _normalize_group_name(raw: object, fallback: str) -> str:
    if isinstance(raw, str):
        candidate = raw.strip()
        if candidate:
            return candidate
    return fallback


def parse_visual_groups(options: Mapping[str, object]) -> VisualGroupsConfig:
    raw = options.get(OPT_VISUAL_GROUPS)
    if not isinstance(raw, Mapping):
        return VisualGroupsConfig()

    version = raw.get("version", VISUAL_GROUPS_VERSION)
    try:
        version_int = int(version)
    except (TypeError, ValueError):
        version_int = VISUAL_GROUPS_VERSION

    groups: dict[str, VisualGroupEntry] = {}
    raw_groups = raw.get("groups")
    if isinstance(raw_groups, Mapping):
        for group_id_raw, meta in raw_groups.items():
            group_id = _normalize_group_id(group_id_raw)
            if not group_id:
                continue
            name = _normalize_group_name(
                meta.get("name") if isinstance(meta, Mapping) else meta,
                group_id,
            )
            groups[group_id] = VisualGroupEntry(name=name)

    membership: dict[str, str] = {}
    raw_membership = raw.get("membership")
    if isinstance(raw_membership, Mapping):
        for shade_id_raw, group_id_raw in raw_membership.items():
            shade_id = _normalize_group_id(shade_id_raw)
            group_id = _normalize_group_id(group_id_raw)
            if not shade_id or not group_id:
                continue
            membership[shade_id] = group_id

    return VisualGroupsConfig(version=version_int, groups=groups, membership=membership)


def update_visual_groups_option(
    options: MutableMapping[str, object], config: VisualGroupsConfig
) -> None:
    payload = config.as_options()
    if payload:
        options[OPT_VISUAL_GROUPS] = payload
    elif OPT_VISUAL_GROUPS in options:
        options.pop(OPT_VISUAL_GROUPS)


def log_invalid_groups(invalid: Iterable[str]) -> None:
    for group_id in sorted(invalid):
        _LOGGER.warning(
            "Visual group '%s' referenced in membership but not defined", group_id
        )
