import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ledger.validation import PROJECT_ROOT


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT_ROOT / ".test-data"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="unittest-", dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.database = self.directory / "ledger.sqlite3"

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "ledger", "--db", str(self.database), *arguments],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
