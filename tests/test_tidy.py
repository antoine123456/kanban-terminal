import os
import tempfile
import unittest

from kanban_terminal import tidy

FILE = """## Tags

| tag | description |
|---|---|
| @v1 | version 1 |

## Idées

- [ ] something @v1 (#3)

## Pending

answered before
  → the answer

@ankiterm better timing: for instance "  a tiempo
  › q

3 carte(s) en 8229 min
see @this

- @bug a bug
- P7 @v1 already numbered
"""


class TidyTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".md")
        os.write(fd, FILE.encode()); os.close(fd)

    def tearDown(self):
        os.remove(self.path)
        snip = os.path.join(os.path.dirname(self.path), ".vscode", "markdown.code-snippets")
        if os.path.exists(snip):
            os.remove(snip)

    def text(self):
        return open(self.path, encoding="utf-8").read()

    def test_numbers_tags_and_is_stable(self):
        self.assertTrue(tidy.tidy(self.path))
        t = self.text()
        self.assertIn("- P1 @ankiterm better timing", t)
        self.assertIn("- P2 @bug a bug", t)
        self.assertIn("- P3 @v1 already numbered", t)
        self.assertIn("answered before\n", t)                 # not an item: left alone
        self.assertIn("\n3 carte(s) en 8229 min\n", t)        # a pasted log: left alone
        self.assertIn("| @ankiterm | à décrire |", t)         # used in Pending, described nowhere
        self.assertNotIn("| @this |", t)
        self.assertEqual(t.count("| @bug |"), 1)
        self.assertFalse(tidy.tidy(self.path))                # nothing left to do
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(self.path), ".vscode", "markdown.code-snippets")))


if __name__ == "__main__":
    unittest.main()
