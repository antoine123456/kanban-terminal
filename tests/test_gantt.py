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


class SelectedRowTest(unittest.TestCase):
    """A row picked with ↑↓ or a click is lit across the whole width."""

    def test_render_lights_the_row(self):
        p = gt.parse(PLAN.split("\n"))
        self.assertEqual(gt.row_count(p, "agent"), 3)
        self.assertEqual(gt.row_count(p, "task"), 4)
        lines = gt.render(p, 80, selected=1)
        row = lines[gt.HEAD_LINES + 1]
        self.assertIn(gt.SELECTED, row)
        others = [l for i, l in enumerate(lines) if i != gt.HEAD_LINES + 1]
        self.assertFalse(any(gt.SELECTED in l for l in others))
        self.assertEqual(len(gt.render(p, 80, selected=1, color=False)[gt.HEAD_LINES + 1]), 80)  # edge to edge

    def test_keys_and_click_in_the_app(self):
        import asyncio, os, tempfile
        from textual.widgets import Static
        from kanban_terminal.app import KanbanApp
        fd, path = tempfile.mkstemp(suffix=".md")
        os.write(fd, PLAN.encode()); os.close(fd)

        async def run():
            app = KanbanApp(path, repo=None)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.press("G")
                await pilot.press("down")
                self.assertEqual(app.gantt_row, 0)
                await pilot.press("down", "down", "down")
                self.assertEqual(app.gantt_row, 0)          # wraps round the 3 agents
                await pilot.press("up")
                self.assertEqual(app.gantt_row, 2)
                await pilot.click("#gantt", offset=(5, gt.HEAD_LINES + 1))
                self.assertEqual(app.gantt_row, 1)
                await pilot.click("#gantt", offset=(5, gt.HEAD_LINES + 1))
                self.assertIsNone(app.gantt_row)            # the lit one again: off
                await pilot.press("G")                       # by task: rows start again
                self.assertIsNone(app.gantt_row)
                await pilot.press("G")                       # back to the board: ↑↓ move cards again
                self.assertFalse(app.check_action("gantt_row", ()))
        try:
            asyncio.run(run())
        finally:
            os.remove(path)
