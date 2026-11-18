import unittest
from datetime import datetime, timedelta

from kanban_terminal import gantt as gt

PLAN = """# Demo
## Rules
- agents: a, b, you
- unit: 5 min
## Work
- [x] first @volet1 @a
  - gantt: 0-2
- [_] second @volet1 @b
  - gantt: 2-6
  - at: 50%
- [ ] third @volet2 @a
  - gantt: 6-8
- [ ] check @volet2 @you
  - gantt: 8-9
"""


class GanttTest(unittest.TestCase):
    def plan(self, text=PLAN):
        return gt.parse(text.split("\n"))

    def test_parse(self):
        p = self.plan()
        self.assertEqual(p.lanes, ["a", "b", "you"])
        self.assertEqual([t.status for t in p.tasks], ["done", "doing", "todo", "todo"])
        self.assertEqual(p.tasks[1].at, 0.5)
        self.assertEqual(p.end, 9)

    def test_progress_moves_only_with_markers(self):
        # the first unfinished card is « second », half way: 2 + 0.5 * 4
        self.assertEqual(self.plan().progress(), 4)
        self.assertEqual(self.plan(PLAN.replace("at: 50%", "at: 75%")).progress(), 5)
        self.assertEqual(self.plan(PLAN.replace("  - at: 50%\n", "")).progress(), 2)  # no marker: its start
        done = PLAN.replace("[_] second", "[x] second")
        self.assertEqual(self.plan(done).progress(), 6)  # next card: « third » at its start
        # an « at: » on a card still to do does not count
        self.assertEqual(self.plan(PLAN.replace("[_] second", "[ ] second")).progress(), 2)

    def test_clock_and_ahead(self):
        p = self.plan(PLAN.replace("- unit: 5 min", "- unit: 5 min\n- start: 2026-11-18 12:00"))
        now = datetime(2026, 11, 18, 12, 0) + timedelta(minutes=10)
        self.assertEqual(p.clock(now), 2)
        head = gt.render(p, 100, color=False, now=now)[0]
        self.assertIn("10m ahead", head)  # progress 4 slots = 20m, clock 10m

    def test_phase_names_from_tag_descriptions(self):
        legend = "\n".join(gt.render(self.plan(PLAN.replace("- unit: 5 min", "- unit: 5 min\n- @volet2: second part")), 120, color=False))
        self.assertIn("■ second part", legend)       # described
        self.assertIn("■ Work", legend)              # not described: its section

    def test_no_text_in_bars_and_width(self):
        for w in (50, 80, 160):
            lines = gt.render(self.plan(), w, color=False)
            self.assertTrue(all(len(l) <= w for l in lines), w)
            self.assertNotIn("second", "\n".join(lines[2:5]))


if __name__ == "__main__":
    unittest.main()
