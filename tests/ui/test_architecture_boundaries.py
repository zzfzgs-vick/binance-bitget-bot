from pathlib import Path
import unittest


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_views_do_not_import_trading_implementations(self) -> None:
        forbidden = (
            "app.exchanges",
            "app.execution",
            "app.market_data",
            "app.persistence",
            "app.infrastructure.network",
            "sqlite3",
            "tomllib",
        )
        for path in Path("app/ui/views").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for item in forbidden:
                self.assertNotIn(item, source, f"{path} imports {item}")

    def test_domain_has_no_infrastructure_imports(self) -> None:
        forbidden = ("PySide6", "requests", "websockets")
        for path in Path("app/domain").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for item in forbidden:
                self.assertNotIn(item, source, f"{path} imports {item}")

    def test_production_tree_is_live_only(self) -> None:
        forbidden_paths = (
            ".env.example",
            "app/paper",
            "app/ui/styles/paper_mode.qss",
            "config/default.toml",
            "config/development.toml",
            "config/paper.toml",
            "scripts/reset_paper_database.py",
            "scripts/run_paper.py",
        )
        for path in forbidden_paths:
            self.assertFalse(Path(path).exists(), path)

        self.assertTrue(Path("config/live.toml").is_file())
        view_source = Path("app/ui/views/main_window.py").read_text(encoding="utf-8")
        self.assertNotIn("paper_", view_source)
        self.assertNotIn("mode_change_requested", view_source)


if __name__ == "__main__":
    unittest.main()
