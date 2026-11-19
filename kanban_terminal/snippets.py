"""
kanban-snippets — the tags of the idea file, offered as you type in VS Code.

The tags and their descriptions are read where the board reads them, the
Rules section (one line per tag), and also from a « ## Tags » table:

    ## Règles                       ## Tags
    - @v1: version 1                | tag | description |
    - @idée: pas encore triée       |---|---|
                                    | @v1 | version 1 |

It writes .vscode/markdown.code-snippets next to the file: typing « @v » (or
« v1 ») in a Markdown file then offers @v1 with its description. It also lists
the tags used on cards but described nowhere.

    kanban-snippets [fichier.md | dossier]

In VS Code, a task makes it one keystroke away (F1 → « Tasks: Run Task »), and
« runOn: folderOpen » refreshes the snippets each time the folder opens:

    { "label": "Tags → snippets", "type": "shell", "command": "kanban-snippets",
      "problemMatcher": [], "runOptions": { "runOn": "folderOpen" } }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from .model import TAG, tag_descriptions

ROW = re.compile(r"^\|\s*@([\w-]+)\s*\|\s*(.*?)\s*\|\s*$")   # « | @v1 | version 1 | »
NAMES = ("idee.md", "idées.md", "ideas.md", "TODO.md", "todo.md", "KANBAN.md", "kanban.md")


def table_tags(lines: list[str]) -> dict[str, str]:
    """{tag: description} from the table of a « ## Tags » section."""
    info, inside = {}, False
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip().lower() == "tags"
        elif inside and (m := ROW.match(line.strip())):
            info[m.group(1)] = m.group(2)
    return info


def all_tags(lines: list[str]) -> dict[str, str]:
    """Rules lines first, then the Tags table (which wins when both describe a tag)."""
    return {**tag_descriptions(lines), **table_tags(lines)}


def snippets(tags: dict[str, str]) -> dict:
    return {f"@{t}": {"scope": "markdown", "prefix": [f"@{t}", t], "body": f"@{t}$0", "description": d}
            for t, d in tags.items()}


def undescribed(lines: list[str], tags: dict[str, str]) -> list[str]:
    """Tags written in the file but described nowhere."""
    text = "\n".join(l for l in lines if not ROW.match(l.strip()))
    return sorted(set(TAG.findall(text)) - set(tags))


def write(path: str) -> tuple[str, dict[str, str], list[str]]:
    lines = open(path, encoding="utf-8").read().splitlines()
    tags = all_tags(lines)
    out = os.path.join(os.path.dirname(os.path.abspath(path)), ".vscode", "markdown.code-snippets")
    if tags:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"// written by kanban-snippets from the tags of {os.path.basename(path)}"
                    " — edit the file, not this one\n")
            json.dump(snippets(tags), f, ensure_ascii=False, indent=2)
    return out, tags, undescribed(lines, tags)


def find(path: str) -> str | None:
    if os.path.isfile(path):
        return path
    for name in NAMES:
        if os.path.isfile(p := os.path.join(path, name)):
            return p
    return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kanban-snippets",
                                 description="Les tags du fichier d'idées → snippets Markdown de VS Code.")
    ap.add_argument("file", nargs="?", default=".", help="fichier Markdown, ou dossier où le chercher (défaut : ici)")
    a = ap.parse_args(argv)
    path = find(a.file)
    if not path:
        sys.exit("kanban-snippets : aucun fichier trouvé (idee.md, ideas.md, TODO.md…)")
    out, tags, missing = write(path)
    if not tags:
        sys.exit(f"kanban-snippets : aucun tag décrit dans {path} (« - @tag: description » sous Règles, ou un tableau sous « ## Tags »)")
    print(f"{len(tags)} tags → {os.path.relpath(out)}")
    if missing:
        print("sans description : " + " ".join("@" + t for t in missing))


if __name__ == "__main__":
    main()
