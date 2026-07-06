from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from sisyphus.config import ConfigError, config_from_dict, discover_config_path, load_config, validate_config
from sisyphus.hosts.cli import build_run_options, build_runtime, main


class ConfigTests(unittest.TestCase):
    def test_config_from_dict_reads_minimal_toml_shape(self) -> None:
        config = config_from_dict(
            {
                "model": {
                    "model": "sisyphus-mock-model",
                    "completions_url": "http://127.0.0.1:8881/v1/chat/completions",
                    "temperature": 0.2,
                    "mock_scenario": "message",
                },
                "runtime": {"max_iterations": 7, "stream_tokens": False},
                "workspace": {"root": "workspace", "read": True, "write": True},
                "tools": {"enabled": ["read_file", "echo"]},
            }
        )

        self.assertEqual(config.model.model, "sisyphus-mock-model")
        self.assertEqual(config.model.completions_url, "http://127.0.0.1:8881/v1/chat/completions")
        self.assertEqual(config.model.temperature, 0.2)
        self.assertEqual(config.model.metadata["mock_scenario"], "message")
        self.assertEqual(config.runtime.max_iterations, 7)
        self.assertFalse(config.runtime.stream_tokens)
        self.assertEqual(config.workspace.root, "workspace")
        self.assertTrue(config.workspace.write)
        self.assertEqual(config.tools.enabled, ["read_file", "echo"])

    def test_load_config_reads_toml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sisyphus.toml"
            path.write_text(
                """
[model]
model = "mock"

[tools]
enabled = ["echo"]
""".strip(),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.model.model, "mock")
        self.assertEqual(config.tools.enabled, ["echo"])

    def test_discover_config_path_prefers_sisyphus_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".sisyphus.toml").write_text("[model]\nmodel = 'hidden'\n", encoding="utf-8")
            (root / "sisyphus.toml").write_text("[model]\nmodel = 'primary'\n", encoding="utf-8")

            path = discover_config_path(root)

        self.assertEqual(path.name, "sisyphus.toml")

    def test_validate_config_rejects_unknown_tools(self) -> None:
        config = config_from_dict({"tools": {"enabled": ["read_file", "missing_tool"]}})

        with self.assertRaisesRegex(ConfigError, "Unknown tool"):
            validate_config(config)

    def test_validate_config_rejects_unsupported_provider(self) -> None:
        config = config_from_dict({"model": {"provider": "other"}})

        with self.assertRaisesRegex(ConfigError, "Unsupported model provider"):
            validate_config(config)

    def test_build_runtime_uses_config_and_command_line_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            configured_root = Path(tmp) / "configured"
            override_root = Path(tmp) / "override"
            configured_root.mkdir()
            override_root.mkdir()
            config = config_from_dict(
                {
                    "model": {
                        "model": "configured-model",
                        "base_url": "https://configured.example/v1",
                        "completions_url": "https://configured.example/chat",
                        "temperature": 0.4,
                    },
                    "workspace": {"root": str(configured_root), "read": False, "write": True},
                    "tools": {"enabled": ["echo"]},
                }
            )
            args = argparse.Namespace(
                model="override-model",
                base_url=None,
                completions_url="https://override.example/chat",
                cwd=str(override_root),
            )

            runtime = build_runtime(args, config)

        self.assertEqual(runtime.model.model, "override-model")
        self.assertEqual(runtime.model.base_url, "https://configured.example/v1")
        self.assertEqual(runtime.model.completions_url, "https://override.example/chat")
        self.assertEqual(runtime.cwd, override_root.resolve())
        self.assertEqual(runtime.permissions.root, override_root.resolve())
        self.assertEqual(runtime.permissions.read, "deny")
        self.assertEqual(runtime.permissions.write, "allow")
        self.assertEqual([spec.name for spec in runtime.tools.specs()], ["echo"])
        self.assertEqual(runtime.config.temperature, 0.4)

    def test_workspace_config_supports_ask_permission_mode(self) -> None:
        config = config_from_dict({"workspace": {"read": "ask", "write": "ask"}})

        self.assertEqual(config.workspace.read, "ask")
        self.assertEqual(config.workspace.write, "ask")

    def test_build_run_options_merges_runtime_config_and_args(self) -> None:
        config = config_from_dict(
            {
                "runtime": {
                    "max_iterations": 3,
                    "timeout_seconds": 12.5,
                    "stream_tokens": False,
                    "metadata": {"trace": "yes"},
                }
            }
        )
        args = argparse.Namespace(max_iterations=9)

        options = build_run_options(args, config)

        self.assertEqual(options.max_iterations, 9)
        self.assertEqual(options.timeout_seconds, 12.5)
        self.assertFalse(options.stream_tokens)
        self.assertEqual(options.metadata, {"trace": "yes"})

    def test_cli_check_validates_config_without_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "sisyphus.toml"
            config_path.write_text(
                f"""
[model]
model = "mock"

[workspace]
root = "{root.as_posix()}"

[tools]
enabled = ["echo"]
""".strip(),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(["--config", str(config_path), "--check"])

        self.assertEqual(code, 0)
        self.assertIn("Configuration OK", stdout.getvalue())

    def test_cli_check_reports_config_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "sisyphus.toml"
            config_path.write_text("[tools]\nenabled = ['missing_tool']\n", encoding="utf-8")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                code = main(["--config", str(config_path), "--check"])

        self.assertEqual(code, 2)
        self.assertIn("Unknown tool", stderr.getvalue())

    def test_cli_check_reports_missing_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            config_path = Path(tmp) / "sisyphus.toml"
            config_path.write_text(f"[workspace]\nroot = \"{missing.as_posix()}\"\n", encoding="utf-8")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                code = main(["--config", str(config_path), "--check"])

        self.assertEqual(code, 2)
        self.assertIn("Workspace root does not exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
