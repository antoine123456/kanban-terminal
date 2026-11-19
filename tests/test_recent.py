import unittest

from kanban_terminal.model import parse, recent_first

FILE = """## Idées
- [X] old one (#3)
- [X] no issue, done right after #3
- [X] newest (#12)
- [ ] still to do (#20)

## Correction
- [X] a fix (#7)
"""


class RecentFirstTest(unittest.TestCase):
    def test_done_by_issue_number_then_line(self):
        cards, _ = parse(FILE.split("\n"))
        done = recent_first([c for c in cards if c.col == "done"])
        self.assertEqual([c.text for c in done],
                         ["newest (#12)", "a fix (#7)", "no issue, done right after #3", "old one (#3)"])


if __name__ == "__main__":
    unittest.main()
