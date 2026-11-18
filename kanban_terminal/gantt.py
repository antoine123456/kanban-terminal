"""The same Markdown file as a Gantt chart: who works when, and where we are.

On top of the kanban format (see model.py), a few lines:

    ## Rules
    - agents: lead, scan, you      the lanes, in this order (else: every tag)
    - unit: 5 min                  what one slot is worth
    - start: 2026-11-18 15:00      when the work started (optional, see below)
    ## Some section
    - [ ] a task @volet1 @lead     @volet… = phase (colour), agent tag = lane
      - gantt: 2-5                 slots 2 to 5

      - at: 60%                    optional marker: how far the card in progress is

Cards without a ``gantt:`` note are not drawn. Three shades of the phase's
colour: █ done, ▒ in progress, ░ to do (a card in progress is █ up to its
``at:`` marker).

The red line ┃ is the progress, and only markers move it: a card ticked
[_] or [x], an ``at:`` note changed. It stands where the first unfinished
card is: at its start, or at its ``at:`` marker. Everything left of it is
done. With ``start:``, a grey line ┊ is the clock, and the header says how
far ahead or behind the work is.

Used by the kanban (key G) and by the ``gantt`` command (``--play`` replays
the plan: the line sweeps the timeline and fills the bars).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

ITEM = re.compile(r"^- (?:\[(?P<mark>[^\]]{1,12})\]\s*)?(?P<body>.*)$")
TAG = re.compile(r"(?<!\S)@([\w-]+)")
SLOT = re.compile(r"gantt:\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)")
PHASE = re.compile(r"(?:volet|v|phase)(\d+)$", re.I)
UNIT = re.compile(r"unit:\s*(\d+(?:\.\d+)?)\s*(\w+)")
AGENTS = re.compile(r"agents:\s*(.+)$")
START = re.compile(r"start:\s*(\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2})")
RULES = {"rules", "règles", "regles"}
TAG_INFO = re.compile(r"^- @([\w-]+)\s*(?::|—|=)\s*(.+)$")

# 16-colour palette: reads on light and dark terminals alike, and in Textual.
PHASE_COLORS = ["34", "32", "35", "36", "33", "31"]   # blue green magenta cyan yellow red
CURSOR = "1;31"
CLOCK = "90"           # the terminal's grey
AT = re.compile(r"(?:at|progress):\s*(\d+(?:\.\d+)?)\s*%")
HUMAN = {"you", "moi", "toi", "me", "human"}


@dataclass
class Task:
    text: str
    section: str
    lane: str
    phase: int
    start: float
    end: float
    status: str  # todo · doing · done
    at: float = 0.0  # 0..1, the « at: 60% » marker of a card in progress

    def reached(self) -> float:
        """How far this card has gone, in slots."""
        if self.status == "done":
            return self.end
        return self.start + self.at * (self.end - self.start)


@dataclass
class Plan:
    title: str
    lanes: list[str]
    tasks: list[Task]
    unit: tuple[float, str] | None
    started: datetime | None = None
    tag_info: dict[str, str] = field(default_factory=dict)   # « - @v1: first release » in Rules

    @property
    def end(self) -> float:
        return max((t.end for t in self.tasks), default=0)

    def progress(self) -> float:
        """Up to where the plan is done: the first unfinished card, at its
        start or at its « at: » marker. Moves only when the file changes."""
        return min((t.reached() for t in self.tasks if t.status != "done"), default=self.end)

    def clock(self, now: datetime | None = None) -> float | None:
        """Slots elapsed since ``start:``, if the unit is a duration."""
        if not self.started or not self.unit:
            return None
        minutes = {"m": 1, "h": 60, "d": 1440, "j": 1440}.get(self.unit[1][0].lower())
        if not minutes:
            return None
        elapsed = ((now or datetime.now()) - self.started).total_seconds() / 60
        return elapsed / (self.unit[0] * minutes)


def parse(lines: list[str]) -> Plan:
    title, section, unit, started = "", "", None, None
    info: dict[str, str] = {}
    lanes: list[str] = []
    cards: list[tuple[str, str, str, list[str], list[str]]] = []  # mark, text, section, tags, notes
    for line in lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            section = line[3:].strip()
        elif section.lower() in RULES:
            if m := AGENTS.search(line):
                lanes = [a.strip().lstrip("@") for a in m.group(1).split(",") if a.strip()]
            if m := UNIT.search(line):
                unit = (float(m.group(1)), m.group(2))
            if m := START.search(line):
                started = datetime.fromisoformat(m.group(1).replace(" ", "T"))
            if m := TAG_INFO.match(line.strip()):
                info[m.group(1)] = m.group(2).strip()
        elif (m := ITEM.match(line)):
            body = m.group("body")
            cards.append((m.group("mark") or "", TAG.sub("", body).strip(), section, TAG.findall(body), []))
        elif line.startswith((" ", "\t")) and cards and line.strip():
            cards[-1][4].append(line.strip())

    tasks = []
    for mark, text, sec, tags, notes in cards:
        slot = next((m for n in notes if (m := SLOT.search(n))), None)
        if not slot:
            continue
        phase = next((int(PHASE.match(t).group(1)) for t in tags if PHASE.match(t)), 0)
        others = [t for t in tags if not PHASE.match(t)]
        lane = next((t for t in others if t in lanes), others[0] if others else "?")
        status = {"x": "done", "X": "done", "_": "doing"}.get(mark, "todo")
        at = next((min(float(m.group(1)), 100) / 100 for n in notes if (m := AT.search(n))), 0.0)
        tasks.append(Task(text, sec, lane, phase, float(slot.group(1)), float(slot.group(2)), status,
                          at if status == "doing" else 0.0))
    used = [l for l in lanes if any(t.lane == l for t in tasks)]
    used += [t.lane for t in tasks if t.lane not in used]
    return Plan(title, list(dict.fromkeys(used)), tasks, unit, started, info)


def load(path: str) -> Plan:
    with open(path, encoding="utf-8") as f:
        return parse(f.read().split("\n"))


# ── drawing: rows of (char, SGR code) cells, then ANSI ──
Cell = tuple[str, str]


def ansi(cells: list[Cell], color: bool = True) -> str:
    if not color:
        return "".join(c for c, _ in cells)
    out, cur, run = [], None, []
    for ch, code in cells + [("", "\0")]:
        if code != cur:
            if run:
                out.append(f"\x1b[{cur}m{''.join(run)}\x1b[0m" if cur else "".join(run))
            cur, run = code, []
        run.append(ch)
    return "".join(out)


def text(s: str, code: str = "") -> list[Cell]:
    return [(c, code) for c in s]


def short(text_: str) -> str:
    """The card's text up to its first « : » or « ( » (the rest is detail)."""
    return re.split(r":\s|\s\(", text_, maxsplit=1)[0].strip()


def fit(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(n - 1, 0)] + "…"


def phase_color(task: Task) -> str:
    if task.lane in HUMAN:
        return "1"
    return PHASE_COLORS[(task.phase - 1) % len(PHASE_COLORS)] if task.phase else ""


def bar(task: Task, width: int, sim: float | None) -> list[Cell]:
    """One bar, no text: █ done, ▒ in progress, ░ to do, in the phase's colour.
    ``sim``: replay time (--play), the bar fills up to it."""
    col = phase_color(task)
    reached = task.reached() if sim is None else sim
    live = task.status == "doing" if sim is None else task.start <= sim < task.end
    cells = []
    for i in range(width):
        t = task.start + (i + 0.5) / width * (task.end - task.start)
        cells.append(("█" if t <= reached else "▒" if live else "░", col))
    if task.lane in HUMAN:
        cells[0] = ("◆", col)                   # your review
    return cells


def fmt_time(slots: float, unit: tuple[float, str] | None) -> str:
    if not unit:
        return f"{slots:g}"
    v, u = slots * unit[0], unit[1]
    if u.startswith("min") and abs(v) >= 60:
        h, m = divmod(int(round(abs(v))), 60)
        return ("-" if v < 0 else "") + (f"{h}h{m:02d}" if m else f"{h}h")
    return f"{round(v):g}{u[0]}"


def render(plan: Plan, cols: int, *, by: str = "agent", sim: float | None = None,
           cursor: float | None = None, color: bool = True, now: datetime | None = None) -> list[str]:
    """The chart as ANSI lines of at most ``cols`` cells.

    sim     replay time: bars fill up to it, the line follows it (--play)
    cursor  where to draw the red line; by default the clock (``start:``) or
            the plan's progress
    """
    end = max(plan.end, 1)
    clock = plan.clock(now) if sim is None else None
    progress = plan.progress()
    if cursor is None:
        cursor = sim if sim is not None else progress
    label_w = min(14, max([len(l) for l in plan.lanes] + [len("parallel")]) + 2) if by == "agent" else min(34, cols // 3)
    span = max(cols - label_w - 8, 10)       # 8: room for " max N" after the load row
    scale = span / end                         # cells per slot

    def x(t: float) -> int:
        return round(t * scale)

    def col_of(t: float | None) -> int | None:
        return None if t is None else min(x(min(max(t, 0), end)), span - 1)

    cur, clk = col_of(cursor), col_of(clock)
    if clk == cur:
        clk = None
    lines: list[list[Cell]] = []

    # header: where we are
    head = text(fit(plan.title or "Gantt", cols), "1")
    if sim is not None:
        active = {t.lane for t in plan.tasks if t.start <= sim < t.end}
        info = f"   t={fmt_time(sim, plan.unit)}   {len(active - HUMAN)} agent(s) at work" + (
            "  · waiting for you" if active & HUMAN else "")
        head += text(info)
    else:
        done = sum(t.status == "done" for t in plan.tasks)
        info = f"   {done}/{len(plan.tasks)} done · "
        head += text(info) + text(f"┃ {fmt_time(progress, plan.unit)}", CURSOR)
        if clock is not None:
            gap = progress - clock
            if progress >= plan.end:
                head += text(" · finished", "32")
            elif abs(gap) * (plan.unit[0] if plan.unit else 1) < 1:
                head += text(" · on time", "32")
            else:
                word = "ahead" if gap > 0 else "late"
                head += text(f" · ┊ clock {fmt_time(min(clock, 10 * end), plan.unit)}", CLOCK)
                head += text(f" → {fmt_time(abs(gap), plan.unit)} {word}", "32" if gap > 0 else CURSOR)
    lines.append(head[:cols])

    # axis: a tick every few slots so labels do not overlap; ▼ over the line
    step = next(s for s in (1, 2, 3, 4, 5, 10, 20, 50, 100) if s * scale >= 6 or s == 100)
    axis = [(" ", "")] * (span + 1)
    for s in range(0, int(end) + 1, step):
        lab = fmt_time(s, plan.unit)
        p = x(s)
        if p + len(lab) <= span + 1:
            axis[p:p + len(lab)] = text(lab, "90")
    if clk is not None and axis[clk][0] == " ":     # never over a time label
        axis[clk] = ("▿", CLOCK)
    if cur is not None and axis[cur][0] == " ":
        axis[cur] = ("▼", CURSOR)
    lines.append(text(" " * label_w) + axis)

    if by == "agent":
        rows = [(l, sorted((t for t in plan.tasks if t.lane == l), key=lambda t: t.start)) for l in plan.lanes]
    else:
        rows = [(short(t.text), [t]) for t in sorted(plan.tasks, key=lambda t: (t.start, t.end))]

    def with_cursor(cells: list[Cell]) -> list[Cell]:
        if clk is not None and clk < len(cells) and cells[clk][0] == " ":   # the clock: only in gaps
            cells[clk] = ("┊", CLOCK)
        if cur is not None and cur < len(cells):
            cells[cur] = ("┃", CURSOR)
        return cells

    for name, tasks in rows:
        cells: list[Cell] = [(" ", "")] * span
        for t in tasks:
            a = min(x(t.start), span - 1)
            b = min(max(x(t.end), a + 1), span)
            cells[a:b] = bar(t, b - a, sim)
        label = text(fit(name, label_w - 1).ljust(label_w), "1" if name in HUMAN else "")
        lines.append(label + with_cursor(cells))

    # load row: how many agents work in each column
    load: list[Cell] = []
    for i in range(span):
        t = (i + 0.5) / scale
        n = len({k.lane for k in plan.tasks if k.start <= t < k.end and k.lane not in HUMAN})
        load.append((" ▁▂▃▄▅▆▇█"[min(n * 2, 8)] if n else " ", "36"))
    peak = max((len({k.lane for k in plan.tasks if k.start <= s + .5 < k.end} - HUMAN) for s in range(int(end))), default=0)
    lines.append(text("parallel".ljust(label_w), "90") + with_cursor(load) + text(f" max {peak}", "90"))

    # legend, wrapped to the width
    # a phase is named by its tag's description (« - @v1: first release »), else its first card's section
    names: dict[int, str] = {}
    for t in plan.tasks:
        names.setdefault(t.phase, t.section)
    for tag, desc in plan.tag_info.items():
        if (m := PHASE.fullmatch(tag)) and int(m.group(1)) in names:
            names[int(m.group(1))] = desc
    lines.append([])
    row: list[Cell] = []
    for p in sorted(n for n in names if n):
        item = text("■ ", PHASE_COLORS[(p - 1) % len(PHASE_COLORS)]) + text(fit(names[p], 18))
        if row and len(row) + 2 + len(item) > cols:
            lines.append(row)
            row = []
        row += (text("  ") if row else []) + item
    lines.append(row)
    total = fmt_time(end, plan.unit)
    work = sum(t.end - t.start for t in plan.tasks if t.lane not in HUMAN)
    # the key: the glyphs in the normal colour (their shades must show), the words grey
    keys = (text("█", "") + text(" done  ", "90") + text("▒", "") + text(" in progress  ", "90")
            + text("░", "") + text(" to do  ", "90") + text("◆", "") + text(" your review  ", "90")
            + text("┃", CURSOR) + text(" progress", "90")
            + ((text("  ┊", CLOCK) + text(" clock", "90")) if plan.started else []))
    times = text(f"wall clock {total}, agent work {fmt_time(work, plan.unit)}", "90")
    if len(keys) + len(times) + 3 <= cols:
        lines.append(keys + text(" · ", "90") + times)
    else:
        lines += [keys[:cols], times[:cols]]
    return [ansi(l, color) for l in lines]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="gantt", description="Le Gantt d'un fichier kanban-terminal, dans le terminal.")
    ap.add_argument("file", help="fichier Markdown (format kanban + notes « gantt: a-b »)")
    ap.add_argument("--by", choices=["agent", "task"], default="agent", help="une ligne par agent (défaut) ou par tâche")
    ap.add_argument("--play", action="store_true", help="rejoue le plan : la ligne avance, les barres se remplissent")
    ap.add_argument("--watch", action="store_true", help="reste ouvert : suit le fichier et l'horloge (ligne rouge)")
    ap.add_argument("--speed", type=float, default=0.5, help="secondes par créneau en --play (défaut 0.5)")
    ap.add_argument("--width", type=int, help="largeur (défaut : celle du terminal)")
    a = ap.parse_args(argv)

    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def width() -> int:
        return a.width or shutil.get_terminal_size((100, 24)).columns

    plan = load(a.file)
    if not plan.tasks:
        sys.exit("Aucune carte avec une note « gantt: a-b ».")
    if not (a.play or a.watch):
        print("\n".join(render(plan, width(), by=a.by, color=color)))
        return

    def show(lines: list[str]) -> None:
        sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(lines) + "\n")
        sys.stdout.flush()

    try:
        sys.stdout.write("\x1b[?25l")
        if a.play:
            t, step = 0.0, 0.25
            while t <= plan.end + step:
                show(render(plan, width(), by=a.by, sim=min(t, plan.end), color=color))
                time.sleep(a.speed * step)
                t += step
        else:
            mtime = None
            while True:
                m = os.path.getmtime(a.file)
                if m != mtime:
                    plan, mtime = load(a.file), m
                show(render(plan, width(), by=a.by, color=color))
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?25h")


if __name__ == "__main__":
    main()
