import unittest

from kanban_terminal import theme as th


class ThemeTest(unittest.TestCase):
    def test_osc11(self):
        self.assertEqual(th.parse_osc11("\033]11;rgb:ffff/ffff/ffff\007"), th.LIGHT)
        self.assertEqual(th.parse_osc11("\033]11;rgb:1e1e/1e1e/1e1e\033\\"), th.DARK)
        self.assertEqual(th.parse_osc11("\033]11;rgb:f8/f8/f8\007"), th.LIGHT)
        self.assertIsNone(th.parse_osc11(""))

    def test_vscode_theme(self):
        self.assertEqual(th.vscode_theme({"workbench.colorTheme": "Light Modern"}, th.DARK), th.LIGHT)
        self.assertEqual(th.vscode_theme({"workbench.colorTheme": "Default High Contrast"}, th.LIGHT), th.DARK)
        self.assertEqual(th.vscode_theme({}, th.LIGHT), th.DARK)  # VS Code's default: Dark Modern
        auto = {"window.autoDetectColorScheme": True, "workbench.colorTheme": "Light Modern",
                "workbench.preferredDarkColorTheme": "Monokai"}
        self.assertEqual(th.vscode_theme(auto, th.DARK), th.DARK)
        self.assertEqual(th.vscode_theme(auto, th.LIGHT), th.LIGHT)

    def test_transparent_terminal(self):
        """VS Code with "terminal.background": "#00000000" answers OSC 11 with
        black: the theme must win over that answer."""
        self.assertTrue(th.transparent_terminal({"workbench.colorCustomizations": {"terminal.background": "#00000000"}}))
        self.assertTrue(th.transparent_terminal({"workbench.colorTheme": "Light Modern",
                                                 "workbench.colorCustomizations": {"[Light Modern]": {"terminal.background": "#fff0"}}}))
        self.assertFalse(th.transparent_terminal({"workbench.colorCustomizations": {"terminal.background": "#1e1e1e"}}))
        self.assertFalse(th.transparent_terminal({}))

    def test_jsonc(self):
        txt = '{\n  // comment\n  "a": "http://x", /* block */\n  "b": [1, 2,],\n}'
        self.assertEqual(th._jsonc(txt), {"a": "http://x", "b": [1, 2]})


if __name__ == "__main__":
    unittest.main()
