import json
import os
import tempfile
import unittest

from kanban_terminal.snippets import all_tags, main, undescribed

FILE = """## Règles
- @volet1: Prepare
- @v1: old text

## Tags

| tag | description |
|---|---|
| @v1 | version 1 |
| @bug | un bug |

## Travail
- [ ] a card @v1 @lead
"""


class SnippetsTest(unittest.TestCase):
    def test_rules_and_table(self):
        lines = FILE.split("\n")
        self.assertEqual(all_tags(lines), {"volet1": "Prepare", "v1": "version 1", "bug": "un bug"})
        self.assertEqual(undescribed(lines, all_tags(lines)), ["lead"])

    def test_writes_vscode_snippets(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "idee.md"), "w", encoding="utf-8") as f:
                f.write(FILE)
            main([d])
            with open(os.path.join(d, ".vscode", "markdown.code-snippets"), encoding="utf-8") as f:
                f.readline()                       # the « written by » comment
                snip = json.load(f)
            self.assertEqual(snip["@v1"], {"scope": "markdown", "prefix": ["@v1", "v1"],
                                           "body": "@v1$0", "description": "version 1"})


if __name__ == "__main__":
    unittest.main()
