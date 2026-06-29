import unittest

from _support import FIXTURES

from spark_analyzer.fetcher import FetchError, extract_code, fetch


class ExtractCodeTests(unittest.TestCase):
    def test_bare_code(self):
        self.assertEqual(extract_code("uksGhFmkWd"), "uksGhFmkWd")

    def test_viewer_url(self):
        self.assertEqual(extract_code("https://spark.lucko.me/uksGhFmkWd"), "uksGhFmkWd")

    def test_url_with_query(self):
        self.assertEqual(
            extract_code("https://spark.lucko.me/uksGhFmkWd?raw=1&full=true"),
            "uksGhFmkWd",
        )

    def test_bytebin_url(self):
        self.assertEqual(
            extract_code("https://spark-usercontent.lucko.me/abc123XYZ"),
            "abc123XYZ",
        )

    def test_rejects_garbage(self):
        self.assertIsNone(extract_code("not a code!"))


class FetchLocalTests(unittest.TestCase):
    def test_reads_local_json(self):
        data = fetch(str(FIXTURES / "sample_sampler.json"))
        self.assertIn("threads", data)

    def test_bad_target_raises(self):
        with self.assertRaises(FetchError):
            fetch("definitely not a real code or path !!")


if __name__ == "__main__":
    unittest.main()
