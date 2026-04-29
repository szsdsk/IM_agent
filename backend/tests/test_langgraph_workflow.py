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

    def test_extracts_chinese_slide_feedback_target(self):
        self.assertEqual(AgentOrchestrator._extract_slide_indexes("第 3 页改成风险分析", 8), [2])

    def test_extracts_english_slide_feedback_target(self):
        self.assertEqual(AgentOrchestrator._extract_slide_indexes("slide 5 add Q&A", 8), [4])

    def test_rehearsal_request_does_not_force_slide_rewrite(self):
        should_update = AgentOrchestrator._should_update_slides(
            "帮我生成排练讲稿和 Q&A",
            {},
            {"slides": [{"title": "封面"}]},
        )

        self.assertFalse(should_update)


if __name__ == "__main__":
    unittest.main()
