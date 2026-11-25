"""
kanban-tidy — tidies the idea file each time it is saved, no AI involved.

  * Pending: each item becomes a card for the board (« - ») and gets a number,
    in file order — « - P1 @ankiterm … », « - P2 … » (P, not #: #12 is an issue).
    A « - » line is an item (a card on the board, as always); so is a line
    starting with « @ » or a number already given, after a blank line (or the
    heading). Anything else (a pasted log, an answer « → … ») stays part of
    the item above.
  * Tags: a tag used in Pending but described nowhere gets a row in the
    « ## Tags » table, « à décrire », so it can be filled in.
  * Snippets: .vscode/markdown.code-snippets is written again (kanban-snippets).

The file is only written when something changed, and not if it was saved
again meanwhile.

    kanban-tidy [fichier.md | dossier]            once
    kanban-tidy [fichier.md | dossier] --watch    at every save (a VS Code task:
                                                  runOn folderOpen, see README)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

from . import snippets as sn
from .model import TAG

ITEM = re.compile(r"^(?:-\s+)?(?:P\d+\s+)?(?=\S)")          # « - P3 », « - », « P3 », nothing
STARTS = re.compile(r"^(?:-\s|@[\w-]|P\d+\s)")                # what an item starts with
NOT_TAGS = {"this"}                                           # « see @this » = the screenshot


def number_pending(lines: list[str]) -> list[str]:
    out, inside, blank, n = [], False, True, 0
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip().lower() in ("pending", "inbox", "à trier", "a trier")
            out.append(line)
            blank = True
            continue
        # « - » is always a card (as on the board); « @… » / « P3 » after a blank line
        if inside and (line.startswith("- ") or (blank and STARTS.match(line))):
            n += 1
            line = f"- P{n} " + ITEM.sub("", line, count=1)
        out.append(line)
        blank = not line.strip()
    return out


def add_missing_tags(lines: list[str]) -> list[str]:
    tags = sn.all_tags(lines)
    # the tags used in Pending (the Rules' prose mentions « @tag », « @voletN »…)
    pending, inside = [], False
    for l in lines:
        if l.startswith("## "):
            inside = l[3:].strip().lower() in ("pending", "inbox", "à trier", "a trier")
        elif inside:
            pending.append(l)
    used = sorted({t for t in TAG.findall("\n".join(pending)) if t not in tags and t not in NOT_TAGS and not t.isdigit()})
    if not used:
        return lines
    # after the last row of the « ## Tags » table
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].strip().lower() == "tags"), None)
    if start is None:
        return lines
    last = None
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        if lines[i].strip().startswith("|"):
            last = i
    if last is None:
        return lines
    return lines[:last + 1] + [f"| @{t} | à décrire |" for t in used] + lines[last + 1:]


def tidy(path: str) -> bool:
    """True when the file was rewritten."""
    st = os.stat(path)
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    new = "\n".join(add_missing_tags(number_pending(lines)))
    changed = new != text
    if changed and os.stat(path).st_mtime == st.st_mtime:  # not saved again meanwhile
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    sn.write(path)
    return changed


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kanban-tidy", description="Range le fichier d'idées : Pending numéroté, tags manquants, snippets.")
    ap.add_argument("file", nargs="?", default=".", help="fichier Markdown, ou dossier où le chercher (défaut : ici)")
    ap.add_argument("--watch", action="store_true", help="recommencer à chaque enregistrement du fichier")
    a = ap.parse_args(argv)
    path = sn.find(a.file)
    if not path:
        sys.exit("kanban-tidy : aucun fichier trouvé (idee.md, ideas.md, TODO.md…)")
    print(("rangé : " if tidy(path) else "déjà rangé : ") + path, flush=True)
    if not a.watch:
        return
    seen = os.stat(path).st_mtime
    while True:
        time.sleep(0.5)
        try:
            m = os.stat(path).st_mtime
        except FileNotFoundError:
            continue
        if m == seen:
            continue
        time.sleep(0.3)  # let the save finish
        if tidy(path):
            print(time.strftime("%H:%M:%S") + " rangé", flush=True)
        seen = os.stat(path).st_mtime


if __name__ == "__main__":
    main()
