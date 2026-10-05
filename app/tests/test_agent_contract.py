from __future__ import annotations

import unittest

from agent import AgentCoreContract, AgentRequest


class AgentContractTests(unittest.TestCase):
    def test_contract_is_ready_but_execution_is_disabled(self):
        state = AgentCoreContract.snapshot()
        self.assertEqual(state["status_code"], "contract_ready")
        self.assertFalse(state["execution_enabled"])
        self.assertFalse(state["provider_connected"])
        request = AgentRequest(text="Проверка", context={"module": "settings"})
        description = AgentCoreContract.describe_request(request)
        self.assertEqual(description["text"], "Проверка")
        self.assertEqual(description["context"]["module"], "settings")


if __name__ == "__main__":
    unittest.main()
