import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = ROOT / "scripts" / "backup-db.sh"


class BackupDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        (self.repo / "scripts").mkdir()
        (self.repo / "data").mkdir()
        shutil.copy2(BACKUP_SCRIPT, self.repo / "scripts" / "backup-db.sh")
        self.script = self.repo / "scripts" / "backup-db.sh"
        self.database = self.repo / "data" / "scanner.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_database(self, table_names=("scan_results", "scan_runs")):
        with sqlite3.connect(self.database) as connection:
            for table_name in table_names:
                connection.execute(
                    f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY)"
                )

    def run_backup(self, *, umask=None):
        if umask is None:
            preexec_fn = None
        else:
            preexec_fn = lambda: os.umask(umask)
        return subprocess.run(
            ["/bin/zsh", str(self.script)],
            capture_output=True,
            check=False,
            preexec_fn=preexec_fn,
            text=True,
        )

    def backup_files(self):
        return list((self.repo / "backups").glob("scanner-*.db"))

    def temporary_paths(self):
        return list((self.repo / "backups").glob(".scanner-backup.*"))

    def test_publishes_private_valid_backup_only_after_validation(self):
        self.create_database()

        result = self.run_backup(umask=0o027)

        self.assertEqual(result.returncode, 0, result.stderr)
        backups = self.backup_files()
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.temporary_paths(), [])
        self.assertEqual(
            stat.S_IMODE((self.repo / "backups").stat().st_mode),
            0o700,
        )
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
        with sqlite3.connect(backups[0]) as connection:
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue({"scan_results", "scan_runs"}.issubset(table_names))

    def test_missing_required_table_does_not_publish_backup(self):
        self.create_database(("scan_results",))

        result = self.run_backup()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required tables", result.stderr)
        self.assertEqual(self.backup_files(), [])
        self.assertEqual(self.temporary_paths(), [])

    def test_corrupt_source_does_not_publish_backup(self):
        self.database.write_bytes(b"not a sqlite database")

        result = self.run_backup()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.backup_files(), [])
        self.assertEqual(self.temporary_paths(), [])

    def test_successful_backup_keeps_fourteen_day_retention(self):
        self.create_database()
        backup_dir = self.repo / "backups"
        backup_dir.mkdir()
        expired = backup_dir / "scanner-20000101T000000Z.db"
        expired.write_bytes(b"expired")
        sixteen_days_ago = time.time() - (16 * 24 * 60 * 60)
        os.utime(expired, (sixteen_days_ago, sixteen_days_ago))

        result = self.run_backup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(expired.exists())
        self.assertEqual(len(self.backup_files()), 1)


if __name__ == "__main__":
    unittest.main()
