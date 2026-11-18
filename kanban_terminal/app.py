"""kanban-terminal: a Markdown idea list as an interactive Kanban board in the
terminal — small enough for VS Code's bottom panel."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
import zlib

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Footer, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from . import gantt as gt
from . import junit
from . import theme as th
from .gh import GitHub, milestone_tag, tag_milestone
from .model import COLUMNS, Board, Card, is_inbox

COL_NAMES = dict(COLUMNS)
SECTION_COLORS = ["#4f8ff7", "#f25f5c", "#b48ead", "#56b6c2", "#e5c07b"]
INBOX_COLOR = "#d7a700"
MUTED = "bright_black"  # the terminal's grey: "dim" turns into black boxes in VS Code's terminal
LATER = "plus-tard"  # the tag that puts a card aside


class CardList(OptionList):
    """A column. A click selects the card; a click on the card already
    selected (in the focused column) opens its detail."""

    _focused_at = 0.0
    _armed: int | None = None

    def _on_focus(self, event: events.Focus) -> None:
        self._focused_at = time.monotonic()

    def _on_mouse_down(self, event: events.MouseDown) -> None:
        # Focus comes with this very press when the column wasn't focused.
        was_focused = time.monotonic() - self._focused_at > 0.15
        self._armed = self.highlighted if was_focused else None

    async def _on_click(self, event: events.Click) -> None:
        event.prevent_default()
        i = event.style.meta.get("option")
        if i is None:
            return
        if i == self._armed:
            self.action_select()
        else:
            self.highlighted = i
        self._armed = None


# ── Tags: groups and completion ──
TYPE_TAGS = {"bug", "feature", "idée", "idee", "question", "ui", "doc", "perf"}
TAG_GROUPS = ["Jalons", "Type", "Thèmes"]


# Milestones colour the card's left bar, like the Gantt's phases (same order);
# the other tags are a bold coloured word before the text.
PHASE_COLORS = ["blue", "green", "magenta", "cyan", "yellow", "red"]
TYPE_COLORS = {"bug": "red", "feature": "green", "idée": INBOX_COLOR, "idee": INBOX_COLOR,
               "question": INBOX_COLOR, "ui": "magenta", "doc": "cyan", "perf": "#d19a66"}
THEME_COLORS = ["#4f8ff7", "#c678dd", "#56b6c2", "#2e9e6a", "#d19a66", "#e06c75", "#b48ead", "#d7a700"]
MILESTONE = re.compile(r"(?:v|volet|phase)(\d+)$", re.I)


def tag_color(tag: str) -> str:
    """Always the same colour for a tag (between runs too)."""
    t = tag.lower()
    if m := MILESTONE.fullmatch(t):
        return PHASE_COLORS[(int(m.group(1)) - 1) % len(PHASE_COLORS)]
    if t == LATER:
        return "#777777"
    return TYPE_COLORS.get(t) or THEME_COLORS[zlib.crc32(t.encode()) % len(THEME_COLORS)]


def tag_group(tag: str) -> str:
    """The tags in three groups (a hierarchy for the t menu): the milestones
    (@v1, @v2, @volet1, @plus-tard), the kind of card (@bug, @feature…) and the
    rest — what the card is about (@helmoltz, @kanban…)."""
    t = tag.lower()
    if re.fullmatch(r"v\d+|volet\d+", t) or t == LATER:
        return "Jalons"
    return "Type" if t in TYPE_TAGS else "Thèmes"


class TagSuggester(Suggester):
    """After an @, the most used tag that starts with what's typed (Tab or →
    takes it)."""

    def __init__(self, tags: list[str]):
        super().__init__(use_cache=False, case_sensitive=True)
        self.tags = tags  # most used first

    async def get_suggestion(self, value: str) -> str | None:
        m = re.search(r"@([\w\-]*)$", value)
        if not m:
            return None
        pre = m.group(1).lower()
        t = next((t for t in self.tags if t.lower().startswith(pre) and t.lower() != pre), None)
        return value + t[len(pre):] if t else None


# ── Small dialogs ──
class Ask(ModalScreen[str | None]):
    """One line of text (add, edit, search); with tags, @ completes them."""
    BINDINGS = [Binding("escape", "cancel", "Annuler"), Binding("tab", "complete", show=False, priority=True)]

    def __init__(self, title: str, value: str = "", placeholder: str = "", tags: list[str] | None = None):
        super().__init__()
        self.title_, self.value, self.placeholder, self.tags = title, value, placeholder, tags

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="dlg-title")
            yield Input(value=self.value, placeholder=self.placeholder,
                        suggester=TagSuggester(self.tags) if self.tags else None)
            hint = "Entrée pour valider · Échap pour annuler"
            if self.tags:
                hint += " · @ puis Tab : tag (les plus utilisés d'abord : " + " ".join("@" + t for t in self.tags[:5]) + ")"
            yield Label(hint, classes="dlg-hint")

    def action_complete(self) -> None:
        inp = self.query_one(Input)
        if inp._suggestion and len(inp._suggestion) > len(inp.value):
            inp.value = inp._suggestion + " "
            inp.cursor_position = len(inp.value)

    @on(Input.Submitted)
    def done(self, e: Input.Submitted) -> None:
        self.dismiss(e.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Choose(ModalScreen[str | None]):
    """Pick one entry (target section, confirmation)."""
    BINDINGS = [Binding("escape", "cancel", "Annuler")]

    def __init__(self, title: str, choices: list[str]):
        super().__init__()
        self.title_, self.choices = title, choices

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="dlg-title")
            yield OptionList(*[Option(c, id=str(i)) for i, c in enumerate(self.choices)])

    @on(OptionList.OptionSelected)
    def picked(self, e: OptionList.OptionSelected) -> None:
        self.dismiss(self.choices[int(e.option.id)])

    def action_cancel(self) -> None:
        self.dismiss(None)


class TagPicker(ModalScreen[str | None]):
    """t: the tags to show, by group, the most used first; type to narrow.
    Returns the tag, "" for all of them, None when left with Échap."""
    BINDINGS = [Binding("escape", "cancel", "Annuler")]

    def __init__(self, counts: dict[str, int], current: str | None, info: dict[str, str] | None = None):
        super().__init__()
        self.counts, self.current, self.info = counts, current, info or {}

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Afficher le tag…", classes="dlg-title")
            yield Input(placeholder="filtrer…", id="tag-q")
            yield OptionList(id="tag-list")
            yield Label("↑↓ puis Entrée · tape pour filtrer · Échap pour annuler", classes="dlg-hint")

    def on_mount(self) -> None:
        self.fill("")

    def fill(self, q: str) -> None:
        ol = self.query_one("#tag-list", OptionList)
        ol.clear_options()
        q = q.strip().lstrip("@").lower()
        opts: list[Option] = []
        if not q:
            opts.append(Option(("● " if not self.current else "  ") + "tous les tags", id="__all__"))
        for g in TAG_GROUPS:
            ts = [(t, n) for t, n in self.counts.items() if tag_group(t) == g and q in t.lower()]
            if g == "Jalons":   # in their order (@v1, @v2… / @volet1, @volet2…), not by use
                ts.sort(key=lambda tn: (int(m.group(1)) if (m := MILESTONE.fullmatch(tn[0].lower())) else 10**6, tn[0]))
            if not ts:
                continue
            opts.append(Option(Text(g, style=f"bold {MUTED}"), disabled=True))
            for t, n in ts:
                mark = "● " if t == self.current else "  "
                opts.append(Option(Text.assemble(f"{mark}  ", (f"@{t}", f"bold {tag_color(t)}"), (f"  {n}", MUTED),
                                                 (f"  {self.info[t]}" if t in self.info else "", MUTED)), id=t))
        ol.add_options(opts)
        first = next((i for i, o in enumerate(opts) if not o.disabled and (q or o.id == (self.current or "__all__"))), None)
        if first is not None:
            ol.highlighted = first

    @on(Input.Changed, "#tag-q")
    def narrow(self, e: Input.Changed) -> None:
        self.fill(e.value)

    @on(Input.Submitted, "#tag-q")
    def take_first(self, e: Input.Submitted) -> None:
        ol = self.query_one("#tag-list", OptionList)
        if ol.highlighted is not None:
            o = ol.get_option_at_index(ol.highlighted)
            self.dismiss("" if o.id == "__all__" else o.id)

    def on_key(self, e: events.Key) -> None:  # ↑↓ from the filter box move in the list
        if e.key in ("up", "down") and self.focused is self.query_one("#tag-q"):
            ol = self.query_one("#tag-list", OptionList)
            (ol.action_cursor_up if e.key == "up" else ol.action_cursor_down)()
            e.stop()

    @on(OptionList.OptionSelected, "#tag-list")
    def picked(self, e: OptionList.OptionSelected) -> None:
        self.dismiss("" if e.option.id == "__all__" else e.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Detail(ModalScreen[None]):
    BINDINGS = [Binding("escape,enter,q", "close", "Fermer")]

    def __init__(self, body: Text):
        super().__init__()
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Static(self.body)
            yield Label("Échap pour fermer", classes="dlg-hint")

    def action_close(self) -> None:
        self.dismiss(None)


HELP = """[b]Se déplacer[/b]  ←→ colonne · ↑↓ carte · Entrée détail · clic : sélectionner, re-clic : détail
[b]Déplacer la carte[/b]  ⇧← ⇧→ (ou < >) · 1 À trier · 2 À faire · 3 En cours · 4 Fait
[b]Écrire[/b]  a ajouter (dans À trier) · e modifier le texte · E ouvrir dans l'éditeur à la ligne
[b]GitHub[/b]  o ouvrir l'issue · i créer l'issue de la carte · c fermer / rouvrir l'issue · g actualiser
[b]Tags[/b]  @volet1, @v2… colorent la barre de gauche · les autres s'écrivent en gras, en couleur, avant le texte · leur sens : « - @tag: description » dans Règles (montré par t et Entrée)
[b]Filtres[/b]  / chercher · t choisir le tag (par groupes : jalons, type, thèmes) · s section · f cacher « Fait » · w texte complet · Échap tout effacer
[b]Gantt[/b]  G : tableau → Gantt par agent → par tâche → tableau · notes « gantt: a-b », lignes agents: / unit: / start: dans Règles · ligne rouge = avancement (cartes cochées, notes « at: 60% »), ┊ = horloge
[b]Tests[/b]  U : la barre verte / rouge façon JUnit (pytest, unittest, Maven, Gradle) · ↑↓ un test → sa trace · r relancer · commande : tests
[b]Fichier[/b]  rechargé tout seul quand il change · r recharger · q quitter
[b]Thème[/b]  clair / sombre comme VS Code (suit ses changements) · T basculer à la main
[b]Claude[/b]  x traiter la carte avec Claude · X traiter « À trier » (Pending) · le tableau revient quand Claude se ferme"""


class KanbanApp(App):
    TITLE = "kanban"
    CSS = """
    Screen { layout: vertical; }
    #bar { height: 1; padding: 0 1; background: $panel; color: $muted; }
    #board { height: 1fr; }
    .col { width: 1fr; height: 1fr; border: round $panel-lighten-2; padding: 0; }
    .col:focus-within { border: round $accent; }
    .col.hidden { display: none; }
    .col-title { height: 1; padding: 0 1; text-style: bold; color: $muted; }
    .col OptionList { height: 1fr; border: none; padding: 0; background: transparent; scrollbar-size-vertical: 1; }
    .col OptionList:focus { border: none; }
    #gantt { height: 1fr; padding: 0 1; display: none; overflow-y: auto; }
    .gantt-view #gantt { display: block; }
    .gantt-view #board, .gantt-view #detail { display: none; }
    #tests { height: 1fr; display: none; padding: 0 1; }
    .tests-view #tests { display: block; }
    .tests-view #board, .tests-view #detail { display: none; }
    #tests-head { height: auto; }
    #tests-list { height: 1fr; border: none; padding: 0; background: transparent; }
    #tests-trace { height: auto; max-height: 45%; overflow-y: auto; padding: 0 0 0 2; }
    /* ANSI themes turn « 50% » colours into the dim attribute (black boxes in
       VS Code) and draw a list's selection invisible when the focus is elsewhere. */
    Input > .input--placeholder, Input > .input--suggestion { color: $muted; text-style: none; }
    .dialog OptionList > .option-list--option-highlighted, #tests-list > .option-list--option-highlighted {
        color: $block-cursor-foreground; background: $block-cursor-background; text-style: bold;
    }
    #detail { height: auto; max-height: 3; padding: 0 1; color: $text; background: $boost; }
    ModalScreen { align: center middle; }
    .dialog { width: 70%; max-width: 100; height: auto; max-height: 90%; border: round $accent; background: $surface; padding: 0 1; }
    .dialog.wide { width: 90%; max-width: 140; }
    .dialog OptionList { height: auto; max-height: 12; border: none; }
    .dlg-title { text-style: bold; padding: 0 0 1 0; }
    .dlg-hint { color: $muted; }
    """
    BINDINGS = [
        Binding("left,h", "col(-1)", "←", show=False),
        Binding("right,l", "col(1)", "→", show=False),
        Binding("shift+left,less_than_sign", "move(-1)", "⇧← déplacer", show=False),
        Binding("shift+right,greater_than_sign", "move(1)", "⇧→ déplacer"),
        Binding("1", "move_to('inbox')", show=False), Binding("2", "move_to('todo')", show=False),
        Binding("3", "move_to('doing')", show=False), Binding("4", "move_to('done')", show=False),
        Binding("a", "add", "ajouter"), Binding("e", "edit", "modifier"), Binding("E", "editor", show=False),
        Binding("o", "open_issue", "issue"), Binding("i", "create_issue", show=False), Binding("c", "close_issue", show=False),
        Binding("slash", "search", "chercher"), Binding("t", "cycle_tag", "tag"), Binding("s", "cycle_section", show=False),
        Binding("f", "toggle_done", show=False), Binding("w", "toggle_wrap", show=False), Binding("escape", "clear_filters", show=False),
        Binding("g", "refresh_gh", show=False), Binding("T", "toggle_mode", show=False), Binding("r", "reload", show=False),
        Binding("G", "toggle_gantt", "gantt"), Binding("U", "toggle_tests", "tests"),
        Binding("x", "claude", "claude"), Binding("X", "claude_inbox", show=False),
        Binding("question_mark", "help", "aide"), Binding("q", "quit", "quitter"),
    ]

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """$muted: the terminal's grey, never a « 50% » colour (see CSS)."""
        return {**super().get_theme_variable_defaults(), "muted": "ansi_bright_black"}

    def __init__(self, path: str, repo: str | None = None, mode: str = th.DARK, follow: bool = True):
        super().__init__()
        self.mode = mode          # light / dark, like the editor around (theme.py)
        self.follow = follow      # keep following VS Code / the OS when they change
        self._sys_mode: str | None = None
        self.board = Board(path)
        self.gh = GitHub(os.path.dirname(self.board.path), repo)
        self.query_text = ""
        self.tag: str | None = None
        self.section: str | None = None
        self.hide_done = False
        self.wrap = False
        self.shown: dict[str, list[Card]] = {}
        self.gantt_by: str | None = None   # None: the board · "agent" / "task": the Gantt view
        self.test_view = False             # U: the JUnit-style test view
        self.tests: junit.Result | None = None
        self.tests_running = False

    # ── layout ──
    def compose(self) -> ComposeResult:
        yield Static(id="bar")
        with Horizontal(id="board"):
            for key, name in COLUMNS:
                with Vertical(classes="col", id=f"col-{key}"):
                    yield Label(name, classes="col-title", id=f"title-{key}")
                    yield CardList(id=f"list-{key}")
        yield Static(id="gantt")
        with Vertical(id="tests"):
            yield Static(id="tests-head")
            yield OptionList(id="tests-list")
            yield Static(id="tests-trace")
        yield Static(id="detail")
        yield Footer()

    def on_resize(self) -> None:
        self.call_after_refresh(self.rebuild)
        if self.test_view:   # the bar follows the width
            self.call_after_refresh(lambda: self.query_one("#tests-head", Static).update(
                self.test_head(max(self.query_one("#tests-head", Static).size.width, 20))))

    def on_mount(self) -> None:
        self.apply_mode()
        if self.follow:
            self._sys_mode = th.from_settings()
            self.set_interval(3.0, self.check_mode)
        self.rebuild()
        self.call_after_refresh(self.rebuild)
        self.query_one("#list-todo", OptionList).focus()
        self.set_interval(1.0, self.watch_file)
        self.set_interval(5.0, self.draw_gantt)   # the red line follows the clock
        self.load_issues()

    # ── light / dark ──
    def apply_mode(self) -> None:
        self.theme = "ansi-light" if self.mode == th.LIGHT else "textual-dark"

    @work(thread=True, exclusive=True, group="mode")
    def check_mode(self) -> None:
        """VS Code (or the OS) switched day / night: the board follows."""
        m = th.from_settings()
        if m and m != self._sys_mode:
            self._sys_mode = m
            self.mode = m
            self.call_from_thread(self.apply_mode)

    def action_toggle_mode(self) -> None:
        self.mode = th.DARK if self.mode == th.LIGHT else th.LIGHT
        self.apply_mode()

    # ── data → screen ──
    def section_color(self, section: str) -> str:
        if is_inbox(section):
            return INBOX_COLOR
        ws = self.board.work_sections
        return SECTION_COLORS[ws.index(section) % len(SECTION_COLORS)] if section in ws else "#888888"

    def tag_info(self) -> dict[str, str]:
        """The descriptions of the Rules section; a milestone without one is
        named after the section that holds all its cards (@volet1 → « 1 · Prepare »)."""
        info = dict(self.board.tag_info)
        for t in self.board.tags():
            if t not in info and tag_group(t) == "Jalons" and t != LATER:
                secs = {c.section for c in self.board.cards if t in c.tags and not is_inbox(c.section)}
                if len(secs) == 1:
                    info[t] = secs.pop()
        return info

    def bar_color(self, c: Card) -> str:
        """The left bar: the card's milestone, else its section."""
        if LATER in c.tags:
            return "#777777"
        m = next((t for t in c.tags if MILESTONE.fullmatch(t.lower())), None)
        return tag_color(m) if m else self.section_color(c.section)

    @staticmethod
    def label_tags(c: Card) -> list[str]:
        """The tags written before the text: all but the milestones (they colour
        the bar). The inbox mark [idée] and the tag @idée look the same."""
        tags = [LATER] if LATER in c.tags else [t for t in c.tags if not MILESTONE.fullmatch(t.lower())]
        if c.custom_mark and c.custom_mark not in tags:
            tags.insert(0, c.custom_mark)
        return tags

    @staticmethod
    def tags_of(c: Card) -> list[str]:
        """@plus-tard wins over the other tags: the card is put aside, whatever
        its version (@v1 @plus-tard → only @plus-tard, and it isn't under the @v1 filter)."""
        return [LATER] if LATER in c.tags else c.tags

    def visible(self, c: Card) -> bool:
        if self.tag and self.tag not in self.tags_of(c):
            return False
        if self.section and c.section != self.section and not is_inbox(c.section):
            return False
        if self.query_text:
            hay = (c.text + " " + " ".join(c.notes) + " " + " ".join(c.tags) + " " + (c.group or "")).lower()
            return all(w in hay for w in self.query_text.lower().split())
        return True

    def card_text(self, c: Card, width: int = 0) -> Text:
        head = Text()
        later = LATER in c.tags  # put aside: the whole card goes quiet
        head.append("▌", style=self.bar_color(c))
        for tg in self.label_tags(c):
            head.append(f"{tg} ", style=f"{MUTED} italic" if later else f"bold {tag_color(tg)}")
        body = Text(re.sub(r"\s*\(#\d+\)", "", c.text), style=f"{MUTED} italic" if later else MUTED if c.col == "done" else "")  # the issue is a chip
        tail = Text()
        for n in c.issues:
            st = self.gh.state(n)
            tail.append(f" #{n}{'✓' if st == 'closed' else ''}", style=MUTED if later else "green" if st == "closed" else "cyan")
        if c.notes:
            tail.append(f" +{len(c.notes)}", style=MUTED)
        # One line per card by default (a short bottom panel shows more), w
        # unfolds; the text is cut, never the issue / tag chips.
        if not self.wrap and width > 4:
            room = width - head.cell_len - tail.cell_len
            if room < 8:
                tail = Text()
                room = width - head.cell_len
            if body.cell_len > room:
                body.truncate(max(1, room - 1))
                body.append("…", style=MUTED)
        return Text.assemble(head, body, tail)

    def rebuild(self, keep: tuple[str, str] | None = None) -> None:
        keep = keep or self.current_key()
        for key, _ in COLUMNS:
            cards = [c for c in self.board.cards if c.col == key and self.visible(c)]
            self.shown[key] = cards
            ol = self.query_one(f"#list-{key}", OptionList)
            hi = ol.highlighted
            ol.clear_options()
            width = ol.size.width - 1  # scrollbar
            ol.add_options([Option(self.card_text(c, width), id=str(i)) for i, c in enumerate(cards)])
            if cards:
                idx = next((i for i, c in enumerate(cards) if keep and (c.text, c.section) == keep), None)
                ol.highlighted = idx if idx is not None else min(hi or 0, len(cards) - 1)
            total = sum(1 for c in self.board.cards if c.col == key)
            n = len(cards)
            self.query_one(f"#title-{key}", Label).update(f"{COL_NAMES[key]}  {n}" + (f"/{total}" if n != total else ""))
        self.query_one("#col-done").set_class(self.hide_done, "hidden")
        self.update_bar()
        self.update_detail()
        self.draw_gantt()

    def update_bar(self) -> None:
        parts = [os.path.basename(self.board.path)]
        if self.gh.ok:
            parts.append(self.gh.repo + ("" if self.gh.issues else " (issues…)"))
        f = []
        if self.tag:
            f.append(f"@{self.tag}")
        if self.section:
            f.append(f"section {self.section}")
        if self.query_text:
            f.append(f"« {self.query_text} »")
        if self.hide_done:
            f.append("sans Fait")
        bar = "  ·  ".join(parts) + ("   filtres : " + ", ".join(f) + " (Échap)" if f else "   ? aide")
        self.query_one("#bar", Static).update(bar)

    def focused_col(self) -> str:
        w = self.focused
        if isinstance(w, OptionList) and (w.id or "").startswith("list-"):
            return w.id[5:]
        return "todo"

    def current(self) -> Card | None:
        key = self.focused_col()
        ol = self.query_one(f"#list-{key}", OptionList)
        cards = self.shown.get(key) or []
        if ol.highlighted is None or ol.highlighted >= len(cards):
            return None
        return cards[ol.highlighted]

    def current_key(self) -> tuple[str, str] | None:
        try:
            c = self.current()
        except Exception:
            return None
        return (c.text, c.section) if c else None

    def update_detail(self) -> None:
        c = self.current()
        d = self.query_one("#detail", Static)
        if not c:
            d.update(Text("—", style=MUTED))
            return
        t = Text()
        t.append(f"{c.section}", style=f"bold {self.section_color(c.section)}")
        if c.group:
            t.append(f" › {c.group}", style=MUTED)
        t.append(f"  l.{c.line + 1}  ", style=MUTED)
        t.append(c.text)
        d.update(t)

    @on(OptionList.OptionHighlighted)
    def highlighted(self, e: OptionList.OptionHighlighted) -> None:
        if (e.option_list.id or "").startswith("list-"):
            self.update_detail()

    def on_descendant_focus(self) -> None:
        self.update_detail()

    @on(OptionList.OptionSelected)
    def selected(self, e: OptionList.OptionSelected) -> None:
        if (e.option_list.id or "").startswith("list-"):
            self.action_detail()

    # ── file / GitHub ──
    def watch_file(self) -> None:
        if self.board.changed_on_disk():
            self.reload(quiet=False)

    def reload(self, quiet: bool = True) -> None:
        keep = self.current_key()
        try:
            self.board.load()
        except OSError as err:
            self.notify(str(err), severity="error")
            return
        self.rebuild(keep)
        if not quiet:
            self.notify(f"{os.path.basename(self.board.path)} rechargé", timeout=2)

    @work(thread=True, exclusive=True)
    def load_issues(self) -> None:
        if not self.gh.ok:
            return
        try:
            self.gh.refresh()
        except Exception as err:
            self.call_from_thread(self.notify, f"GitHub : {err}", severity="warning")
            return
        self.call_from_thread(self.rebuild)

    def guard(self, fn, *a) -> bool:
        try:
            fn(*a)
            return True
        except LookupError as err:
            self.notify(str(err), severity="warning")
            self.reload()
            return False

    # ── actions ──
    def action_col(self, step: int) -> None:
        keys = [k for k, _ in COLUMNS if not (k == "done" and self.hide_done)]
        cur = self.focused_col()
        i = keys.index(cur) if cur in keys else 1
        self.query_one(f"#list-{keys[(i + step) % len(keys)]}", OptionList).focus()

    def action_move(self, step: int) -> None:
        keys = [k for k, _ in COLUMNS]
        c = self.current()
        if not c:
            return
        i = keys.index(c.col) + step
        if 0 <= i < len(keys):
            self.action_move_to(keys[i])

    def action_move_to(self, col: str) -> None:
        c = self.current()
        if not c or c.col == col:
            return
        if is_inbox(c.section) and col != "inbox":
            ws = self.board.work_sections
            if len(ws) == 1:
                self._do_move(c, col, ws[0])
            else:
                self.push_screen(Choose(f"Dans quelle section ? « {c.text[:60]} »", ws),
                                 lambda s: s and self._do_move(c, col, s))
            return
        self._do_move(c, col, None)

    def _do_move(self, c: Card, col: str, section: str | None) -> None:
        key = (c.text, section or (self.board.inbox_section if col == "inbox" else c.section))
        if not self.guard(self.board.move, c, col, section):
            return
        self.rebuild(key)
        self.query_one(f"#list-{col}", OptionList).focus()
        self.call_after_refresh(self.rebuild, key)
        open_issues = [n for n in c.issues if self.gh.state(n) == "open"]
        if col == "done" and open_issues and self.gh.ok:
            nums = ", ".join("#" + n for n in open_issues)
            self.push_screen(Choose(f"Fermer {nums} sur GitHub ?", ["Oui, fermer", "Non"]),
                             lambda r: r and r.startswith("Oui") and self.close_issues(open_issues))

    @work(thread=True)
    def close_issues(self, nums: list[str]) -> None:
        for n in nums:
            try:
                self.gh.close(n)
                self.call_from_thread(self.notify, f"#{n} fermée")
            except Exception as err:
                self.call_from_thread(self.notify, f"#{n} : {err}", severity="error")
        self.call_from_thread(self.rebuild)

    def action_add(self) -> None:
        def done(text):
            if text and text.strip():
                self.board.add(text)
                self.rebuild((text.strip(), self.board.inbox_section))
                self.query_one("#list-inbox", OptionList).focus()
        self.push_screen(Ask("Nouvelle idée (dans « À trier »)", placeholder="texte… (#12 pour une issue, @v1 pour un tag)",
                             tags=list(self.board.tag_counts())), done)

    def action_edit(self) -> None:
        c = self.current()
        if not c:
            return
        full = c.text + "".join(f" @{t}" for t in c.tags)

        def done(text):
            if text and text.strip() and text.strip() != full:
                if self.guard(self.board.set_text, c, text):
                    self.rebuild()
        self.push_screen(Ask("Modifier la carte", full, tags=list(self.board.tag_counts())), done)

    def action_editor(self) -> None:
        c = self.current()
        if not c:
            return
        where = f"{self.board.path}:{c.line + 1}"
        if shutil.which("code"):
            subprocess.Popen(["code", "-g", where])
            return
        editor = os.environ.get("EDITOR", "vi")
        with self.suspend():
            subprocess.call([editor, f"+{c.line + 1}", self.board.path])
        self.reload()

    # ── Claude (#185): the board steps aside, Claude Code runs in this very
    # terminal, in the file's folder; the board comes back (reloaded) when
    # Claude is closed. KANBAN_CLAUDE changes the command (default: claude).
    def run_claude(self, prompt: str) -> None:
        cmd = os.environ.get("KANBAN_CLAUDE", "claude").split()
        if not shutil.which(cmd[0]):
            self.notify(f"« {cmd[0]} » introuvable (Claude Code n'est pas installé ?)", severity="error")
            return
        with self.suspend():
            subprocess.call(cmd + [prompt], cwd=os.path.dirname(os.path.abspath(self.board.path)))
        self.reload()

    def action_claude(self) -> None:
        c = self.current()
        if not c:
            return
        name = os.path.basename(self.board.path)
        self.run_claude(f"Traite cette carte de {name} (section « {c.section} », ligne {c.line + 1}) :\n{c.raw.strip()}"
                        + "".join("\n" + n for n in c.notes))

    def action_claude_inbox(self) -> None:
        self.run_claude(f"Exécute « Pending » : traite les idées de la boîte de réception de {os.path.basename(self.board.path)}.")

    def action_open_issue(self) -> None:
        c = self.current()
        if not c or not c.issues:
            self.notify("Pas d'issue sur cette carte (i pour en créer une)")
            return
        if not self.gh.repo:
            self.notify("Dépôt GitHub inconnu (--repo propriétaire/nom)", severity="warning")
            return
        if len(c.issues) == 1:
            webbrowser.open(self.gh.url(c.issues[0]))
        else:
            self.push_screen(Choose("Quelle issue ?", ["#" + n + "  " + (self.gh.issues.get(n) or {}).get("title", "")[:70] for n in c.issues]),
                             lambda r: r and webbrowser.open(self.gh.url(r.split()[0][1:])))

    def action_create_issue(self) -> None:
        c = self.current()
        if not c or not self.gh.ok:
            if not self.gh.ok:
                self.notify("gh ou dépôt GitHub indisponible", severity="warning")
            return
        ms = next((tag_milestone(t, self.gh.milestones) for t in self.tags_of(c) if tag_milestone(t, self.gh.milestones)), None)
        choices = ([ms] if ms else []) + [m for m in self.gh.milestones if m != ms] + ["(sans milestone)"]

        def picked(m):
            if m is None:
                return
            self.make_issue(c, None if m == "(sans milestone)" else m)
        self.push_screen(Choose(f"Créer l'issue « {c.text[:60]} » — milestone :", choices), picked)

    @work(thread=True)
    def make_issue(self, c: Card, milestone: str | None) -> None:
        label = "bug" if c.section.lower().startswith(("correction", "bug")) else "enhancement"
        try:
            n = self.gh.create(c.text[:240], milestone, label)
        except Exception as err:
            self.call_from_thread(self.notify, f"GitHub : {err}", severity="error")
            return
        self.call_from_thread(self.guard, self.board.add_issue, c, n, milestone_tag(milestone or ""))
        self.call_from_thread(self.notify, f"#{n} créée")
        self.gh.refresh()
        self.call_from_thread(self.rebuild)

    def action_close_issue(self) -> None:
        c = self.current()
        if not c or not c.issues or not self.gh.ok:
            return
        n = c.issues[0]
        st = self.gh.state(n)
        verb = "Rouvrir" if st == "closed" else "Fermer"
        self.push_screen(Choose(f"{verb} #{n} sur GitHub ?", [f"Oui, {verb.lower()}", "Non"]),
                         lambda r: r and r.startswith("Oui") and self.toggle_issue(n, st == "closed"))

    @work(thread=True)
    def toggle_issue(self, n: str, reopen: bool) -> None:
        try:
            (self.gh.reopen if reopen else self.gh.close)(n)
            self.call_from_thread(self.notify, f"#{n} {'rouverte' if reopen else 'fermée'}")
        except Exception as err:
            self.call_from_thread(self.notify, f"#{n} : {err}", severity="error")
        self.call_from_thread(self.rebuild)

    def action_search(self) -> None:
        def done(text):
            if text is not None:
                self.query_text = text.strip()
                self.rebuild()
        self.push_screen(Ask("Chercher", self.query_text, "mots…"), done)

    def action_cycle_tag(self) -> None:
        """t: a menu of the tags, grouped (milestones, kind, themes), most used first."""
        def done(t):
            if t is None:
                return
            self.tag = t or None
            self.rebuild()
        self.push_screen(TagPicker(self.board.tag_counts(), self.tag, self.tag_info()), done)

    def action_cycle_section(self) -> None:
        ss = [None] + self.board.work_sections
        self.section = ss[(ss.index(self.section) + 1) % len(ss)] if self.section in ss else None
        self.rebuild()

    def action_toggle_done(self) -> None:
        self.hide_done = not self.hide_done
        if self.hide_done and self.focused_col() == "done":
            self.query_one("#list-doing", OptionList).focus()
        self.rebuild()

    def action_toggle_wrap(self) -> None:
        self.wrap = not self.wrap
        self.rebuild()

    def action_clear_filters(self) -> None:
        self.query_text, self.tag, self.section, self.hide_done = "", None, None, False
        self.rebuild()

    def action_refresh_gh(self) -> None:
        self.notify("GitHub…", timeout=1)
        self.load_issues()

    def action_reload(self) -> None:
        if self.test_view:
            self.run_tests()
        else:
            self.reload(quiet=False)

    # ── Gantt view (gantt.py): the same file, who works when ──
    VIEW_KEYS = {"toggle_gantt", "toggle_tests", "quit", "help", "toggle_mode", "reload", "command_palette"}

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """In the Gantt and test views the cards are hidden: no key acts on them."""
        return action in self.VIEW_KEYS if (self.gantt_by or self.test_view) else True

    def action_toggle_gantt(self) -> None:
        """G: board → Gantt by agent → Gantt by task → board."""
        self.gantt_by = {None: "agent", "agent": "task"}.get(self.gantt_by)
        if self.test_view:
            self.gantt_by, self.test_view = "agent", False
            self.screen.set_class(False, "tests-view")
        self.screen.set_class(bool(self.gantt_by), "gantt-view")
        if not self.gantt_by:
            self.query_one(f"#list-{self.focused_col()}", OptionList).focus()
        self.refresh_bindings()
        self.draw_gantt()

    def draw_gantt(self) -> None:
        if not self.gantt_by:
            return
        w = self.query_one("#gantt", Static)
        plan = gt.parse(self.board.read_lines())
        if not plan.tasks:
            w.update(Text("Aucune carte avec une note « gantt: a-b » (voir gantt.py).\nG : retour au tableau.", style=MUTED))
            return
        width = max((w.size.width or self.size.width) - 2, 40)
        w.update(Text.from_ansi("\n".join(gt.render(plan, width, by=self.gantt_by))))

    # ── Test view (junit.py): the JUnit bar, green or red ──
    def action_toggle_tests(self) -> None:
        """U: the test view and back. The first time, the tests run."""
        self.test_view = not self.test_view
        if self.test_view and self.gantt_by:
            self.gantt_by = None
            self.screen.set_class(False, "gantt-view")
        self.screen.set_class(self.test_view, "tests-view")
        if self.test_view:
            self.query_one("#tests-list", OptionList).focus()
            if self.tests is None and not self.tests_running:
                self.run_tests()
        else:
            self.query_one(f"#list-{self.focused_col()}", OptionList).focus()
        self.refresh_bindings()
        self.draw_tests()

    @work(thread=True, exclusive=True, group="tests")
    def run_tests(self) -> None:
        self.tests_running = True
        self.call_from_thread(self.draw_tests)
        res = junit.run(junit.project_root(self.board.path))
        self.tests, self.tests_running = res, False
        self.call_from_thread(self.draw_tests)

    def test_head(self, width: int) -> Text:
        res = self.tests
        t = Text()
        if self.tests_running or res is None:
            t.append(f"{os.path.basename(junit.project_root(self.board.path))} · tests en cours…\n", style="bold")
            t.append("█" * min(width, 40) + "\n", style="yellow")
            return t.append(" ", style=MUTED)
        t.append(res.command + "\n", style="bold")
        t.append("█" * junit.bar_width(res, width) + "\n", style="green" if res.ok else "red")
        t.append(junit.summary(res))
        if res.problem:
            t.append("\n" + res.problem, style="red")
        return t

    def draw_tests(self) -> None:
        if not self.test_view:
            return
        head = self.query_one("#tests-head", Static)
        width = max((head.size.width or self.size.width - 2), 20)
        head.update(self.test_head(width))
        ol = self.query_one("#tests-list", OptionList)
        ol.clear_options()
        res = self.tests
        if res is None or self.tests_running:
            self.query_one("#tests-trace", Static).update("")
            return
        # failures first (the JUnit "Failures" tab), then the others, quieter
        order = res.failures + [c for c in res.cases if not c.bad]
        self.shown_tests = order
        for c in order:
            sign, style = {"failure": ("✗", "red"), "error": ("!", "red"), "skipped": ("–", "yellow")}.get(c.status, ("✓", "green"))
            line = Text.assemble((f"{sign} ", style), (c.title, "" if c.bad else MUTED), (f"  {c.time:.2f}s", MUTED))
            ol.add_option(Option(line))
        if not order and res.output:
            self.query_one("#tests-trace", Static).update(Text(res.output[-3000:], style=MUTED))
        elif order:
            ol.highlighted = 0
            self.show_trace(0)

    def show_trace(self, i: int | None) -> None:
        tests = getattr(self, "shown_tests", [])
        w = self.query_one("#tests-trace", Static)
        if i is None or i >= len(tests):
            w.update("")
            return
        c = tests[i]
        if not c.bad and c.status != "skipped":
            w.update(Text(f"{c.title} · ok", style=MUTED))
            return
        t = Text()
        t.append((c.message or c.status) + "\n", style="bold red" if c.bad else "yellow")
        root = junit.project_root(self.board.path)
        detail = c.detail
        for r in {root, os.path.realpath(root)}:   # paths relative to the project
            detail = detail.replace(r + os.sep, "")
        t.append(detail, style=MUTED)
        w.update(t)

    @on(OptionList.OptionHighlighted, "#tests-list")
    def _test_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.show_trace(event.option_index)

    def action_help(self) -> None:
        self.push_screen(Detail(Text.from_markup(HELP)))

    def action_detail(self) -> None:
        c = self.current()
        if not c:
            return
        t = Text()
        t.append(f"{COL_NAMES[c.col]} · {c.section}", style=f"bold {self.section_color(c.section)}")
        if c.group:
            t.append(f" › {c.group}", style=MUTED)
        t.append(f"   ligne {c.line + 1}\n\n", style=MUTED)
        t.append(c.text + "\n")
        info = self.tag_info()
        for tg in c.tags + ([c.custom_mark] if c.custom_mark and c.custom_mark not in c.tags else []):
            t.append(f"@{tg}", style=f"bold {tag_color(tg)}")
            t.append(f"  {info[tg]}\n" if tg in info else "\n", style=MUTED)
        if c.notes:
            t.append("\n")
            for n in c.notes:
                t.append(f"  • {n}\n", style=MUTED)
        for n in c.issues:
            i = self.gh.issues.get(n) or {}
            st = self.gh.state(n)
            t.append(f"\n#{n} ", style="green" if st == "closed" else "cyan")
            t.append(f"{i.get('title', '')}  ", style="")
            t.append(f"{st or '?'} · {self.gh.milestone(n) or 'sans milestone'}", style=MUTED)
        self.push_screen(Detail(t))


def find_file(start: str) -> str | None:
    for name in ("idee.md", "idées.md", "ideas.md", "TODO.md", "todo.md", "KANBAN.md", "kanban.md"):
        p = os.path.join(start, name)
        if os.path.exists(p):
            return p
    return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kanban", description="Un fichier Markdown d'idées en Kanban interactif dans le terminal.")
    ap.add_argument("file", nargs="?", help="fichier Markdown, ou dossier où le chercher (par défaut : idee.md, ideas.md, TODO.md… du dossier courant)")
    ap.add_argument("--repo", help="dépôt GitHub propriétaire/nom (par défaut : celui du git du fichier)")
    ap.add_argument("--theme", choices=["auto", "light", "dark"], default=os.environ.get("KANBAN_THEME", "auto"),
                    help="clair, sombre, ou auto : comme le terminal / VS Code / le système (par défaut)")
    a = ap.parse_args(argv)
    path = os.path.expanduser(a.file) if a.file else os.getcwd()
    if os.path.isdir(path):  # kanban ~/Documents/projet : its idee.md, TODO.md…
        path = find_file(path)
    if not path or not os.path.exists(path):
        sys.exit("kanban : aucun fichier trouvé (idee.md, ideas.md, TODO.md…). Donne son chemin : kanban chemin/vers/idees.md ou kanban chemin/vers/dossier")
    auto = a.theme == "auto"
    mode = th.detect() if auto else a.theme
    KanbanApp(path, a.repo, mode, follow=auto).run()


if __name__ == "__main__":
    main()
