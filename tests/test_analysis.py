import unittest

from _support import load_fixture

from spark_analyzer.analysis import (
    analysis_to_dict,
    analyze,
    summarize_for_ai,
)
from spark_analyzer.parser import parse_profile


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.profile = parse_profile(load_fixture("sample_sampler.json"))
        self.result = analyze(self.profile)

    def test_focus_is_server_thread(self):
        # Server thread (1000) is busier than the async loader (120).
        self.assertEqual(self.result.primary_thread, "Server thread")
        self.assertEqual(self.result.thread_total, 1000.0)

    def test_top_method_by_self_time(self):
        top_label, top_self = self.result.top_methods[0]
        self.assertEqual(top_label, "com.example.LaggyPlugin.scanLoadedChunks")
        self.assertEqual(top_self, 700.0)

    def test_plugin_attribution(self):
        self.assertEqual(self.result.plugins[0], ("LaggyPlugin", 700.0))

    def test_hot_path_descends_heaviest(self):
        labels = [label for label, _pct, _src in self.result.hot_path]
        self.assertEqual(
            labels,
            [
                "net.minecraft.server.MinecraftServer.tick",
                "com.example.LaggyPlugin.onServerTick",
                "com.example.LaggyPlugin.scanLoadedChunks",
            ],
        )

    def test_lag_windows_sorted_by_mspt_max(self):
        self.assertEqual(self.result.lag_windows[0].mspt_max, 412.0)

    def test_summary_mentions_key_signals(self):
        summary = summarize_for_ai(self.result)
        self.assertIn("LaggyPlugin", summary)
        self.assertIn("scanLoadedChunks", summary)
        self.assertIn("Worst lag windows", summary)

    def test_to_dict_is_json_safe(self):
        import json

        payload = analysis_to_dict(self.result)
        json.dumps(payload)  # must not raise
        self.assertEqual(payload["primary_thread"], "Server thread")

    def test_thread_filter(self):
        result = analyze(self.profile, thread_filter="async")
        self.assertEqual(result.primary_thread, "Async Chunk Loader #1")


if __name__ == "__main__":
    unittest.main()
