import unittest
from unittest import mock

import _support  # noqa: F401  (ensures src/ is importable)

from spark_analyzer import ai


SUMMARY = "Server thread total 1000ms\nscanChunks self 700ms (70%)"


class PromptTests(unittest.TestCase):
    def test_build_prompt_includes_summary(self):
        prompt = ai.build_prompt(SUMMARY)
        self.assertIn(SUMMARY, prompt)
        self.assertIn("Diagnose the lag spike", prompt)

    def test_manual_prompt_bundles_system_and_user(self):
        prompt = ai.build_manual_prompt(SUMMARY)
        # The manual prompt must be self-contained: system instructions + data.
        self.assertIn(ai.SYSTEM_PROMPT, prompt)
        self.assertIn(SUMMARY, prompt)


class BackendSelectionTests(unittest.TestCase):
    def test_explicit_choices_pass_through(self):
        self.assertEqual(ai.choose_backend("api"), "api")
        self.assertEqual(ai.choose_backend("cli"), "cli")

    def test_auto_prefers_api_key(self):
        with mock.patch.object(ai, "has_api_key", return_value=True), mock.patch.object(
            ai, "has_claude_cli", return_value=True
        ):
            self.assertEqual(ai.choose_backend("auto"), "api")

    def test_auto_falls_back_to_cli(self):
        with mock.patch.object(ai, "has_api_key", return_value=False), mock.patch.object(
            ai, "has_claude_cli", return_value=True
        ):
            self.assertEqual(ai.choose_backend("auto"), "cli")

    def test_auto_none_when_nothing_available(self):
        with mock.patch.object(ai, "has_api_key", return_value=False), mock.patch.object(
            ai, "has_claude_cli", return_value=False
        ):
            self.assertEqual(ai.choose_backend("auto"), "none")


class CliBackendTests(unittest.TestCase):
    def _completed(self, returncode=0, stdout="### Verdict\nfine", stderr=""):
        proc = mock.Mock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_builds_print_command_and_returns_stdout(self):
        with mock.patch.object(ai, "has_claude_cli", return_value=True), mock.patch.object(
            ai.subprocess, "run", return_value=self._completed()
        ) as run:
            out = ai.run_analysis_cli(SUMMARY, model="claude-opus-4-8")

        self.assertEqual(out, "### Verdict\nfine")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "claude")
        self.assertIn("--print", cmd)
        self.assertIn("--system-prompt", cmd)
        self.assertIn("--safe-mode", cmd)
        # tools disabled (empty string after --tools)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        # model is passed through
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-opus-4-8")
        # the analysis summary is fed on stdin
        self.assertIn(SUMMARY, run.call_args.kwargs["input"])

    def test_strips_api_key_for_subscription(self):
        with mock.patch.object(ai, "has_claude_cli", return_value=True), mock.patch.dict(
            ai.os.environ, {"ANTHROPIC_API_KEY": "sk-ant-secret"}, clear=False
        ), mock.patch.object(ai.subprocess, "run", return_value=self._completed()) as run:
            ai.run_analysis_cli(SUMMARY)
        env = run.call_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_keeps_api_key_when_subscription_disabled(self):
        with mock.patch.object(ai, "has_claude_cli", return_value=True), mock.patch.dict(
            ai.os.environ, {"ANTHROPIC_API_KEY": "sk-ant-secret"}, clear=False
        ), mock.patch.object(ai.subprocess, "run", return_value=self._completed()) as run:
            ai.run_analysis_cli(SUMMARY, use_subscription=False)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env.get("ANTHROPIC_API_KEY"), "sk-ant-secret")

    def test_missing_cli_raises_helpful_error(self):
        with mock.patch.object(ai, "has_claude_cli", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                ai.run_analysis_cli(SUMMARY)
        self.assertIn("claude login", str(ctx.exception).lower())

    def test_nonzero_exit_raises(self):
        with mock.patch.object(ai, "has_claude_cli", return_value=True), mock.patch.object(
            ai.subprocess, "run", return_value=self._completed(returncode=1, stdout="", stderr="boom")
        ):
            with self.assertRaises(RuntimeError) as ctx:
                ai.run_analysis_cli(SUMMARY)
        self.assertIn("boom", str(ctx.exception))

    def test_empty_output_raises(self):
        with mock.patch.object(ai, "has_claude_cli", return_value=True), mock.patch.object(
            ai.subprocess, "run", return_value=self._completed(stdout="   ")
        ):
            with self.assertRaises(RuntimeError):
                ai.run_analysis_cli(SUMMARY)


if __name__ == "__main__":
    unittest.main()
