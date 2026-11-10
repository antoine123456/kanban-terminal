import asyncio
import contextlib
import os
import stat
import tempfile
import unittest

from test_board import SAMPLE


class ClaudeKeyTest(unittest.TestCase):
    def test_x_runs_claude_on_the_card(self):
        from kanban_terminal.app import KanbanApp
        d = tempfile.mkdtemp()
        path = os.path.join(d, "idee.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SAMPLE)
        out = os.path.join(d, "args.txt")
        fake = os.path.join(d, "fake-claude")
        with open(fake, "w") as f:
            f.write(f'#!/bin/sh\npwd > "{out}"; printf "%s" "$1" >> "{out}"\n')
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        os.environ["KANBAN_CLAUDE"] = fake

        async def run():
            app = KanbanApp(path, repo=None)
            app.gh.available = False
            app.suspend = lambda: contextlib.nullcontext()
            async with app.run_test(size=(140, 16)) as pilot:
                await pilot.pause()
                app.query_one("#list-todo").focus()
                await pilot.pause()
                card = app.current()
                await pilot.press("x")
                await pilot.pause()
                got = open(out, encoding="utf-8").read()
                self.assertEqual(os.path.realpath(got.splitlines()[0]), os.path.realpath(d))
                self.assertIn(card.raw.strip(), got)
                self.assertIn("idee.md", got)
                await pilot.press("X")
                await pilot.pause()
                self.assertIn("Pending", open(out, encoding="utf-8").read())
        try:
            asyncio.run(run())
        finally:
            del os.environ["KANBAN_CLAUDE"]


if __name__ == "__main__":
    unittest.main()
