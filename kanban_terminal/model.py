"""Read a Markdown idea list as a Kanban board, and write changes back.

The file stays the source of truth: every change re-reads it, finds the
card's line again (it may have moved if the file was edited meanwhile),
changes only that line (and its indented notes when a card moves), and
writes the file back. Everything else is kept byte for byte.

Format (the one of idee.md, see README):

    ## Idées                      a section (a category of cards)
    - [ ] to do                   [ ] todo · [_] doing · [x] / [X] done
    - [_] half done (#12) @v1     #12 = GitHub issue, @v1 = tag (milestone)
      - a note                    indented lines = notes of the card above
    conjugaison:                  a group label for the next cards
    ## Pending                    the inbox: every "- " line is a card
    - [ui] an idea to sort        an unknown mark is kept as a tag
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

COLUMNS = [("inbox", "À trier"), ("todo", "À faire"), ("doing", "En cours"), ("done", "Fait")]
MARK_OF = {"todo": " ", "doing": "_", "done": "X"}
COL_OF_MARK = {" ": "todo", "_": "doing", "x": "done", "X": "done"}
INBOX_NAMES = {"pending", "inbox", "à trier", "a trier", "à classer", "todo inbox"}
SKIP_NAMES = {"règles", "regles", "rules"}

ITEM = re.compile(r"^- (?:\[(?P<mark>[^\]]{1,12})\]\s*)?(?P<body>.*)$")
TAG = re.compile(r"(?<!\S)@([\w-]+)")
TAG_INFO = re.compile(r"^- @([\w-]+)\s*(?::|—|=)\s*(.+)$")   # « - @idée: pas encore triée » in Rules
ISSUE = re.compile(r"#(\d+)")


@dataclass
class Card:
    line: int                     # 0-based line number in the file
    raw: str                      # the line as read
    section: str
    col: str
    text: str                     # without tags
    mark: str | None = None
    group: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    note_lines: int = 0           # indented lines that belong to the card

    @property
    def issues(self) -> list[str]:
        return list(dict.fromkeys(ISSUE.findall(self.raw + " " + " ".join(self.notes))))

    @property
    def custom_mark(self) -> str | None:
        return self.mark if self.mark and self.mark not in COL_OF_MARK else None


def recent_first(cards: list[Card]) -> list[Card]:
    """The « Fait » column, most recently done on top: by issue number (#N,
    the highest of the card), a card without one taking the number of the
    card above it in the file (lines are added in order); then the lower line."""
    rank, last = {}, 0
    for c in sorted(cards, key=lambda c: c.line):
        nums = [int(n) for n in c.issues]
        if nums:
            last = max(nums)
        rank[id(c)] = (max(nums) if nums else last, c.line)
    return sorted(cards, key=lambda c: rank[id(c)], reverse=True)


def is_inbox(section: str | None) -> bool:
    return bool(section) and section.strip().lower() in INBOX_NAMES


class Board:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.cards: list[Card] = []
        self.sections: list[str] = []
        self.tag_info: dict[str, str] = {}
        self.mtime = 0.0
        self.load()

    # ── reading ──
    def read_lines(self) -> list[str]:
        with open(self.path, encoding="utf-8") as f:
            return f.read().split("\n")

    def load(self) -> None:
        self.mtime = os.path.getmtime(self.path)
        lines = self.read_lines()
        self.cards, self.sections = parse(lines)
        self.tag_info = tag_descriptions(lines)

    def changed_on_disk(self) -> bool:
        try:
            return os.path.getmtime(self.path) != self.mtime
        except OSError:
            return False

    @property
    def work_sections(self) -> list[str]:
        return [s for s in self.sections if not is_inbox(s) and s.strip().lower() not in SKIP_NAMES]

    @property
    def inbox_section(self) -> str | None:
        return next((s for s in self.sections if is_inbox(s)), None)

    def tags(self) -> list[str]:
        return sorted({t for c in self.cards for t in c.tags})

    def tag_counts(self) -> dict[str, int]:
        """How many cards carry each tag, most used first."""
        n: dict[str, int] = {}
        for c in self.cards:
            for t in c.tags:
                n[t] = n.get(t, 0) + 1
        return dict(sorted(n.items(), key=lambda kv: (-kv[1], kv[0])))

    # ── writing ──
    def _locate(self, lines: list[str], card: Card) -> int:
        """The card's line now: same place if unchanged, else the nearest identical line."""
        if card.line < len(lines) and lines[card.line] == card.raw:
            return card.line
        hits = [i for i, l in enumerate(lines) if l == card.raw]
        if not hits:
            raise LookupError("Carte introuvable : le fichier a changé, rechargé.")
        return min(hits, key=lambda i: abs(i - card.line))

    def _write(self, lines: list[str]) -> None:
        tmp = self.path + ".kanban-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        os.replace(tmp, self.path)
        self.load()

    def _block(self, lines: list[str], i: int) -> int:
        """Number of lines of the card at i (its line + indented notes)."""
        n = 1
        while i + n < len(lines) and lines[i + n].startswith((" ", "\t")) and lines[i + n].strip():
            n += 1
        return n

    def set_text(self, card: Card, text: str) -> None:
        lines = self.read_lines()
        i = self._locate(lines, card)
        lines[i] = compose_line(card.mark, text.strip())
        self._write(lines)

    def move(self, card: Card, col: str, section: str | None = None) -> None:
        """Card to another column. Into or out of the inbox, the line moves to
        that section (``section`` names the target when leaving the inbox)."""
        lines = self.read_lines()
        i = self._locate(lines, card)
        body = lines[i][2:]
        m = ITEM.match(lines[i])
        mark, rest = (m.group("mark"), m.group("body")) if m else (None, body)
        if mark and mark not in COL_OF_MARK:
            rest = f"{rest} @{mark}" if f"@{mark}" not in rest else rest  # [ui] → @ui
        if col == "inbox":
            target = self.inbox_section
            new = f"- {rest}"
        else:
            new = compose_line(MARK_OF[col], rest)
            target = section if is_inbox(card.section) else None
        if not target or target == card.section:
            lines[i] = new
            self._write(lines)
            return
        n = self._block(lines, i)
        block = [new] + lines[i + 1:i + n]
        del lines[i:i + n]
        at = section_end(lines, target)
        if at is None:
            raise LookupError(f"Section « {target} » introuvable.")
        lines[at:at] = block
        self._write(lines)

    def add(self, text: str, section: str | None = None) -> None:
        lines = self.read_lines()
        target = section or self.inbox_section
        line = f"- {text.strip()}" if is_inbox(target) else compose_line(" ", text)
        at = section_end(lines, target) if target else None
        if at is None:
            lines += ["", "## Pending", "", line] if not target else [line]
        else:
            lines.insert(at, line)
        self._write(lines)

    def add_issue(self, card: Card, number: int | str, tag: str | None = None) -> None:
        lines = self.read_lines()
        i = self._locate(lines, card)
        line = lines[i]
        tags = " ".join(f"@{t}" for t in TAG.findall(line))
        core = TAG.sub("", line).rstrip()
        core += f" (#{number})"
        if tag and tag not in TAG.findall(line):
            tags = (tags + f" @{tag}").strip()
        lines[i] = core + (" " + tags if tags else "")
        self._write(lines)


def compose_line(mark: str | None, text: str) -> str:
    return f"- [{mark}] {text}" if mark is not None else f"- {text}"


def section_end(lines: list[str], name: str) -> int | None:
    """Index just after the last non-blank line of section ``name``."""
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].strip() == name), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last = start
    for i in range(start + 1, end):
        if lines[i].strip():
            last = i
    return last + 1


def tag_descriptions(lines: list[str]) -> dict[str, str]:
    """What each tag means, written in the Rules section: « - @volet1: Prepare »."""
    info, section = {}, None
    for line in lines:
        if line.startswith("## "):
            section = line[3:].strip().lower()
        elif section in SKIP_NAMES and (m := TAG_INFO.match(line.strip())):
            info[m.group(1)] = m.group(2).strip()
    return info


def parse(lines: list[str]) -> tuple[list[Card], list[str]]:
    cards: list[Card] = []
    sections: list[str] = []
    section = group = None
    card = last = None
    for n, line in enumerate(lines):
        if line.startswith("## "):
            section = line[3:].strip()
            sections.append(section)
            group = card = last = None
            continue
        if section is None or section.strip().lower() in SKIP_NAMES:
            continue
        if not line.strip():
            card = group = None
            continue
        m = ITEM.match(line)
        if m and m.group("mark") is None and not is_inbox(section) and last:
            last.notes.append(m.group("body"))       # « - Estoy aprendiendo »: brainstorm under an idea
            continue
        if m:
            mark, body = m.group("mark"), m.group("body")
            if is_inbox(section):
                col = "inbox"
            else:
                col = COL_OF_MARK.get(mark or "", "todo" if mark is None else "inbox")
            tags = TAG.findall(body)
            card = Card(line=n, raw=line, section=section, col=col, mark=mark, group=group,
                        text=TAG.sub("", body).strip(), tags=tags)
            cards.append(card)
            last = card
        elif line.startswith((" ", "\t")) and card:
            card.notes.append(line.strip().lstrip("- "))
            card.note_lines += 1
        elif re.match(r"^[^-#].*:\s*$", line):
            group, card = line.strip().rstrip(":").strip(), None
        elif card:
            card.notes.append(line.strip())
    return cards, sections
