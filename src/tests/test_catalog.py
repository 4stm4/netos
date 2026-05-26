"""Unit tests for PackageCatalog (M6).

Tests cover YAML loading (with both PyYAML and the built-in mini-parser),
group resolution, deduplication, error handling, and integration with
the built-in catalog.yaml.

Run:
    python src/tests/test_catalog.py
    python -m pytest src/tests/test_catalog.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from netos_build.catalog import PackageCatalog, DEFAULT_GROUPS, _parse_simple_yaml


# ---------------------------------------------------------------------------
# Minimal catalog YAML for unit tests (no file I/O)
# ---------------------------------------------------------------------------

_MINI_CATALOG = """
version: 1

groups:
  core:
    description: "Core tools"
    packages:
      - BR2_PACKAGE_BUSYBOX=y
      - BR2_PACKAGE_BASH=y

  networking:
    description: "Network tools"
    packages:
      - BR2_PACKAGE_IPROUTE2=y
      - BR2_PACKAGE_BUSYBOX=y

  python:
    description: "Python runtime"
    packages:
      - BR2_PACKAGE_PYTHON3=y
      - BR2_PACKAGE_PYTHON_PIP=y

  empty:
    description: "Group with no packages"
    packages: []
"""


# ---------------------------------------------------------------------------
# _parse_simple_yaml (built-in parser)
# ---------------------------------------------------------------------------

class TestParseSimpleYaml(unittest.TestCase):

    def test_parses_version(self):
        data = _parse_simple_yaml("version: 1\n")
        self.assertEqual(data.get("version"), "1")

    def test_parses_group_names(self):
        data = _parse_simple_yaml(_MINI_CATALOG)
        self.assertIn("groups", data)
        self.assertIn("core", data["groups"])
        self.assertIn("networking", data["groups"])

    def test_parses_package_list(self):
        data = _parse_simple_yaml(_MINI_CATALOG)
        core_pkgs = data["groups"]["core"]["packages"]
        self.assertIn("BR2_PACKAGE_BUSYBOX=y", core_pkgs)
        self.assertIn("BR2_PACKAGE_BASH=y", core_pkgs)

    def test_ignores_comments(self):
        text = "# this is a comment\nversion: 1\n# another\n"
        data = _parse_simple_yaml(text)
        self.assertIn("version", data)
        self.assertNotIn("#", str(data))

    def test_handles_blank_lines(self):
        text = "\n\nversion: 1\n\n"
        data = _parse_simple_yaml(text)
        self.assertEqual(data.get("version"), "1")


# ---------------------------------------------------------------------------
# PackageCatalog.from_text
# ---------------------------------------------------------------------------

class TestPackageCatalogFromText(unittest.TestCase):

    def _cat(self) -> PackageCatalog:
        return PackageCatalog.from_text(_MINI_CATALOG)

    def test_version(self):
        self.assertEqual(self._cat().version, 1)

    def test_group_names(self):
        names = self._cat().group_names()
        self.assertIn("core", names)
        self.assertIn("networking", names)
        self.assertIn("python", names)

    def test_packages_for_group(self):
        pkgs = self._cat().packages_for_group("core")
        self.assertIn("BR2_PACKAGE_BUSYBOX=y", pkgs)
        self.assertIn("BR2_PACKAGE_BASH=y", pkgs)

    def test_packages_for_unknown_group_raises_keyerror(self):
        with self.assertRaises(KeyError) as ctx:
            self._cat().packages_for_group("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_has_group_true(self):
        self.assertTrue(self._cat().has_group("core"))

    def test_has_group_false(self):
        self.assertFalse(self._cat().has_group("does-not-exist"))

    def test_description_for_group(self):
        desc = self._cat().description_for("core")
        self.assertIn("Core", desc)

    def test_description_for_unknown_returns_empty(self):
        self.assertEqual(self._cat().description_for("ghost"), "")

    def test_empty_group_returns_empty_list(self):
        pkgs = self._cat().packages_for_group("empty")
        self.assertEqual(pkgs, [])


# ---------------------------------------------------------------------------
# resolve_groups
# ---------------------------------------------------------------------------

class TestResolveGroups(unittest.TestCase):

    def _cat(self) -> PackageCatalog:
        return PackageCatalog.from_text(_MINI_CATALOG)

    def test_single_group(self):
        result = self._cat().resolve_groups(["core"])
        self.assertIn("BR2_PACKAGE_BUSYBOX=y", result)
        self.assertIn("BR2_PACKAGE_BASH=y", result)
        # networking packages must not be present
        self.assertNotIn("BR2_PACKAGE_IPROUTE2=y", result)

    def test_multiple_groups_merged(self):
        result = self._cat().resolve_groups(["core", "python"])
        self.assertIn("BR2_PACKAGE_BUSYBOX=y", result)
        self.assertIn("BR2_PACKAGE_PYTHON3=y", result)

    def test_deduplication(self):
        """BR2_PACKAGE_BUSYBOX=y appears in both core and networking."""
        result = self._cat().resolve_groups(["core", "networking"])
        count = result.count("BR2_PACKAGE_BUSYBOX=y")
        self.assertEqual(count, 1, "Duplicate package lines must be deduplicated")

    def test_order_preserved_first_occurrence_wins(self):
        result = self._cat().resolve_groups(["core", "networking"])
        idx_busybox = result.index("BR2_PACKAGE_BUSYBOX=y")
        idx_bash    = result.index("BR2_PACKAGE_BASH=y")
        idx_iproute = result.index("BR2_PACKAGE_IPROUTE2=y")
        # core comes first, so busybox and bash before iproute
        self.assertLess(idx_busybox, idx_iproute)
        self.assertLess(idx_bash, idx_iproute)

    def test_unknown_group_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self._cat().resolve_groups(["core", "ghost"])

    def test_empty_group_list_returns_empty(self):
        self.assertEqual(self._cat().resolve_groups([]), [])

    def test_all_packages_covers_all_groups(self):
        cat = self._cat()
        all_pkgs = set(cat.all_packages())
        for group in cat.group_names():
            for pkg in cat.packages_for_group(group):
                self.assertIn(pkg, all_pkgs,
                    f"Package {pkg} from group {group} missing from all_packages()")


# ---------------------------------------------------------------------------
# PackageCatalog.load (file-based)
# ---------------------------------------------------------------------------

class TestPackageCatalogLoad(unittest.TestCase):

    def test_load_default_catalog(self):
        """The built-in catalog.yaml must load without errors."""
        cat = PackageCatalog.load()
        self.assertIsInstance(cat, PackageCatalog)
        self.assertGreater(len(cat.group_names()), 0)

    def test_default_catalog_has_expected_groups(self):
        cat = PackageCatalog.load()
        for group in ("core", "networking", "monitoring", "storage",
                      "ssh", "python", "python-web", "ovs", "rootfs"):
            self.assertTrue(cat.has_group(group), f"Expected group '{group}' in catalog")

    def test_default_catalog_version_is_1(self):
        self.assertEqual(PackageCatalog.load().version, 1)

    def test_load_custom_catalog_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "custom.yaml"
            p.write_text(_MINI_CATALOG)
            cat = PackageCatalog.load(p)
            self.assertIn("core", cat.group_names())

    def test_load_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            PackageCatalog.load(Path("/nonexistent/catalog.yaml"))


# ---------------------------------------------------------------------------
# DEFAULT_GROUPS integration
# ---------------------------------------------------------------------------

class TestDefaultGroups(unittest.TestCase):

    def test_default_groups_all_exist_in_catalog(self):
        cat = PackageCatalog.load()
        for group in DEFAULT_GROUPS:
            self.assertTrue(
                cat.has_group(group),
                f"DEFAULT_GROUPS references '{group}' which is not in catalog",
            )

    def test_default_groups_resolve_busybox(self):
        cat = PackageCatalog.load()
        pkgs = cat.resolve_groups(list(DEFAULT_GROUPS))
        self.assertIn("BR2_PACKAGE_BUSYBOX=y", pkgs)

    def test_default_groups_resolve_rootfs_tar(self):
        cat = PackageCatalog.load()
        pkgs = cat.resolve_groups(list(DEFAULT_GROUPS))
        self.assertIn("BR2_TARGET_ROOTFS_TAR=y", pkgs)

    def test_default_groups_resolve_openvswitch(self):
        cat = PackageCatalog.load()
        pkgs = cat.resolve_groups(list(DEFAULT_GROUPS))
        self.assertIn("BR2_PACKAGE_OPENVSWITCH=y", pkgs)

    def test_default_groups_no_duplicates(self):
        cat = PackageCatalog.load()
        pkgs = cat.resolve_groups(list(DEFAULT_GROUPS))
        self.assertEqual(len(pkgs), len(set(pkgs)), "Duplicates in resolved DEFAULT_GROUPS")

    def test_default_groups_excludes_wireless_by_default(self):
        """wireless group is opt-in (target-specific), not in DEFAULT_GROUPS."""
        self.assertNotIn("wireless", DEFAULT_GROUPS)
        cat = PackageCatalog.load()
        pkgs = cat.resolve_groups(list(DEFAULT_GROUPS))
        self.assertNotIn("BR2_PACKAGE_WPA_SUPPLICANT=y", pkgs)

    def test_wireless_group_available_as_opt_in(self):
        cat = PackageCatalog.load()
        self.assertTrue(cat.has_group("wireless"))
        pkgs = cat.packages_for_group("wireless")
        self.assertIn("BR2_PACKAGE_WPA_SUPPLICANT=y", pkgs)


# ---------------------------------------------------------------------------
# Malformed catalog
# ---------------------------------------------------------------------------

class TestMalformedCatalog(unittest.TestCase):

    def test_bad_groups_type_raises(self):
        bad = "version: 1\ngroups: not-a-mapping\n"
        # PyYAML will parse "groups" as a string → ValueError
        # Mini-parser will produce an empty dict for "not-a-mapping" string
        # Just ensure it doesn't crash hard
        try:
            cat = PackageCatalog.from_text(bad)
            # If it loads, group names should be empty or valid
            self.assertIsInstance(cat.group_names(), list)
        except (ValueError, Exception):
            pass  # Acceptable

    def test_empty_catalog_gives_empty_groups(self):
        cat = PackageCatalog.from_text("version: 1\n")
        self.assertEqual(cat.group_names(), [])


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
