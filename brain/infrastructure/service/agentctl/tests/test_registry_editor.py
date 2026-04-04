#!/usr/bin/env python3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from config.registry_editor import AgentEntry, append_agent_to_group


def _entry(name: str, group: str = "brain") -> AgentEntry:
    return AgentEntry(
        name=name,
        tmux_session=name,
        cwd=f"/tmp/{name}",
        desired_state="stopped",
        role="custom",
        scope="group",
        group=group,
        path=f"/tmp/{name}",
        agent_type="claude",
        agent_cli="claude",
        agent_model="claude-sonnet-4.6",
        cli_type="claude",
        model="claude-sonnet-4.6",
        transport_mode="proxy",
    )


class RegistryEditorTests(unittest.TestCase):
    def _write_temp(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml")
        tmp.write(textwrap.dedent(content).lstrip())
        tmp.close()
        return Path(tmp.name)

    def test_append_to_group_before_inline_sibling_group(self) -> None:
        path = self._write_temp(
            """
            agents_registry:
              version: '2.2'
            group_meta:
              brain:
                type: coding
                description: Brain
              system:
                type: coding
                description: System
            groups:
              brain:
              - name: existing
                tmux_session: existing
                cwd: /tmp/existing
                required: false
                desired_state: running
                status: active
              system: []
            services: {}
            """
        )
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        append_agent_to_group(path, "brain", _entry("tmp-agent_sonnet"))
        text = path.read_text(encoding="utf-8")

        self.assertIn("  - name: tmp-agent_sonnet", text)
        self.assertLess(text.index("  - name: tmp-agent_sonnet"), text.index("  system: []"))

    def test_append_to_inline_empty_group_expands_group_header(self) -> None:
        path = self._write_temp(
            """
            agents_registry:
              version: '2.2'
            group_meta:
              brain:
                type: coding
                description: Brain
              system:
                type: coding
                description: System
            groups:
              brain: []
              system: []
            services: {}
            """
        )
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        append_agent_to_group(path, "system", _entry("tmp-agent_system_sonnet", group="system"))
        text = path.read_text(encoding="utf-8")

        self.assertIn("  system:\n  - name: tmp-agent_system_sonnet", text)
        self.assertNotIn("  system: []", text)


if __name__ == "__main__":
    unittest.main()
