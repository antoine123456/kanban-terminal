import asyncio
import os
import tempfile
import unittest

from kanban_terminal.app import CardList, KanbanApp

SAMPLE = """## Idées

- [ ] first to do (#9)
- [ ] second to do (#10)
- [X] done one (#3)
- [X] done two (#4)
"""


class HoverTest(unittest.TestCase):
    """The mouse over a column's first card lights it up, like the others —
    even though that card carries the column's (blurred, invisible) cursor."""

    def test_first_line_lights_up(self):
        fd, path = tempfile.mkstemp(suffix=".md")
        os.write(fd, SAMPLE.encode()); os.close(fd)

        async def run():
            app = KanbanApp(path, repo=None)
            async with app.run_test(size=(140, 16)) as pilot:
                await pilot.pause()
                done = app.query_one("#list-done", CardList)
                self.assertFalse(done.has_focus)
                self.assertEqual(done.highlighted, 0)
                plain = done.render_line(1)  # second card, no mouse
                done._mouse_hovering_over = 1
                second = done.render_line(1)
                done._mouse_hovering_over = 0
                first = done.render_line(0)
                done._mouse_hovering_over = None
                first_off = done.render_line(0)
                bg = lambda strip: {seg.style.bgcolor for seg in strip if seg.style}
                self.assertNotEqual(bg(second), bg(plain))      # hover shows on the 2nd line
                self.assertEqual(bg(first), bg(second))         # …and on the 1st one too
                self.assertNotEqual(bg(first), bg(first_off))
        try:
            asyncio.run(run())
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
