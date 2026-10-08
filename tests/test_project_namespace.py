import ast
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from fulcrum.service.app import create_app


class NamespaceTests(unittest.TestCase):
    def test_new_and_legacy_token_headers_share_authorization(self):
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(Path(temporary))) as client:
            session = client.get("/api/session").json()
            self.assertEqual(session["header"], "X-Fulcrum-Token")
            for header in ("X-Fulcrum-Token", "X-Blackflow-Token"):
                self.assertEqual(client.get("/api/runs", headers={header: session["token"]}).status_code, 200)
                self.assertEqual(client.get("/api/runs", headers={header: "invalid"}).status_code, 401)
            self.assertEqual(client.get("/api/runs", headers={
                "X-Fulcrum-Token": "invalid", "X-Blackflow-Token": session["token"],
            }).status_code, 401)

    def test_python_entry_points_and_build_spec_use_fulcrum(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "blackflow").exists())
        self.assertTrue((root / "packaging/fulcrum.spec").is_file())
        for directory in ("fulcrum", "scripts", "tests", "experiments"):
            for file in (root / directory).rglob("*.py"):
                source = file.read_text(encoding="utf-8")
                for node in ast.walk(ast.parse(source)):
                    modules = ([node.module] if isinstance(node, ast.ImportFrom) else
                               [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                    self.assertFalse(any(module and module.split('.')[0] == "blackflow" for module in modules), str(file))
                    if isinstance(node, (ast.List, ast.Tuple)):
                        values = [element.value if isinstance(element, ast.Constant) else None for element in node.elts]
                        for previous, current in zip(values, values[1:]):
                            if previous == "-m" and isinstance(current, str):
                                self.assertFalse(current.startswith("blackflow."), str(file))
        self.assertIn("from fulcrum.desktop import main", (root / "desktop_launcher.py").read_text())
