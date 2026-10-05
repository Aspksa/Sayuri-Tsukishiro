from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.config import Settings
from app.core import SayuriCore


class CoreTests(unittest.TestCase):
    def test_health_reads_versions_and_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("9.8.7\n", encoding="utf-8")
            (root / "MODULES.json").write_text(
                json.dumps({"schema_version": 1, "modules": [{"id": "core", "path": "module"}]}),
                encoding="utf-8",
            )
            (root / "module").mkdir()
            (root / "module" / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            settings = Settings(root=root, preferred_port=8765)
            core = SayuriCore(settings)
            core.initialize()
            health = core.health(port=8765)
            self.assertEqual(health["project_version"], "9.8.7")
            self.assertEqual(health["modules"]["core"], "1.2.3")
            self.assertTrue(health["server"]["loopback_only"])
            self.assertEqual(health["database"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
