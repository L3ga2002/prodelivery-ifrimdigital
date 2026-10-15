"""Test de acceptanta INDEPENDENT pentru pilotul Ifrim Agent Hub (pachetul B4, M08).

Pregatit de Hub la aprobarea proprietarului si protejat in misiune (writer-ul nu il poate modifica).
Verifica livrabilul: suita backend/tests/test_driver_ranking_unit.py exista, trece doar cu biblioteca standard,
are cel putin 12 teste si apeleaza fiecare functie publica a modulului backend/utils/driver_ranking.py.
"""
import ast
import importlib.util
import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
UNIT = ROOT / "backend/tests/test_driver_ranking_unit.py"
REQUIRED = ["calculate_driver_score","get_tier_for_score","get_next_tier_for_score","_build_cycle_window","build_tier_access_state"]
MIN_TESTS = 12


def _test_methods(tree):
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                    count += 1
    return count


MODULE_FILE = (ROOT / "backend" / "utils" / "driver_ranking.py").resolve()


def _load_suite_module():
    for extra in (str(ROOT), str(ROOT / "backend")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    try:
        # The same way the check command loads it (package-relative imports keep working).
        return importlib.import_module("backend.tests.test_driver_ranking_unit")
    except ImportError:
        spec = importlib.util.spec_from_file_location("driver_ranking_unit_under_acceptance", UNIT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class DriverRankingUnitSuiteAcceptance(unittest.TestCase):
    def test_suite_exists(self):
        self.assertTrue(UNIT.is_file(), "suita unitara lipseste: " + str(UNIT.relative_to(ROOT)))

    def test_suite_has_enough_tests(self):
        self.assertTrue(UNIT.is_file(), "suita unitara lipseste: " + str(UNIT.relative_to(ROOT)))
        tree = ast.parse(UNIT.read_text(encoding="utf-8"))
        self.assertGreaterEqual(_test_methods(tree), MIN_TESTS, "suita are prea putine teste")

    def test_suite_passes_and_really_runs_every_public_function(self):
        self.assertTrue(UNIT.is_file(), "suita unitara lipseste: " + str(UNIT.relative_to(ROOT)))
        module = _load_suite_module()
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        called = set()

        def profile(frame, event, arg):
            # Records real calls into the module file (however the suite imports it), not names mentioned in the source.
            if event == "call" and frame.f_code.co_name in REQUIRED:
                try:
                    if pathlib.Path(frame.f_code.co_filename).resolve() == MODULE_FILE:
                        called.add(frame.f_code.co_name)
                except (OSError, ValueError):
                    pass

        stream = io.StringIO()
        sys.setprofile(profile)
        try:
            result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
        finally:
            sys.setprofile(None)
        self.assertGreaterEqual(result.testsRun, MIN_TESTS, "suita a rulat prea putine teste")
        self.assertTrue(result.wasSuccessful(), "suita unitara nu trece:\n" + stream.getvalue()[-3000:])
        missing = [name for name in REQUIRED if name not in called]
        self.assertEqual(missing, [], "functii fara niciun apel in suita: " + ", ".join(missing))


if __name__ == "__main__":
    unittest.main()
