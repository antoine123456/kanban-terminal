import asyncio
import os
import tempfile
import unittest

from kanban_terminal.model import Board

def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


SAMPLE = """## Règles

-> une règle

## Idées

- [ ] faire une page de connexion (#9) @v2
- [X] toggle type mode @v1
conjugaison:
- [_] tableau de conjugaison (#51)
laisse moi réfléchir
- Estoy aprendiendo
  - une note indentée

## Correction

- [X] police des indices (#121) @v1

## Pending

- [ui] 1. si la carte ne tient pas
  - sous-note
- pourquoi des points
"""


class BoardTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".md")
        os.write(fd, SAMPLE.encode()); os.close(fd)
        self.b = Board(self.path)

    def tearDown(self):
        os.remove(self.path)

    def text(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def card(self, start):
        return next(c for c in self.b.cards if c.text.startswith(start))

    def test_parse(self):
        cols = {c.text[:12]: c.col for c in self.b.cards}
        self.assertEqual(cols["faire une pa"], "todo")
        self.assertEqual(cols["toggle type "], "done")
        self.assertEqual(cols["tableau de c"], "doing")
        self.assertEqual(cols["1. si la car"], "inbox")
        self.assertEqual(len(self.b.cards), 6)  # « Estoy aprendiendo » is a note
        t = self.card("tableau")
        self.assertEqual(t.group, "conjugaison")
        self.assertIn("Estoy aprendiendo", t.notes)
        self.assertEqual(self.card("faire").tags, ["v2"])
        self.assertEqual(self.card("faire").issues, ["9"])
        self.assertEqual(self.card("1. si").custom_mark, "ui")
        self.assertEqual(self.b.work_sections, ["Idées", "Correction"])

    def test_mark_change_keeps_rest(self):
        self.b.move(self.card("faire"), "doing")
        self.assertIn("- [_] faire une page de connexion (#9) @v2\n", self.text())
        self.assertEqual(self.text().replace("- [_] faire", "- [ ] faire"), SAMPLE)

    def test_inbox_to_section_moves_block(self):
        self.b.move(self.card("1. si"), "todo", "Correction")
        t = self.text()
        self.assertIn("- [X] police des indices (#121) @v1\n- [ ] 1. si la carte ne tient pas @ui\n  - sous-note\n", t)
        self.assertNotIn("- [ui]", t)

    def test_back_to_inbox(self):
        self.b.move(self.card("police"), "inbox")
        self.assertIn("- pourquoi des points\n- police des indices (#121) @v1", self.text())

    def test_edit_after_external_change(self):
        c = self.card("police")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# ajouté\n" + SAMPLE)          # lines shifted by someone else
        self.b.set_text(c, "police des indices, italique (#121) @v1")
        self.assertIn("- [X] police des indices, italique (#121) @v1", self.text())

    def test_add_and_issue(self):
        self.b.add("nouvelle idée")
        self.assertTrue(self.text().rstrip().endswith("- nouvelle idée"))
        self.b.add_issue(self.card("nouvelle"), 140, "v1")
        self.assertTrue(self.text().rstrip().endswith("- nouvelle idée (#140) @v1"))


class AppTest(unittest.TestCase):
    def test_ui(self):
        from kanban_terminal.app import KanbanApp
        fd, path = tempfile.mkstemp(suffix=".md")
        os.write(fd, SAMPLE.encode()); os.close(fd)

        async def run():
            app = KanbanApp(path, repo=None)
            app.gh.available = False
            async with app.run_test(size=(140, 16)) as pilot:
                await pilot.pause()
                self.assertEqual(len(app.shown["inbox"]), 2)
                await pilot.press("left")                      # → À trier
                self.assertEqual(app.focused_col(), "inbox")
                await pilot.press("shift+right")               # out of the inbox: pick a section
                await pilot.pause()
                await pilot.press("down", "enter")             # « Correction »
                await pilot.pause()
                self.assertIn("- [ ] 1. si la carte ne tient pas @ui", read(path))
                await pilot.press("4")                         # → Fait
                await pilot.pause()
                self.assertIn("- [X] 1. si la carte ne tient pas @ui", read(path))
                await pilot.press("t")                         # the tag menu (by groups)
                await pilot.pause()
                await pilot.press("u", "i", "enter")           # narrowed to @ui, taken
                await pilot.pause()
                self.assertEqual(app.tag, "ui")
                self.assertEqual(sum(len(v) for v in app.shown.values()), 1)
                await pilot.press("escape")
                await pilot.press("a")
                await pilot.pause()
                await pilot.press(*"idee test", "enter")
                await pilot.pause()
                self.assertIn("- idee test", read(path))
                app.save_screenshot(os.path.join(tempfile.gettempdir(), "kanban_terminal_test.svg"))
        try:
            asyncio.run(run())
        finally:
            os.remove(path)


class ClickTest(unittest.TestCase):
    def test_click_selects_then_opens(self):
        from kanban_terminal.app import Detail, KanbanApp
        fd, path = tempfile.mkstemp(suffix=".md")
        os.write(fd, SAMPLE.encode()); os.close(fd)

        async def run():
            app = KanbanApp(path, repo=None)
            app.gh.available = False
            async with app.run_test(size=(140, 16)) as pilot:
                await pilot.pause()
                lst = app.query_one("#list-inbox")
                await pilot.click("#list-inbox", offset=(3, 1))     # 2nd card, other column
                await pilot.pause()
                self.assertEqual(app.focused_col(), "inbox")
                self.assertEqual(lst.highlighted, 1)
                self.assertNotIsInstance(app.screen, Detail)
                await asyncio.sleep(0.2)
                await pilot.click("#list-inbox", offset=(3, 1))     # same card again → detail
                await pilot.pause()
                self.assertIsInstance(app.screen, Detail)
                await pilot.press("escape")
                await asyncio.sleep(0.2)
                await pilot.click("#list-inbox", offset=(3, 0))     # another card → just selected
                await pilot.pause()
                self.assertEqual(lst.highlighted, 0)
                self.assertNotIsInstance(app.screen, Detail)
        try:
            asyncio.run(run())
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
