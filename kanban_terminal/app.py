"""kanban-terminal: a Markdown idea list as an interactive Kanban board in the
terminal — small enough for VS Code's bottom panel."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import webbrowser

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .gh import GitHub, milestone_tag, tag_milestone
from .model import COLUMNS, Board, Card, is_inbox

COL_NAMES = dict(COLUMNS)
SECTION_COLORS = ["#4f8ff7", "#f25f5c", "#b48ead", "#56b6c2", "#e5c07b"]
INBOX_COLOR = "#d7a700"


# ── Small dialogs ──
class Ask(ModalScreen[str | None]):
    """One line of text (add, edit, search)."""
    BINDINGS = [Binding("escape", "cancel", "Annuler")]

    def __init__(self, title: str, value: str = "", placeholder: str = ""):
        super().__init__()
        self.title_, self.value, self.placeholder = title, value, placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_, classes="dlg-title")
            yield Input(value=self.value, placeholder=self.placeholder)
            yield Label("Entrée pour valider · Échap pour annuler", classes="dlg-hint")

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


HELP = """[b]Se déplacer[/b]  ←→ colonne · ↑↓ carte · Entrée détail · clic souris
[b]Déplacer la carte[/b]  ⇧← ⇧→ (ou < >) · 1 À trier · 2 À faire · 3 En cours · 4 Fait
[b]Écrire[/b]  a ajouter (dans À trier) · e modifier le texte · E ouvrir dans l'éditeur à la ligne
[b]GitHub[/b]  o ouvrir l'issue · i créer l'issue de la carte · c fermer / rouvrir l'issue · g actualiser
[b]Filtres[/b]  / chercher · t tag (@v1…) · s section · f cacher « Fait » · w texte complet · Échap tout effacer
[b]Fichier[/b]  rechargé tout seul quand il change · r recharger · q quitter"""


class KanbanApp(App):
    TITLE = "kanban"
    CSS = """
    Screen { layout: vertical; }
    #bar { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    #board { height: 1fr; }
    .col { width: 1fr; height: 1fr; border: round $panel-lighten-2; padding: 0; }
    .col:focus-within { border: round $accent; }
    .col.hidden { display: none; }
    .col-title { height: 1; padding: 0 1; text-style: bold; color: $text-muted; }
    .col OptionList { height: 1fr; border: none; padding: 0; background: transparent; scrollbar-size-vertical: 1; }
    .col OptionList:focus { border: none; }
    #detail { height: auto; max-height: 3; padding: 0 1; color: $text; background: $boost; }
    ModalScreen { align: center middle; }
    .dialog { width: 70%; max-width: 100; height: auto; max-height: 90%; border: round $accent; background: $surface; padding: 0 1; }
    .dialog.wide { width: 90%; max-width: 140; }
    .dialog OptionList { height: auto; max-height: 12; border: none; }
    .dlg-title { text-style: bold; padding: 0 0 1 0; }
    .dlg-hint { color: $text-muted; }
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
        Binding("g", "refresh_gh", show=False), Binding("r", "reload", show=False),
        Binding("question_mark", "help", "aide"), Binding("q", "quit", "quitter"),
    ]

    def __init__(self, path: str, repo: str | None = None):
        super().__init__()
        self.board = Board(path)
        self.gh = GitHub(os.path.dirname(self.board.path), repo)
        self.query_text = ""
        self.tag: str | None = None
        self.section: str | None = None
        self.hide_done = False
        self.wrap = False
        self.shown: dict[str, list[Card]] = {}

    # ── layout ──
    def compose(self) -> ComposeResult:
        yield Static(id="bar")
        with Horizontal(id="board"):
            for key, name in COLUMNS:
                with Vertical(classes="col", id=f"col-{key}"):
                    yield Label(name, classes="col-title", id=f"title-{key}")
                    yield OptionList(id=f"list-{key}")
        yield Static(id="detail")
        yield Footer()

    def on_resize(self) -> None:
        self.call_after_refresh(self.rebuild)

    def on_mount(self) -> None:
        self.rebuild()
        self.call_after_refresh(self.rebuild)
        self.query_one("#list-todo", OptionList).focus()
        self.set_interval(1.0, self.watch_file)
        self.load_issues()

    # ── data → screen ──
    def section_color(self, section: str) -> str:
        if is_inbox(section):
            return INBOX_COLOR
        ws = self.board.work_sections
        return SECTION_COLORS[ws.index(section) % len(SECTION_COLORS)] if section in ws else "#888888"

    def visible(self, c: Card) -> bool:
        if self.tag and self.tag not in c.tags:
            return False
        if self.section and c.section != self.section and not is_inbox(c.section):
            return False
        if self.query_text:
            hay = (c.text + " " + " ".join(c.notes) + " " + " ".join(c.tags) + " " + (c.group or "")).lower()
            return all(w in hay for w in self.query_text.lower().split())
        return True

    def card_text(self, c: Card, width: int = 0) -> Text:
        head = Text()
        head.append("▌", style=self.section_color(c.section))
        if c.custom_mark:
            head.append(f"{c.custom_mark} ", style=f"bold {INBOX_COLOR}")
        body = Text(re.sub(r"\s*\(#\d+\)", "", c.text), style="dim" if c.col == "done" else "")  # the issue is a chip
        tail = Text()
        for n in c.issues:
            st = self.gh.state(n)
            tail.append(f" #{n}{'✓' if st == 'closed' else ''}", style="green" if st == "closed" else "cyan")
        for tg in c.tags:
            tail.append(f" @{tg}", style="magenta")
        if c.notes:
            tail.append(f" +{len(c.notes)}", style="dim")
        # One line per card by default (a short bottom panel shows more), w
        # unfolds; the text is cut, never the issue / tag chips.
        if not self.wrap and width > 4:
            room = width - head.cell_len - tail.cell_len
            if room < 8:
                tail = Text()
                room = width - head.cell_len
            if body.cell_len > room:
                body.truncate(max(1, room - 1))
                body.append("…", style="dim")
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
            d.update(Text("—", style="dim"))
            return
        t = Text()
        t.append(f"{c.section}", style=f"bold {self.section_color(c.section)}")
        if c.group:
            t.append(f" › {c.group}", style="dim")
        t.append(f"  l.{c.line + 1}  ", style="dim")
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
        self.push_screen(Ask("Nouvelle idée (dans « À trier »)", placeholder="texte… (#12 pour une issue, @v1 pour un tag)"), done)

    def action_edit(self) -> None:
        c = self.current()
        if not c:
            return
        full = c.text + "".join(f" @{t}" for t in c.tags)

        def done(text):
            if text and text.strip() and text.strip() != full:
                if self.guard(self.board.set_text, c, text):
                    self.rebuild()
        self.push_screen(Ask("Modifier la carte", full), done)

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
        ms = next((tag_milestone(t, self.gh.milestones) for t in c.tags if tag_milestone(t, self.gh.milestones)), None)
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
        tags = [None] + self.board.tags()
        self.tag = tags[(tags.index(self.tag) + 1) % len(tags)] if self.tag in tags else None
        self.rebuild()

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
        self.reload(quiet=False)

    def action_help(self) -> None:
        self.push_screen(Detail(Text.from_markup(HELP)))

    def action_detail(self) -> None:
        c = self.current()
        if not c:
            return
        t = Text()
        t.append(f"{COL_NAMES[c.col]} · {c.section}", style=f"bold {self.section_color(c.section)}")
        if c.group:
            t.append(f" › {c.group}", style="dim")
        t.append(f"   ligne {c.line + 1}\n\n", style="dim")
        t.append(c.text + "\n")
        for tg in c.tags:
            t.append(f"@{tg} ", style="magenta")
        if c.notes:
            t.append("\n")
            for n in c.notes:
                t.append(f"  • {n}\n", style="dim")
        for n in c.issues:
            i = self.gh.issues.get(n) or {}
            st = self.gh.state(n)
            t.append(f"\n#{n} ", style="green" if st == "closed" else "cyan")
            t.append(f"{i.get('title', '')}  ", style="")
            t.append(f"{st or '?'} · {self.gh.milestone(n) or 'sans milestone'}", style="dim")
        self.push_screen(Detail(t))


def find_file(start: str) -> str | None:
    for name in ("idee.md", "idées.md", "ideas.md", "TODO.md", "todo.md", "KANBAN.md", "kanban.md"):
        p = os.path.join(start, name)
        if os.path.exists(p):
            return p
    return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kanban", description="Un fichier Markdown d'idées en Kanban interactif dans le terminal.")
    ap.add_argument("file", nargs="?", help="fichier Markdown (par défaut : idee.md, ideas.md, TODO.md… du dossier courant)")
    ap.add_argument("--repo", help="dépôt GitHub propriétaire/nom (par défaut : celui du git du fichier)")
    a = ap.parse_args(argv)
    path = a.file or find_file(os.getcwd())
    if not path or not os.path.exists(path):
        sys.exit("kanban : aucun fichier trouvé (idee.md, ideas.md, TODO.md…). Donne son chemin : kanban chemin/vers/idees.md")
    KanbanApp(path, a.repo).run()


if __name__ == "__main__":
    main()
