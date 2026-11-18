"""Test results the JUnit way: one bar, green if everything passes, red as
soon as one test fails; Runs · Errors · Failures · Skipped; the failures and
their trace.

The results are read from JUnit XML reports, the format every test tool can
write (pytest --junitxml, Maven surefire, Gradle, Jest, cargo nextest…), so
the view works for any language. unittest can't write it: unittest_xml.py
does it.

How to run the tests of a project, first match:
    --cmd / --report given          that command, that report (glob)
    pom.xml                         mvn test        → target/surefire-reports/
    build.gradle(.kts)              gradle test     → build/test-results/test/
    Python with pytest              pytest --junitxml
    Python with a tests/ folder     unittest, through unittest_xml.py
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

ADAPTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unittest_xml.py")


@dataclass
class Case:
    suite: str
    name: str
    classname: str = ""
    time: float = 0.0
    status: str = "passed"        # passed · failure · error · skipped
    message: str = ""
    detail: str = ""              # the trace

    @property
    def title(self) -> str:
        cls = self.classname or self.suite
        return f"{cls}.{self.name}" if cls else self.name

    @property
    def bad(self) -> bool:
        return self.status in ("failure", "error")


@dataclass
class Result:
    cases: list[Case] = field(default_factory=list)
    command: str = ""
    output: str = ""              # what the command printed (shown when there is no report)
    returncode: int | None = None
    seconds: float = 0.0
    problem: str = ""             # no report, command not found…

    def count(self, status: str) -> int:
        return sum(c.status == status for c in self.cases)

    @property
    def runs(self) -> int:
        return len(self.cases) - self.count("skipped")

    @property
    def ok(self) -> bool:
        return not self.problem and bool(self.cases) and not any(c.bad for c in self.cases)

    @property
    def failures(self) -> list[Case]:
        return [c for c in self.cases if c.bad]


# ── reading the reports ──
def parse_xml(text: str) -> list[Case]:
    root = ET.fromstring(text)
    suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
    cases = []
    for suite in suites:
        sname = suite.get("name", "")
        for tc in suite.findall("testcase"):
            case = Case(sname, tc.get("name", "?"), tc.get("classname", ""), float(tc.get("time") or 0))
            for status in ("failure", "error", "skipped"):
                el = tc.find(status)
                if el is not None:
                    case.status = status
                    case.message = (el.get("message") or "").strip()
                    case.detail = (el.text or "").strip()
                    break
            cases.append(case)
    return cases


def read_reports(pattern: str) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(glob.glob(pattern, recursive=True)):
        with open(path, encoding="utf-8", errors="replace") as f:
            cases += parse_xml(f.read())
    return cases


# ── finding how to run them ──
def project_root(start: str) -> str:
    """The git root above ``start`` (else ``start``)."""
    d = os.path.abspath(start if os.path.isdir(start) else os.path.dirname(start))
    probe = d
    while True:
        if os.path.exists(os.path.join(probe, ".git")):
            return probe
        up = os.path.dirname(probe)
        if up == probe:
            return d
        probe = up


def python_of(root: str) -> str:
    for venv in (".venv", "venv", "env"):
        p = os.path.join(root, venv, "bin", "python")
        if os.path.exists(p):
            return p
    return sys.executable


def has_module(python: str, module: str) -> bool:
    try:
        return subprocess.run([python, "-c", f"import {module}"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def report_path(root: str) -> str:
    h = hashlib.sha1(root.encode()).hexdigest()[:10]
    return os.path.join(tempfile.gettempdir(), "kanban-tests", f"{h}.xml")


def detect(root: str) -> tuple[list[str], str, str] | None:
    """(command, report glob, label) to run the tests of ``root``."""
    def has(*names: str) -> bool:
        return any(os.path.exists(os.path.join(root, n)) for n in names)

    if has("pom.xml"):
        mvn = "./mvnw" if has("mvnw") else "mvn"
        return [mvn, "-q", "test"], os.path.join(root, "target/surefire-reports/TEST-*.xml"), "Maven"
    if has("build.gradle", "build.gradle.kts"):
        gradle = "./gradlew" if has("gradlew") else "gradle"
        return [gradle, "test", "-q"], os.path.join(root, "build/test-results/test/*.xml"), "Gradle"
    if has("pyproject.toml", "setup.py", "setup.cfg", "tests", "test"):
        py, out = python_of(root), report_path(root)
        if has("pytest.ini", "conftest.py") or has_module(py, "pytest"):
            return [py, "-m", "pytest", "-q", f"--junitxml={out}"], out, "pytest"
        start = "tests" if has("tests") else "test" if has("test") else "."
        return [py, ADAPTER, out, "discover", "-s", start], out, "unittest"
    return None


def run(root: str, cmd: str | None = None, report: str | None = None, timeout: int = 900) -> Result:
    """Run the tests of ``root`` and read their report."""
    if cmd:
        argv, pattern, label = shlex.split(cmd), report or report_path(root), cmd
        if not report:
            return Result(command=cmd, problem="--cmd demande aussi --report (le XML JUnit qu'il écrit).")
    else:
        found = detect(root)
        if not found:
            return Result(problem="Pas de tests trouvés (ni pom.xml, ni Gradle, ni Python). Utiliser --cmd et --report.")
        argv, pattern, label = found
    pattern = pattern if os.path.isabs(pattern) else os.path.join(root, pattern)
    for old in glob.glob(pattern, recursive=True):        # no stale results
        os.remove(old)
    os.makedirs(os.path.dirname(pattern), exist_ok=True)
    res = Result(command=f"{os.path.basename(root)} · {label}")
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=timeout)
        res.output, res.returncode = (p.stdout + p.stderr).strip(), p.returncode
    except FileNotFoundError:
        res.problem = f"Commande introuvable : {argv[0]}"
        return res
    except subprocess.TimeoutExpired:
        res.problem = f"Plus de {timeout} s : arrêté."
        return res
    res.seconds = time.monotonic() - t0
    try:
        res.cases = read_reports(pattern)
    except ET.ParseError as err:
        res.problem = f"Rapport illisible : {err}"
    if not res.cases and not res.problem:
        res.problem = "Aucun rapport JUnit écrit (erreur de compilation ? voir la sortie)."
    return res


# ── text ──
def bar_color(res: Result) -> str:
    return "32" if res.ok else "31"


def bar_width(res: Result, cols: int) -> int:
    """The bar ends with the text under it: a block that belongs to the result,
    not a line across the screen that could pass for a glitch."""
    return min(cols, max(len(summary(res)), len(res.command), 20))


def summary(res: Result) -> str:
    return (f"Runs: {res.runs}   Errors: {res.count('error')}   Failures: {res.count('failure')}"
            f"   Skipped: {res.count('skipped')}   {res.seconds:.1f}s")


def render(res: Result, cols: int, color: bool = True, trace_lines: int = 8) -> list[str]:
    def pen(code: str, s: str) -> str:
        return f"\x1b[{code}m{s}\x1b[0m" if color and code else s

    out = [pen("1", res.command[:cols]) if res.command else ""]
    out.append(pen(bar_color(res), "█" * bar_width(res, cols)))
    out.append(summary(res))
    if res.problem:
        out += ["", pen("31", res.problem)]
        if res.output:
            out += [pen("90", l[:cols]) for l in res.output.splitlines()[-trace_lines * 2:]]
    for c in res.failures:
        sign = "✗" if c.status == "failure" else "!"
        out += ["", pen("31", f"{sign} {c.title}"[:cols])]
        if c.message:
            out.append(f"  {c.message.splitlines()[0]}"[:cols])
        out += [pen("90", f"    {l}"[:cols]) for l in c.detail.splitlines()[-trace_lines:]]
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tests", description="Lance les tests et affiche la barre verte / rouge, façon JUnit.")
    ap.add_argument("path", nargs="?", default=".", help="dossier du projet (défaut : ici, remonte jusqu'à la racine git)")
    ap.add_argument("--cmd", help="commande qui lance les tests (avec --report)")
    ap.add_argument("--report", help="rapport(s) JUnit XML écrit(s) par la commande (glob)")
    ap.add_argument("--read", metavar="GLOB", help="ne lance rien : lit seulement ces rapports")
    ap.add_argument("--width", type=int)
    a = ap.parse_args(argv)
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    cols = a.width or shutil.get_terminal_size((80, 24)).columns
    if a.read:
        res = Result(cases=read_reports(a.read), command=a.read)
        if not res.cases:
            res.problem = "Aucun cas de test dans ces rapports."
    else:
        root = project_root(a.path)
        if sys.stdout.isatty():
            print("…", end="\r", flush=True)
        res = run(root, a.cmd, a.report)
    print("\n".join(render(res, cols, color)))
    sys.exit(0 if res.ok else 1)


if __name__ == "__main__":
    main()
