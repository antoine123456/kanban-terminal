"""Run unittest and write a JUnit XML report (unittest can't).

    python unittest_xml.py REPORT.xml [unittest args…]     e.g. discover -s tests

Standard library only, so it runs with the project's own Python (its venv),
not the kanban's. The exit code is unittest's.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
import unittest
import xml.etree.ElementTree as ET


class XMLResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases: list[tuple[unittest.TestCase, str, str, str, float]] = []
        self._t0 = 0.0

    def startTest(self, test):
        self._t0 = time.perf_counter()
        super().startTest(test)

    def _add(self, test, status, err=None, reason=""):
        msg, detail = reason, ""
        if err is not None:
            msg = traceback.format_exception_only(err[0], err[1])[-1].strip()
            detail = self._exc_info_to_string(err, test)
        self.cases.append((test, status, msg, detail, time.perf_counter() - self._t0))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, "failure", err)

    def addError(self, test, err):
        super().addError(test, err)
        self._add(test, "error", err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._add(test, "skipped", reason=reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._add(test, "passed")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._add(test, "failure", reason="unexpected success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            failed = issubclass(err[0], test.failureException)
            self._add(subtest, "failure" if failed else "error", err)


def to_xml(cases) -> ET.Element:
    suites: dict[str, ET.Element] = {}
    root = ET.Element("testsuites")
    for test, status, msg, detail, secs in cases:
        tid = test.id()                                  # module.Class.method
        cls, _, name = tid.rpartition(".")
        if hasattr(test, "test_case"):                   # _SubTest: name with its params
            cls, _, base = test.test_case.id().rpartition(".")
            name = base + " " + test._subDescription()
        suite = suites.get(cls)
        if suite is None:
            suite = suites[cls] = ET.SubElement(root, "testsuite", name=cls)
        tc = ET.SubElement(suite, "testcase", classname=cls, name=name, time=f"{secs:.3f}")
        if status != "passed":
            el = ET.SubElement(tc, status, message=msg)
            el.text = detail
    for suite in suites.values():
        tcs = suite.findall("testcase")
        suite.set("tests", str(len(tcs)))
        for status, attr in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
            suite.set(attr, str(sum(tc.find(status) is not None for tc in tcs)))
    return root


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    out, rest = argv[0], argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]   # not our app.py, model.py…
    sys.path.insert(0, os.getcwd())
    prog = unittest.main(module=None, argv=["unittest"] + (rest or ["discover"]), exit=False,
                         testRunner=unittest.TextTestRunner(resultclass=XMLResult, verbosity=1))
    res = prog.result
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    ET.ElementTree(to_xml(res.cases)).write(out, encoding="utf-8", xml_declaration=True)
    return 0 if res.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
