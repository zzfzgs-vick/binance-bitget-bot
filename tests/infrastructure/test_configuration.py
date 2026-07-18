from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class ConfigurationTests(unittest.TestCase):
    def test_empty_toml_uses_typed_live_defaults(self) -> None:
        from app.infrastructure.config.configuration import load_config

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            path.write_text("", encoding="utf-8")

            config = load_config(path, environ={})

        self.assertEqual(config.application.mode, "live")
        self.assertEqual(config.logging.level, "INFO")
        self.assertEqual(config.logging.third_party_level, "WARNING")
        self.assertEqual(config.logging.directory, Path("logs"))
        self.assertEqual(config.logging.file_name, "application.log")
        self.assertEqual(config.logging.max_bytes, 5_000_000)
        self.assertEqual(config.logging.backup_count, 3)

    def test_toml_values_override_defaults(self) -> None:
        from app.infrastructure.config.configuration import load_config

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            path.write_text(
                """[application]
mode = "live"

[logging]
level = "DEBUG"
third_party_level = "ERROR"
directory = "runtime-logs"
file_name = "desktop.log"
max_bytes = 12345
backup_count = 7
""",
                encoding="utf-8",
            )

            config = load_config(path, environ={})

        self.assertEqual(config.logging.level, "DEBUG")
        self.assertEqual(config.logging.third_party_level, "ERROR")
        self.assertEqual(config.logging.directory, Path("runtime-logs"))
        self.assertEqual(config.logging.file_name, "desktop.log")
        self.assertEqual(config.logging.max_bytes, 12345)
        self.assertEqual(config.logging.backup_count, 7)

    def test_environment_overrides_logging_values(self) -> None:
        from app.infrastructure.config.configuration import load_config

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            path.write_text("", encoding="utf-8")

            config = load_config(
                path,
                environ={
                    "APP_LOG_LEVEL": "DEBUG",
                    "APP_THIRD_PARTY_LOG_LEVEL": "CRITICAL",
                    "APP_LOG_DIRECTORY": "environment-logs",
                    "APP_LOG_FILE": "environment.log",
                    "APP_LOG_MAX_BYTES": "24680",
                    "APP_LOG_BACKUP_COUNT": "4",
                },
            )

        self.assertEqual(config.logging.level, "DEBUG")
        self.assertEqual(config.logging.third_party_level, "CRITICAL")
        self.assertEqual(config.logging.directory, Path("environment-logs"))
        self.assertEqual(config.logging.file_name, "environment.log")
        self.assertEqual(config.logging.max_bytes, 24680)
        self.assertEqual(config.logging.backup_count, 4)

    def test_invalid_field_type_names_the_field_and_reason(self) -> None:
        from app.infrastructure.config.configuration import ConfigurationError, load_config

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            path.write_text("[logging]\nlevel = 123\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ConfigurationError,
                r"logging\.level: expected string",
            ):
                load_config(path, environ={})

    def test_unknown_or_sensitive_toml_section_is_rejected(self) -> None:
        from app.infrastructure.config.configuration import ConfigurationError, load_config

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            path.write_text(
                '[credentials]\napi_key = "must-not-be-stored-here"\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError,
                r"credentials: unknown section",
            ):
                load_config(path, environ={})

    def test_invalid_values_report_their_configuration_field(self) -> None:
        from app.infrastructure.config.configuration import ConfigurationError, load_config

        cases = (
            ('[application]\nmode = "not-live"\n', "application.mode"),
            ('[logging]\nthird_party_level = 123\n', "logging.third_party_level"),
            ('[logging]\ndirectory = 123\n', "logging.directory"),
            ('[logging]\nfile_name = 123\n', "logging.file_name"),
            ('[logging]\nmax_bytes = "large"\n', "logging.max_bytes"),
            ('[logging]\nbackup_count = -1\n', "logging.backup_count"),
        )
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            for content, field_name in cases:
                with self.subTest(field_name=field_name):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(
                        ConfigurationError,
                        field_name.replace(".", r"\."),
                    ):
                        load_config(path, environ={})

    def test_invalid_toml_reports_the_file(self) -> None:
        from app.infrastructure.config.configuration import ConfigurationError, load_config

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "broken.toml"
            path.write_text("[logging\n", encoding="utf-8")

            with self.assertRaises(ConfigurationError) as raised:
                load_config(path, environ={})

        self.assertIn(str(path), str(raised.exception))
        self.assertIn("invalid TOML", str(raised.exception))

    def test_invalid_environment_integer_names_variable_and_field(self) -> None:
        from app.infrastructure.config.configuration import ConfigurationError, load_config

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            path.write_text("", encoding="utf-8")

            with self.assertRaises(ConfigurationError) as raised:
                load_config(path, environ={"APP_LOG_MAX_BYTES": "many"})

        message = str(raised.exception)
        self.assertIn("logging.max_bytes", message)
        self.assertIn("APP_LOG_MAX_BYTES", message)


if __name__ == "__main__":
    unittest.main()
