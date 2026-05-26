"""PackageCatalog — load and resolve Buildroot package groups from YAML.

The catalog lives at ``src/packages/catalog.yaml`` and contains named groups
of ``BR2_PACKAGE_*=y`` lines.  This module is the bridge between the
human-readable catalog and the Buildroot defconfig generator.

Usage::

    from netos_build.catalog import PackageCatalog, DEFAULT_GROUPS

    cat = PackageCatalog.load()
    lines = cat.resolve_groups(DEFAULT_GROUPS)
    # → ["BR2_PACKAGE_BUSYBOX=y", "BR2_PACKAGE_BASH=y", ...]

Loading without PyYAML
-----------------------
PyYAML is an optional dependency.  When it is not available, the catalog
falls back to a lightweight built-in YAML parser that handles the simple
subset used by ``catalog.yaml`` (scalar lists under mapping keys, comments,
blank lines).  This keeps the build tool dependency-free for CI environments.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Default set of groups that go into every netos build.
DEFAULT_GROUPS: tuple[str, ...] = (
    "core",
    "networking",
    "monitoring",
    "dns",
    "storage",
    "ssh",
    "python",
    "python-web",
    "ovs",
    "rootfs",
)

_CATALOG_PATH = Path(__file__).parent.parent / "packages" / "catalog.yaml"


# ---------------------------------------------------------------------------
# Minimal YAML subset parser (fallback when PyYAML is absent)
# ---------------------------------------------------------------------------

def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the specific subset of YAML used by catalog.yaml.

    Handles:
    - Top-level mapping keys (``key:``)
    - Nested mapping keys (indented ``key:``)
    - Scalar list items (``  - value``)
    - Line comments (``# …``) and blank lines

    Does NOT handle: anchors, multi-line scalars, flow style, tags.

    Stack entries: ``(indent, parent_dict, key)`` meaning that
    ``parent_dict[key]`` is the current node (dict or list).  This lets
    us *promote* an empty-dict node to a list when the first child we
    see is a ``- item`` rather than a ``key: value`` pair.
    """
    root: dict[str, Any] = {}
    # sentinel entry: root has no parent, use (indent=-1, parent=None, key=None)
    stack: list[tuple[int, Any, Any]] = [(-1, None, None)]
    # current_node: the container we are currently filling
    current_node: Any = root

    def _current() -> Any:
        return current_node

    # We track the actual container in a parallel way:
    # stack[-1] = (indent, parent_dict, key) where parent_dict[key] IS the container
    # root is special: no parent

    # Simpler flat approach: keep (indent, node) and also track the "last key"
    # that was pushed so we can convert dict→list on first list item.
    # We use a separate stack: (indent, parent, key) to always know our location.

    node_stack: list[tuple[int, Any, Any]] = []  # (indent, parent, key)
    result: dict[str, Any] = {}
    cur: Any = result
    # node_stack is empty → cur == result (root)

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        # Strip inline comments (good enough for simple catalog; strings don't contain #)
        if "#" in line:
            line = line[:line.index("#")].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if stripped.startswith("- "):
            # List item
            value = stripped[2:].strip()

            # Pop back to the scope that *contains* the list key.
            # List items at indent N belong to a key defined at indent < N.
            while node_stack and node_stack[-1][0] >= indent:
                node_stack.pop()
                cur = node_stack[-1][1][node_stack[-1][2]] if node_stack else result

            # At this point `cur` is either:
            # (a) an empty dict  — we just descended into "key:" with no value;
            #     that key should be a list, so promote it using the parent info
            #     stored in node_stack.
            # (b) a dict with a last key already holding a list — append to it.
            if isinstance(cur, dict) and not cur and node_stack:
                # Case (a): promote parent[key] from {} to [value]
                _, parent, key = node_stack[-1]
                parent[key] = [value]
                cur = parent[key]
            elif isinstance(cur, dict) and cur:
                # Case (b): the last key's value should be a list
                last_key = next(reversed(cur))
                val = cur[last_key]
                if isinstance(val, list):
                    val.append(value)
                elif isinstance(val, dict) and len(val) == 0:
                    cur[last_key] = [value]
            elif isinstance(cur, list):
                cur.append(value)
            continue

        if ":" in stripped:
            key, _, rest = stripped.partition(":")
            key       = key.strip()
            value_str = rest.strip()

            # Pop to the right scope
            while node_stack and node_stack[-1][0] >= indent:
                node_stack.pop()
                cur = node_stack[-1][1][node_stack[-1][2]] if node_stack else result

            if value_str:
                cur[key] = value_str.strip('"\'')
            else:
                new_node: dict = {}
                cur[key] = new_node
                node_stack.append((indent, cur, key))
                cur = new_node

    return result


# ---------------------------------------------------------------------------
# PackageCatalog
# ---------------------------------------------------------------------------

class PackageCatalog:
    """Loaded package catalog with group resolution."""

    def __init__(self, data: dict[str, Any], source_path: Path | None = None) -> None:
        self._data = data
        self._source_path = source_path
        self._groups: dict[str, list[str]] = {}

        raw_groups = data.get("groups", {})
        if not isinstance(raw_groups, dict):
            raise ValueError("catalog.yaml: 'groups' must be a mapping")
        for name, body in raw_groups.items():
            if not isinstance(body, dict):
                continue
            pkgs = body.get("packages", [])
            if not isinstance(pkgs, list):
                raise ValueError(
                    f"catalog.yaml: group '{name}' packages must be a list"
                )
            self._groups[name] = [str(p) for p in pkgs]

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "PackageCatalog":
        """Load catalog from *path* (defaults to the built-in catalog.yaml).

        Tries PyYAML first; falls back to the built-in mini-parser.
        """
        p = Path(path) if path else _CATALOG_PATH
        if not p.exists():
            raise FileNotFoundError(f"Package catalog not found: {p}")
        text = p.read_text(encoding="utf-8")
        data = cls._parse(text)
        return cls(data, source_path=p)

    @classmethod
    def from_text(cls, yaml_text: str) -> "PackageCatalog":
        """Create a catalog from a raw YAML string (useful in tests)."""
        return cls(cls._parse(yaml_text))

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        try:
            import yaml  # type: ignore[import]
            return yaml.safe_load(text) or {}
        except ImportError:
            return _parse_simple_yaml(text)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def version(self) -> int:
        return int(self._data.get("version", 1))

    def group_names(self) -> list[str]:
        """Return all group names in catalog order."""
        return list(self._groups)

    def description_for(self, group: str) -> str:
        """Return the description string for a group (empty string if absent)."""
        raw = self._data.get("groups", {}).get(group, {})
        if isinstance(raw, dict):
            return raw.get("description", "")
        return ""

    def packages_for_group(self, group: str) -> list[str]:
        """Return ``BR2_PACKAGE_*=y`` lines for *group*.

        Raises ``KeyError`` if the group is not in the catalog.
        """
        if group not in self._groups:
            raise KeyError(
                f"Package group '{group}' not in catalog "
                f"(available: {', '.join(self._groups)})"
            )
        return list(self._groups[group])

    def resolve_groups(self, groups: "list[str] | tuple[str, ...]") -> list[str]:
        """Resolve group names to a flat, deduplicated list of package lines.

        Order is preserved (first occurrence wins for duplicates).
        Raises ``KeyError`` if any group name is unknown.
        """
        seen: dict[str, None] = {}
        for group in groups:
            for pkg in self.packages_for_group(group):
                seen[pkg] = None
        return list(seen)

    def all_packages(self) -> list[str]:
        """All packages from all groups (deduplicated, catalog order)."""
        return self.resolve_groups(list(self._groups))

    def has_group(self, group: str) -> bool:
        return group in self._groups
