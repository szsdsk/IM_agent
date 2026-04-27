import unittest

from backend.agent.orchestrator import AgentOrchestrator


class LangGraphRoutingTests(unittest.TestCase):
    def test_routes_to_doc_when_document_is_required(self):
        state = {"content_types": ["doc"], "steps": [{"module": "DOC"}], "error": None}

        self.assertEqual(AgentOrchestrator._route_after_extract(state), "generate_doc")

    def test_routes_to_slides_when_only_deck_is_required(self):
        state = {"content_types": ["slides"], "steps": [{"module": "DECK"}], "error": None}

        self.assertEqual(AgentOrchestrator._route_after_extract(state), "generate_slides")

    def test_routes_error_to_delivery(self):
        state = {"content_types": ["slides"], "steps": [{"module": "DECK"}], "error": "failed"}

        self.assertEqual(AgentOrchestrator._route_after_extract(state), "deliver_result")


if __name__ == "__main__":
    unittest.main()
