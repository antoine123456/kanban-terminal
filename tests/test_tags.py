import asyncio
import os
import tempfile
import unittest

from kanban_terminal.app import KanbanApp, tag_color
from kanban_terminal.model import tag_descriptions

FILE = """## Règles
- @volet1: Prepare
- @idée: pas encore triée

## Travail
- [ ] a card @volet2 @lead
- [ ] another @volet2

## Pending
- [idée] an idea to sort
"""


class TagTest(unittest.TestCase):
    def test_descriptions_from_rules_only(self):
        self.assertEqual(tag_descriptions(FILE.split("\n")), {"volet1": "Prepare", "idée": "pas encore triée"})
        self.assertEqual(tag_descriptions(["## Idées", "- @x: not a description here"]), {})

    def test_colours_are_stable_and_follow_the_gantt(self):
        self.assertEqual(tag_color("volet1"), "blue")
        self.assertEqual(tag_color("v2"), "green")
        self.assertEqual(tag_color("lead"), tag_color("lead"))

    def test_idea_keeps_its_label_when_it_leaves_the_inbox(self):
        """Bug: [idée] showed bold in the inbox, but became a plain @idée at
        the end of the line once moved."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "idee.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(FILE)

            async def go():
                app = KanbanApp(path, follow=False)
                async with app.run_test(size=(120, 24)):
                    card = next(c for c in app.board.cards if c.text == "an idea to sort")
                    before = app.card_text(card, 60)
                    self.assertEqual(app.label_tags(card), ["idée"])
                    app.board.move(card, "todo", "Travail")
                    moved = next(c for c in app.board.cards if c.text == "an idea to sort")
                    self.assertEqual(moved.tags, ["idée"])          # the file says @idée now
                    self.assertEqual(app.label_tags(moved), ["idée"])
                    after = app.card_text(moved, 60)
                    self.assertTrue(after.plain.startswith("▌idée an idea"), after.plain)
                    self.assertEqual(before.plain[:15], after.plain[:15])
                    # milestones colour the bar, the other tags come first
                    a = next(c for c in app.board.cards if c.text == "a card")
                    self.assertEqual(app.bar_color(a), "green")
                    self.assertEqual(app.label_tags(a), ["lead"])
                    self.assertEqual(app.tag_info()["volet2"], "Travail")   # named after its section
            asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
