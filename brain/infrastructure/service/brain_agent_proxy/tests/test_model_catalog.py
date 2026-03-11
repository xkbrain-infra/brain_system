import unittest

from src.main import _build_exposed_model_ids


class ModelCatalogTests(unittest.TestCase):
    def test_bare_mode_preserves_existing_model_ids(self) -> None:
        self.assertEqual(
            _build_exposed_model_ids("claude-sonnet-4.6", "copilot", mode="bare"),
            ["claude-sonnet-4.6"],
        )

    def test_prefixed_mode_exposes_provider_model_ids(self) -> None:
        self.assertEqual(
            _build_exposed_model_ids("claude-sonnet-4.6", "copilot", mode="prefixed"),
            ["copilot/claude-sonnet-4.6"],
        )

    def test_both_mode_exposes_bare_and_prefixed_ids(self) -> None:
        self.assertEqual(
            _build_exposed_model_ids("claude-sonnet-4.6", "copilot", mode="both"),
            ["claude-sonnet-4.6", "copilot/claude-sonnet-4.6"],
        )

    def test_both_mode_does_not_duplicate_prefixed_ids(self) -> None:
        self.assertEqual(
            _build_exposed_model_ids("copilot/claude-sonnet-4.6", "copilot", mode="both"),
            ["copilot/claude-sonnet-4.6"],
        )


if __name__ == "__main__":
    unittest.main()
