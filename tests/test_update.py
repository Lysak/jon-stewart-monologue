import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from update import classify, seconds  # noqa: E402

NONE = {"include": [], "exclude": []}


class ClassifyTest(unittest.TestCase):
    def test_marker_variants(self):
        for line in ("0:00 - Jon Stewart's TDS Welcome", "0:00 - Jon Stewart’s TDS Open", "0:00 TDS Welcome from Jon Stewart"):
            self.assertEqual(classify("a", "Some title", f"Intro text.\n\n{line}\n5:12 - Next", 1200, NONE), "monologue")

    def test_interview_and_compilation_skipped(self):
        self.assertIsNone(classify("a", "Matthew Cole - Princes and Thieves", "Investigative journalist Matthew Cole sits down with Jon Stewart", 1583, NONE))
        self.assertIsNone(classify("a", "Jon Stewart on French Riots, Kosta on Midterm Meltdowns", "Jon Stewart examines the riots", 2433, NONE))

    def test_recaps_and_shorts_skipped_even_with_marker_or_clef(self):
        marker = "0:00 - Jon Stewart's TDS Welcome"
        self.assertIsNone(classify("a", "Jon Stewart on Iran & Josh Johnson on the Pool | The Daily Show", marker, 2340, NONE))
        self.assertIsNone(classify("a", "Trump's $5K checks? #DailyShow", "Jon Stewart", 95, NONE, 0.95))

    def test_candidate_without_marker(self):
        self.assertEqual(classify("a", "Jon Stewart on Biden's Age", "Jon Stewart breaks down the race", 1300, NONE), "candidate")
        self.assertIsNone(classify("a", "Jon Stewart: Knicks Fan", "Jon Stewart loves the Knicks", 209, NONE))

    def test_overrides_win(self):
        self.assertEqual(classify("x", "t", "", 0, {"include": ["x"], "exclude": []}), "monologue")
        self.assertIsNone(classify("x", "t", "0:00 - Jon Stewart's TDS Welcome", 1200, {"include": [], "exclude": ["x"]}))

    def test_clef_probability_replaces_heuristic(self):
        args = ("a", "Some title", "With two weeks until the election, Jon Stewart sifts", 1016, NONE)
        self.assertIsNone(classify(*args))
        self.assertEqual(classify(*args, 0.95), "candidate")  # no release time: a human decides
        self.assertEqual(classify(*args, 0.6), "candidate")
        self.assertIsNone(classify(*args, 0.1))
        self.assertEqual(classify("a", "t", "0:00 - Jon Stewart's TDS Welcome", 1200, NONE, 0.0), "monologue")

    def test_evening_slot_publishes_clef_monologues(self):
        args = ("a", "Some title", "Trump spent the weekend", 1200, NONE, 0.82)
        self.assertEqual(classify(*args, "2026-10-27T03:00:00Z"), "monologue")  # Mon 23:00 EDT
        self.assertEqual(classify(*args, "2025-01-14T04:00:00Z"), "monologue")  # Mon 23:00 EST
        self.assertEqual(classify(*args, "2024-06-28T04:02:00Z"), "monologue")  # Fri 00:02 EDT, debate special
        self.assertEqual(classify(*args, "2026-10-24T02:29:00Z"), "candidate")  # Fri 22:29 EDT, just before the slot
        self.assertEqual(classify(*args, "2026-10-27T05:01:00Z"), "candidate")  # Tue 01:01 EDT, just after
        self.assertEqual(classify(*args, "2025-06-23T13:00:00Z"), "candidate")  # 09:00 archive re-upload
        self.assertIsNone(classify("a", "Some title", "x", 1200, NONE, 0.12, "2026-10-27T03:30:00Z"))  # interview

    def test_seconds(self):
        self.assertEqual(seconds("PT20M28S"), 1228)
        self.assertEqual(seconds("PT1H2M"), 3720)
        self.assertEqual(seconds("PT45S"), 45)


if __name__ == "__main__":
    unittest.main()
