import importlib.util
import os
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


MODULE_PATH = Path("/xkagent_infra/brain/base/hooks/lep/lep.py")
LOADER = SourceFileLoader("brain_base_hooks_lep", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader("brain_base_hooks_lep", LOADER)
lep_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = lep_module
SPEC.loader.exec_module(lep_module)


class LepPathResolutionTest(unittest.TestCase):
    def test_get_lep_path_prefers_hook_relative_spec_when_hook_root_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hook_root = root / "base" / "hooks"
            spec_file = root / "base" / "spec" / "core" / "lep.yaml"
            hook_root.mkdir(parents=True, exist_ok=True)
            spec_file.parent.mkdir(parents=True, exist_ok=True)
            spec_file.write_text("actions: {}\n", encoding="utf-8")

            old_hook_root = os.environ.get("HOOK_ROOT")
            old_local = lep_module.LEP_FILE_LOCAL
            try:
                os.environ["HOOK_ROOT"] = str(hook_root)
                lep_module.LEP_FILE_LOCAL = str(root / "missing_local.yaml")
                self.assertEqual(lep_module.get_lep_path(), str(spec_file.resolve()))
            finally:
                if old_hook_root is None:
                    os.environ.pop("HOOK_ROOT", None)
                else:
                    os.environ["HOOK_ROOT"] = old_hook_root
                lep_module.LEP_FILE_LOCAL = old_local


if __name__ == "__main__":
    unittest.main()
