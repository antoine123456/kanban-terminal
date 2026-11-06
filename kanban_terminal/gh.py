"""GitHub issues through the `gh` CLI (optional: without it the board works,
issue numbers are just shown)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess


def _run(args: list[str], cwd: str, timeout: int = 30) -> str:
    out = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout) else "gh a échoué")
    return out.stdout


class GitHub:
    def __init__(self, folder: str, repo: str | None = None):
        self.folder = folder
        self.available = shutil.which("gh") is not None
        self.repo = repo or (self._detect() if self.available else None)
        self.issues: dict[str, dict] = {}
        self.milestones: list[str] = []

    def _detect(self) -> str | None:
        try:
            url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=self.folder,
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            return None
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
        return m.group(1) if m else None

    @property
    def ok(self) -> bool:
        return self.available and bool(self.repo)

    def url(self, number: str) -> str | None:
        return f"https://github.com/{self.repo}/issues/{number}" if self.repo else None

    def refresh(self) -> None:
        if not self.ok:
            return
        data = json.loads(_run(["issue", "list", "--repo", self.repo, "--state", "all", "--limit", "1000",
                                "--json", "number,state,title,milestone,labels"], self.folder))
        self.issues = {str(i["number"]): i for i in data}
        try:
            ms = json.loads(_run(["api", f"repos/{self.repo}/milestones?state=all", "--jq", "[.[].title]"], self.folder))
            self.milestones = ms
        except Exception:
            self.milestones = sorted({(i.get("milestone") or {}).get("title") for i in data} - {None})

    def state(self, number: str) -> str:
        return (self.issues.get(number) or {}).get("state", "").lower()

    def milestone(self, number: str) -> str:
        return ((self.issues.get(number) or {}).get("milestone") or {}).get("title", "")

    def create(self, title: str, milestone: str | None = None, label: str | None = None) -> str:
        args = ["issue", "create", "--repo", self.repo, "--title", title, "--body", "Créée depuis kanban-terminal."]
        if milestone:
            args += ["--milestone", milestone]
        if label:
            args += ["--label", label]
        url = _run(args, self.folder).strip().splitlines()[-1]
        return url.rstrip("/").rsplit("/", 1)[-1]

    def close(self, number: str) -> None:
        _run(["issue", "close", number, "--repo", self.repo], self.folder)
        if number in self.issues:
            self.issues[number]["state"] = "CLOSED"

    def reopen(self, number: str) -> None:
        _run(["issue", "reopen", number, "--repo", self.repo], self.folder)
        if number in self.issues:
            self.issues[number]["state"] = "OPEN"


def milestone_tag(title: str) -> str | None:
    """« v1 — app actuelle » → v1 ; « Plus tard » → plus-tard ; « Volet 2 — … » → volet2."""
    if not title:
        return None
    m = re.match(r"\s*(v\d+)\b", title, re.I)
    if m:
        return m.group(1).lower()
    m = re.match(r"\s*volet\s*(\d+)", title, re.I)
    if m:
        return f"volet{m.group(1)}"
    head = re.split(r"\s+[—–-]\s+", title)[0]
    return re.sub(r"\W+", "-", head.strip().lower()).strip("-") or None


def tag_milestone(tag: str, milestones: list[str]) -> str | None:
    return next((m for m in milestones if milestone_tag(m) == tag), None)
