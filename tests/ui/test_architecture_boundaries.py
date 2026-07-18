from pathlib import Path
import unittest


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_views_do_not_import_trading_implementations(self) -> None:
        forbidden = ("app.exchanges", "app.execution", "app.market_data")
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


if __name__ == "__main__":
    unittest.main()
