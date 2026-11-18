import asyncio
import unittest

from textual.widgets import Input, OptionList

from kanban_terminal.app import KanbanApp

FILE = "## Idées\n- [ ] a @v1 @ui\n- [ ] b @v2\n"


class AnsiThemeTest(unittest.TestCase):
    """With ansi-light, « 50% » colours become the dim attribute, that VS Code's
    terminal draws as black boxes; and a list without focus hides its selection."""

    def test_no_dim_and_visible_selection_in_the_tag_menu(self):
        import os, tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "idee.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(FILE)

        async def go():
            app = KanbanApp(path, follow=False, mode="light")
            async with app.run_test(size=(120, 30)) as pilot:
                self.assertEqual(app.theme, "ansi-light")
                for w in ("#bar", ".col-title"):
                    self.assertFalse(app.query(w).first().rich_style.dim, w)
                await pilot.press("t")
                await pilot.pause(0.2)
                inp = app.screen.query_one("#tag-q", Input)
                self.assertIs(app.screen.focused, inp)
                self.assertFalse(inp.get_component_rich_style("input--placeholder").dim)
                ol = app.screen.query_one("#tag-list", OptionList)
                before = ol.highlighted
                await pilot.press("down")
                self.assertNotEqual(ol.highlighted, before)
                hl = ol.get_component_rich_style("option-list--option-highlighted")
                self.assertIsNotNone(hl.bgcolor)        # visible while the focus is in the filter box
                self.assertNotEqual(hl.bgcolor.name, "default")
                await pilot.press("escape", "slash")
                await pilot.pause(0.2)
                ask = app.screen.query_one(Input)
                self.assertFalse(ask.get_component_rich_style("input--placeholder").dim)

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
