import importlib.util
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


HOOKS_ROOT = Path("/xkagent_infra/brain/base/hooks")
LEP_ROOT = HOOKS_ROOT / "lep"
OVERRIDES_ROOT = HOOKS_ROOT / "overrides" / "agent-brain_manager"

if str(LEP_ROOT) not in sys.path:
    sys.path.insert(0, str(LEP_ROOT))

from result import CheckContext


def _load_module(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


exploration_checker = _load_module(
    "brain_manager_exploration_checker",
    OVERRIDES_ROOT / "exploration_checker.py",
)
service_boundary_checker = _load_module(
    "brain_manager_service_boundary_checker",
    OVERRIDES_ROOT / "service_boundary_checker.py",
)


def _bash_context(command: str) -> CheckContext:
    return CheckContext(
        tool_name="Bash",
        tool_input={"command": command},
        gate_id="",
        enforcement={},
    )


class ManagerAgentctlAllowlistTest(unittest.TestCase):
    def test_exploration_checker_allows_uppercase_agentctl_path(self) -> None:
        result = exploration_checker.check(
            _bash_context(
                "/brain/infrastructure/service/agentctl/bin/Agentctl "
                "start --apply agent-brain_devops agent-brain_pmo"
            )
        )

        self.assertTrue(result.is_pass)

    def test_exploration_checker_allows_python_wrapped_agentctl(self) -> None:
        result = exploration_checker.check(
            _bash_context(
                "python3 /brain/infrastructure/service/agentctl/bin/agentctl "
                "start --apply agent-brain_devops"
            )
        )

        self.assertTrue(result.is_pass)

    def test_exploration_checker_allows_brain_agentctl(self) -> None:
        result = exploration_checker.check(
            _bash_context("brain-agentctl start --apply agent-brain_devops")
        )

        self.assertTrue(result.is_pass)

    def test_exploration_checker_still_blocks_directory_exploration(self) -> None:
        result = exploration_checker.check(
            _bash_context("ls /brain/infrastructure/service/agentctl/bin")
        )

        self.assertTrue(result.is_block)

    def test_service_boundary_checker_allows_agentctl_in_service_path(self) -> None:
        result = service_boundary_checker.check(
            _bash_context(
                "python3 /xkagent_infra/brain/infrastructure/service/agentctl/bin/agentctl "
                "start --apply agent-brain_devops"
            )
        )

        self.assertTrue(result.is_pass)

    def test_service_boundary_checker_still_blocks_service_file_reads(self) -> None:
        result = service_boundary_checker.check(
            _bash_context("cat /xkagent_infra/brain/infrastructure/service/agentctl/README.md")
        )

        self.assertTrue(result.is_block)


if __name__ == "__main__":
    unittest.main()
