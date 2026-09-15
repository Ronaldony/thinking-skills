from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_mock_model_catalog import derive_catalog


class MockModelCatalogTests(unittest.TestCase):
    def _model(self, slug: str, *, patch: str | None = "freeform", shell: str = "unified_exec", modalities=None):
        return {
            "slug": slug,
            "display_name": f"display-{slug}",
            "description": f"description-{slug}",
            "apply_patch_tool_type": patch,
            "shell_type": shell,
            "input_modalities": ["text", "image"] if modalities is None else modalities,
            "priority": 7,
            "supported_in_api": True,
            "arbitrary_preserved_field": {"nested": [1, 2, 3]},
        }

    def test_patch_capable_model_is_cloned_and_only_identity_fields_change(self):
        source = self._model("source-model")
        catalog = {"models": [source], "extra_envelope": {"keep": True}}
        output, manifest = derive_catalog(catalog, mock_slug="mock-model")
        self.assertEqual(output["extra_envelope"], {"keep": True})
        self.assertEqual(len(output["models"]), 1)
        clone = output["models"][0]
        self.assertEqual(clone["slug"], "mock-model")
        self.assertEqual(clone["display_name"], "mock-model")
        restored = deepcopy(clone)
        restored["slug"] = source["slug"]
        restored["display_name"] = source["display_name"]
        self.assertEqual(restored, source)
        self.assertEqual(manifest["source_slug"], "source-model")
        self.assertTrue(manifest["only_slug_and_display_name_changed"])

    def test_first_eligible_model_is_selected_deterministically(self):
        catalog = {
            "models": [
                self._model("no-patch", patch=None),
                self._model("first-good"),
                self._model("second-good"),
            ]
        }
        output, manifest = derive_catalog(catalog)
        self.assertEqual(manifest["source_slug"], "first-good")
        self.assertEqual(manifest["candidate_count"], 2)
        self.assertEqual(output["models"][0]["description"], "description-first-good")

    def test_no_patch_capable_model_is_rejected(self):
        with self.assertRaises(ValueError):
            derive_catalog({"models": [self._model("a", patch=None)]})

    def test_disabled_shell_is_rejected(self):
        with self.assertRaises(ValueError):
            derive_catalog({"models": [self._model("a", shell="disabled")]})

    def test_missing_text_modality_is_rejected(self):
        with self.assertRaises(ValueError):
            derive_catalog({"models": [self._model("a", modalities=["image"])]})

    def test_duplicate_source_slugs_are_rejected(self):
        model = self._model("duplicate")
        with self.assertRaises(ValueError):
            derive_catalog({"models": [model, deepcopy(model)]})

    def test_malformed_model_entry_is_rejected(self):
        with self.assertRaises(ValueError):
            derive_catalog({"models": ["not-an-object"]})

    def test_mock_slug_must_be_trimmed(self):
        with self.assertRaises(ValueError):
            derive_catalog({"models": [self._model("a")]}, mock_slug=" mock-model ")


if __name__ == "__main__":
    unittest.main()
