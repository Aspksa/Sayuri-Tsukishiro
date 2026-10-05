from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent import CLOUDRU_BASE_URL, CLOUDRU_MODEL_ID, SayuriAgent
from agent.runtime import SecretStore


class AgentRuntimeTests(unittest.TestCase):
    def test_secret_store_roundtrip_and_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sayuri.secret"
            store = SecretStore(path)
            secret = "test-key-1234567890-abcdef"
            store.set(secret)
            self.assertEqual(store.get(), secret)
            snapshot = store.snapshot().public()
            self.assertTrue(snapshot["configured"])
            self.assertNotIn(secret, str(snapshot))
            self.assertTrue(snapshot["api_key_masked"].startswith("test"))
            store.clear()
            self.assertFalse(store.snapshot().configured)

    def test_sayuri_is_locked_to_cloudru_deepseek_v4_flash(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = SayuriAgent(Path(tmp))
            profile = agent.profile()
            self.assertEqual(profile["provider"]["provider"], "Cloud.ru")
            self.assertEqual(profile["provider"]["model"], CLOUDRU_MODEL_ID)
            self.assertEqual(profile["provider"]["base_url"], CLOUDRU_BASE_URL)
            self.assertFalse(profile["provider"]["configured"])
            self.assertTrue(profile["chat"]["context_aware"])


if __name__ == "__main__":
    unittest.main()
