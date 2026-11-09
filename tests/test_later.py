import os
import tempfile
import unittest

from kanban_terminal.app import KanbanApp


class LaterTest(unittest.TestCase):
    def test_plus_tard_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "idee.md")
            with open(p, "w") as f:
                f.write("## Idées\n- [ ] a (#1) @v1\n- [ ] b (#2) @v1 @plus-tard\n")
            app = KanbanApp(p, None, "light", follow=False)
            a, b = app.board.cards
            self.assertEqual(app.tags_of(a), ["v1"])
            self.assertEqual(app.tags_of(b), ["plus-tard"])
            app.tag = "v1"
            self.assertEqual([c.text for c in app.board.cards if app.visible(c)], ["a (#1)"])


if __name__ == "__main__":
    unittest.main()
