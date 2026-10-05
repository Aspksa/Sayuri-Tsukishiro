from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from app.config import Settings
from app.core import SayuriCore
from app.logging_setup import configure_logging
from app.server import SayuriRequestHandler, create_server


class _AbortWriter:
    def write(self, body):
        raise ConnectionAbortedError(10053, "клиент закрыл соединение")


class ServerTests(unittest.TestCase):
    def _start_server(self, root: Path):
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "MODULES.json").write_text(
            json.dumps({"schema_version": 1, "modules": []}),
            encoding="utf-8",
        )
        (root / "web").mkdir()
        (root / "web" / "index.html").write_text("<h1>Саюри</h1>", encoding="utf-8")
        settings = Settings(root=root, host="127.0.0.1", preferred_port=18000, port_scan_limit=100)
        core = SayuriCore(settings)
        core.initialize()
        server = create_server(core, configure_logging(settings.logs_dir))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_system_settings_static_index_and_favicon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server, thread = self._start_server(root)
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/api/system", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["status"], "готово")
                    self.assertEqual(payload["agent"]["status_code"], "provider_not_configured")

                with urllib.request.urlopen(base + "/api/settings", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    keys = {item["key"] for item in payload["settings"]}
                    self.assertIn("ui.refresh_seconds", keys)

                with urllib.request.urlopen(base + "/api/sayuri/profile", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["provider"]["model"], "deepseek-ai/DeepSeek-V4-Flash")
                    self.assertFalse(payload["provider"]["configured"])

                secret = "test-cloudru-key-123456789"
                body = json.dumps({"api_key": secret}).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/sayuri/provider",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(payload["provider"]["configured"])
                    self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))

                action_body = json.dumps({
                    "text": "создай папку Проверка действий",
                    "context": {"view": "disk", "disk": {"folder_id": None}},
                }).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/sayuri/actions/plan",
                    data=action_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    action_id = payload["action"]["id"]
                    self.assertEqual(payload["action"]["status"], "pending")

                with urllib.request.urlopen(base + "/api/disk", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["folders"], [])

                request = urllib.request.Request(
                    base + f"/api/sayuri/actions/{action_id}/confirm",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["status"], "completed")

                request = urllib.request.Request(
                    base + f"/api/sayuri/actions/{action_id}/confirm",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["status"], "completed")

                with urllib.request.urlopen(base + "/api/disk", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(
                        [item["name"] for item in payload["folders"]],
                        ["Проверка действий"],
                    )

                with urllib.request.urlopen(base + "/api/sayuri/actions", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(payload["tools"])
                    self.assertEqual(payload["actions"][0]["id"], action_id)

                memory_body = json.dumps({
                    "scope": "project",
                    "kind": "decision",
                    "importance": 5,
                    "content": "Sayuri использует разделённую проектную память",
                }).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/sayuri/memory",
                    data=memory_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    memory_id = payload["entry"]["id"]
                    self.assertEqual(payload["entry"]["scope"], "project")

                with urllib.request.urlopen(base + "/api/sayuri/memory?scope=project", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(len(payload["entries"]), 1)
                    self.assertEqual(payload["entries"][0]["id"], memory_id)

                intelligence_body = json.dumps({
                    "settings": {
                        "candidate_generation": True,
                        "conflict_detection": True,
                        "context_linking": True,
                        "auto_save_high_confidence": False,
                        "auto_save_threshold": 0.98,
                    }
                }).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/sayuri/memory/intelligence",
                    data=intelligence_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["settings"]["auto_save_threshold"], 0.98)

                with urllib.request.urlopen(base + "/api/sayuri/memory/intelligence", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(payload["settings"]["candidate_generation"])

                server.core.agent.experience.record_chat_response(
                    "response-api-test",
                    {"view": "sayuri"},
                )
                feedback_body = json.dumps({
                    "response_id": "response-api-test",
                    "rating": "useful",
                    "prompt": "Как улучшить память Sayuri?",
                    "answer": "Использовать отдельную очередь кандидатов памяти.",
                    "context": {"view": "sayuri"},
                }).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/sayuri/experience/feedback",
                    data=feedback_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["event"]["outcome"], "useful")
                    self.assertGreaterEqual(payload["stats"]["positive"], 1)

                with urllib.request.urlopen(base + "/api/sayuri/experience?limit=20", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertGreaterEqual(payload["stats"]["total"], 2)
                    self.assertTrue(
                        any(item["subject_id"] == "response-api-test" for item in payload["recent"])
                    )

                candidates = server.core.agent.memory_intelligence.analyze_message(
                    "Я предпочитаю компактный светлый интерфейс",
                    {"view": "sayuri"},
                )
                candidate_id = candidates[0]["id"]

                with urllib.request.urlopen(base + "/api/sayuri/memory/candidates?limit=20", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(any(item["id"] == candidate_id for item in payload["candidates"]))

                review_body = json.dumps({"decision": "accept"}).encode("utf-8")
                request = urllib.request.Request(
                    base + f"/api/sayuri/memory/candidates/{candidate_id}/review",
                    data=review_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["candidate"]["status"], "accepted")
                    self.assertEqual(payload["stats"]["personal"]["count"], 1)

                with urllib.request.urlopen(base + "/api/sayuri/memory/v3", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["stats"]["version"], "3.0")
                    self.assertGreaterEqual(payload["stats"]["knowledge"], 1)
                    self.assertGreaterEqual(payload["stats"]["graph_nodes"], 1)

                request = urllib.request.Request(
                    base + "/api/sayuri/memory/v3/maintenance",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["status"], "готово")
                    self.assertIn("retention", payload)

                conflict_old = server.core.agent.memory.add(
                    scope="personal",
                    kind="preference",
                    content="Я предпочитаю тёмный интерфейс",
                    importance=4,
                    confidence=0.9,
                )
                conflict_new = server.core.agent.memory.add(
                    scope="personal",
                    kind="preference",
                    content="Я предпочитаю светлый интерфейс",
                    importance=4,
                    confidence=0.95,
                    supersedes_id=conflict_old["id"],
                )
                conflict = server.core.agent.memory_v3.register_conflict(
                    candidate_id="server-test-conflict",
                    old_memory_id=conflict_old["id"],
                    new_memory_id=conflict_new["id"],
                    scope="personal",
                )
                resolution_body = json.dumps({"resolution": "prefer_new"}).encode("utf-8")
                request = urllib.request.Request(
                    base + f"/api/sayuri/memory/v3/conflicts/{conflict['id']}/resolve",
                    data=resolution_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload["conflict"]["status"], "resolved")
                    self.assertEqual(payload["conflict"]["resolution"], "prefer_new")

                png = (
                    b"\x89PNG\r\n\x1a\n"
                    + b"\x00\x00\x00\x0dIHDR"
                    + (192).to_bytes(4, "big")
                    + (192).to_bytes(4, "big")
                    + b"\x08\x06\x00\x00\x00"
                    + b"\x00\x00\x00\x00"
                )
                request = urllib.request.Request(
                    base + "/api/sayuri/avatar/upload?slot=orb",
                    data=png,
                    headers={
                        "Content-Type": "image/png",
                        "X-Sayuri-Filename": "orb.png",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(payload["avatar"]["custom"])
                    self.assertEqual(payload["avatar"]["width"], 192)

                with urllib.request.urlopen(base + "/api/sayuri/avatar/orb", timeout=2) as response:
                    self.assertEqual(response.headers.get_content_type(), "image/png")
                    self.assertEqual(response.read(), png)

                request = urllib.request.Request(
                    base + f"/api/sayuri/memory/{memory_id}",
                    method="DELETE",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(payload["deleted"])

                request = urllib.request.Request(
                    base + "/api/sayuri/avatar/orb",
                    method="DELETE",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertFalse(payload["avatar"]["custom"])

                body = json.dumps(
                    {"settings": {"ui.refresh_seconds": 15, "events.display_limit": 20}}
                ).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/settings",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    values = {item["key"]: item["value"] for item in payload["settings"]}
                    self.assertEqual(values["ui.refresh_seconds"], 15)
                    self.assertEqual(values["events.display_limit"], 20)

                with urllib.request.urlopen(base + "/", timeout=2) as response:
                    self.assertIn("Саюри", response.read().decode("utf-8"))

                try:
                    urllib.request.urlopen(base + "/favicon.ico", timeout=2)
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 204)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_client_disconnect_is_not_raised_as_server_error(self):
        handler = SayuriRequestHandler.__new__(SayuriRequestHandler)
        handler.path = "/api/health"
        handler.wfile = _AbortWriter()
        handler.server = type(
            "Server",
            (),
            {"logger": logging.getLogger("sayuri-test")},
        )()
        handler._headers = lambda status, content_type, length, extra_headers=None: None
        self.assertFalse(handler._send(b"{}", "application/json", 200))


if __name__ == "__main__":
    unittest.main()
