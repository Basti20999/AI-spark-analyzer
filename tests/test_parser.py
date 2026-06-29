import unittest

from _support import load_fixture

from spark_analyzer.parser import parse_profile


class FlatFormatTests(unittest.TestCase):
    def setUp(self):
        self.profile = parse_profile(load_fixture("sample_sampler.json"))

    def test_detects_sampler(self):
        self.assertEqual(self.profile.source_type, "sampler")
        self.assertEqual(len(self.profile.threads), 2)

    def test_builds_tree_from_pool_refs(self):
        server = next(t for t in self.profile.threads if t.name == "Server thread")
        self.assertEqual(len(server.roots), 1)
        root = server.roots[0]
        self.assertEqual(root.label, "net.minecraft.server.MinecraftServer.tick")
        self.assertEqual(root.total_time, 1000.0)
        self.assertEqual(len(root.children), 2)

    def test_self_time_excludes_children(self):
        server = next(t for t in self.profile.threads if t.name == "Server thread")
        root = server.roots[0]
        # tick total 1000, children 700 + 300 -> self 0
        self.assertEqual(root.self_time, 0.0)
        on_tick = next(c for c in root.children if "onServerTick" in c.label)
        # onServerTick total 700, child scanLoadedChunks 700 -> self 0
        self.assertEqual(on_tick.self_time, 0.0)
        scan = on_tick.children[0]
        self.assertEqual(scan.self_time, 700.0)

    def test_source_attribution(self):
        server = next(t for t in self.profile.threads if t.name == "Server thread")
        scan = server.roots[0].children[0].children[0]
        self.assertEqual(scan.label, "com.example.LaggyPlugin.scanLoadedChunks")
        self.assertEqual(scan.source, "LaggyPlugin")

    def test_window_stats(self):
        self.assertEqual(len(self.profile.window_stats), 1)
        w = self.profile.window_stats[0]
        self.assertEqual(w.mspt_max, 412.0)
        self.assertEqual(w.ticks, 100)

    def test_platform_health(self):
        self.assertEqual(self.profile.platform["tps"]["last1m"], 14.2)
        self.assertEqual(self.profile.platform["tps"]["target"], 20)


class NestedFormatTests(unittest.TestCase):
    """Legacy nested format: frames carry their own `children`, no refs."""

    def test_nested_tree(self):
        data = {
            "metadata": {},
            "threads": [
                {
                    "name": "Server thread",
                    "children": [
                        {
                            "class_name": "A",
                            "method_name": "outer",
                            "times": [100.0],
                            "children": [
                                {
                                    "class_name": "B",
                                    "method_name": "inner",
                                    "times": [60.0],
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
            "class_sources": {"B": "PluginB"},
        }
        profile = parse_profile(data)
        root = profile.threads[0].roots[0]
        self.assertEqual(root.label, "A.outer")
        self.assertEqual(root.self_time, 40.0)
        self.assertEqual(root.children[0].source, "PluginB")


if __name__ == "__main__":
    unittest.main()
