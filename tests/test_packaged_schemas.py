import json
import unittest
from importlib.resources import files
from pathlib import Path

from warrantos.schemas import available_schemas, load_schema


class PackagedSchemaResourceTests(unittest.TestCase):
    """These reads use package resources, never repository-relative paths."""

    def test_resources_are_available_through_installed_package_api(self):
        self.assertEqual(
            available_schemas(),
            ("source-manifest-v1.json", "claim-binding-v1.json", "trust-root-v1.json"),
        )
        for name in available_schemas():
            with self.subTest(name=name):
                resource = files("warrantos.schemas").joinpath(name)
                self.assertTrue(resource.is_file())
                parsed = load_schema(name)
                self.assertEqual(parsed["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_unknown_resource_fails_closed(self):
        with self.assertRaises(ValueError):
            load_schema("not-a-schema.json")

    def test_loaded_schema_identities(self):
        self.assertEqual(
            load_schema("source-manifest-v1.json")["properties"]["schema"]["const"],
            "warrantos-source-manifest/v1",
        )
        self.assertEqual(
            load_schema("claim-binding-v1.json")["properties"]["schema"]["const"],
            "warrantos-claim-binding/v1",
        )
        self.assertEqual(
            load_schema("trust-root-v1.json")["properties"]["schema"]["const"],
            "warrantos-trust-root/v1",
        )


class SchemaCopyDriftTests(unittest.TestCase):
    def test_repository_exchange_schemas_match_packaged_resources(self):
        root = Path(__file__).resolve().parents[1]
        for name in available_schemas():
            with self.subTest(name=name):
                source = json.loads((root / "schema" / name).read_text(encoding="utf-8"))
                self.assertEqual(source, load_schema(name))


if __name__ == "__main__":
    unittest.main()
