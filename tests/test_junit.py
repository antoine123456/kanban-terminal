import asyncio
import os
import subprocess
import sys
import tempfile
import unittest

from kanban_terminal import junit

REPORT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="pkg.MathTest" tests="4" failures="1" errors="1" skipped="1">
    <testcase classname="pkg.MathTest" name="test_add" time="0.010"/>
    <testcase classname="pkg.MathTest" name="test_sub" time="0.020">
      <failure message="expected 2 but was 3" type="AssertionError">at pkg.MathTest.test_sub(MathTest.java:12)</failure>
    </testcase>
    <testcase classname="pkg.MathTest" name="test_div" time="0.001">
      <error message="/ by zero" type="ArithmeticException">java.lang.ArithmeticException: / by zero</error>
    </testcase>
    <testcase classname="pkg.MathTest" name="test_later"><skipped/></testcase>
  </testsuite>
</testsuites>
"""

DEMO = '''import unittest
class Demo(unittest.TestCase):
    def test_ok(self): self.assertTrue(True)
    def test_fail(self): self.assertEqual(1 + 1, 3)
    def test_error(self): {}["missing"]
    @unittest.skip("later")
    def test_skip(self): pass
    def test_sub(self):
        for i in range(3):
            with self.subTest(i=i): self.assertLess(i, 2)
'''


def project(files: dict[str, str]) -> str:
    root = tempfile.mkdtemp()
    os.mkdir(os.path.join(root, ".git"))
    for name, text in files.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return root


class ParseTest(unittest.TestCase):
    def test_surefire_style_report(self):
        cases = junit.parse_xml(REPORT)
        self.assertEqual([c.status for c in cases], ["passed", "failure", "error", "skipped"])
        fail = cases[1]
        self.assertEqual(fail.title, "pkg.MathTest.test_sub")
        self.assertEqual(fail.message, "expected 2 but was 3")
        self.assertIn("MathTest.java:12", fail.detail)
        res = junit.Result(cases=cases)
        self.assertEqual((res.runs, res.count("failure"), res.count("error"), res.count("skipped")), (3, 1, 1, 1))
        self.assertFalse(res.ok)
        self.assertEqual([c.name for c in res.failures], ["test_sub", "test_div"])

    def test_single_testsuite_root_and_green(self):
        cases = junit.parse_xml('<testsuite name="s"><testcase name="a"/><testcase name="b"/></testsuite>')
        self.assertTrue(junit.Result(cases=cases).ok)

    def test_no_case_is_not_green(self):
        self.assertFalse(junit.Result().ok)


class DetectTest(unittest.TestCase):
    def test_maven_gradle_python(self):
        self.assertEqual(junit.detect(project({"pom.xml": "<project/>"}))[2], "Maven")
        self.assertEqual(junit.detect(project({"build.gradle.kts": ""}))[2], "Gradle")
        self.assertIn(junit.detect(project({"tests/test_x.py": ""}))[2], ("unittest", "pytest"))
        self.assertIsNone(junit.detect(project({"notes.md": "# rien"})))

    def test_root_is_the_git_root(self):
        root = project({"a/b/idee.md": ""})
        self.assertEqual(junit.project_root(os.path.join(root, "a", "b", "idee.md")), root)


class UnittestAdapterTest(unittest.TestCase):
    def test_failures_errors_skips_and_subtests(self):
        root = project({"tests/test_demo.py": DEMO})
        out = os.path.join(root, "report.xml")
        p = subprocess.run([sys.executable, junit.ADAPTER, out, "discover", "-s", "tests"],
                           cwd=root, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stderr)
        with open(out, encoding="utf-8") as f:
            cases = {c.name: c for c in junit.parse_xml(f.read())}
        self.assertEqual(cases["test_ok"].status, "passed")
        self.assertEqual(cases["test_fail"].status, "failure")
        self.assertIn("2 != 3", cases["test_fail"].message)
        self.assertEqual(cases["test_error"].status, "error")
        self.assertEqual(cases["test_skip"].status, "skipped")
        self.assertEqual(cases["test_sub (i=2)"].status, "failure")

    def test_project_modules_win_over_ours(self):
        """A project with its own model.py must import it, not kanban's."""
        root = project({"model.py": "WHO = 'project'\n",
                        "tests/test_m.py": "import unittest, model\n"
                                           "class T(unittest.TestCase):\n"
                                           "    def test_who(self): self.assertEqual(model.WHO, 'project')\n"})
        out = os.path.join(root, "r.xml")
        p = subprocess.run([sys.executable, junit.ADAPTER, out, "discover", "-s", "tests"],
                           cwd=root, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_run_end_to_end(self):
        root = project({"tests/test_demo.py": DEMO})
        res = junit.run(root)
        self.assertEqual((res.runs, res.count("failure"), res.count("error")), (4, 2, 1))
        self.assertFalse(res.ok)
        self.assertEqual(res.problem, "")


class ViewTest(unittest.TestCase):
    def test_U_shows_the_bar_and_blocks_card_keys(self):
        from kanban_terminal.app import KanbanApp
        root = project({"tests/test_demo.py": DEMO, "idee.md": "## Idées\n- [ ] une idée\n"})

        async def go():
            app = KanbanApp(os.path.join(root, "idee.md"), follow=False)
            async with app.run_test(size=(100, 26)) as pilot:
                await pilot.press("U")
                await pilot.pause(0.3)
                self.assertIsNone(app.tests)  # nothing runs until r (#4)
                self.assertFalse(app.tests_running)
                await pilot.press("r")
                for _ in range(100):
                    await pilot.pause(0.1)
                    if app.tests is not None and not app.tests_running:
                        break
                self.assertFalse(app.tests.ok)
                self.assertFalse(app.check_action("move_to", ("done",)))
                self.assertTrue(app.check_action("reload", ()))
                await pilot.press("U")
                self.assertFalse(app.test_view)
                self.assertTrue(app.check_action("move_to", ("done",)))

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
