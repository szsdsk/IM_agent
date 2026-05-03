import unittest

from backend.services.canvas_layout import normalize_canvas_artifact


class CanvasLayoutTests(unittest.TestCase):
    def test_old_canvas_spec_gets_renderable_elements(self):
        result = normalize_canvas_artifact(
            title="流程图",
            diagram_type="flow",
            task_id="task_1",
            nodes=[
                {"id": "n1", "text": "接收需求", "type": "input"},
                {"id": "n2", "text": "生成 PPT", "type": "process"},
            ],
            edges=[{"source": "n1", "target": "n2", "label": "下一步"}],
        )

        self.assertEqual(result["provider"], "local_canvas")
        self.assertTrue(result["exportable"])
        self.assertEqual(result["diagram_type"], "flow")
        self.assertTrue(any(element["type"] == "node" for element in result["elements"]))
        self.assertTrue(any(element["type"] == "edge" for element in result["elements"]))
        self.assertIn("viewport", result)

    def test_architecture_layers_create_grouped_nodes(self):
        result = normalize_canvas_artifact(
            title="系统架构图",
            diagram_type="architecture",
            task_id="task_arch",
            layers=[["前端", "后端"], ["数据库", "飞书 OpenAPI"]],
        )

        self.assertEqual(result["diagram_type"], "architecture")
        self.assertTrue(any(element["type"] == "group" for element in result["elements"]))
        self.assertEqual(len(result["nodes"]), 4)

    def test_empty_canvas_has_safe_fallback(self):
        result = normalize_canvas_artifact(
            title="空画布",
            diagram_type="flow",
            task_id="task_empty",
        )

        self.assertGreaterEqual(len(result["nodes"]), 3)
        self.assertEqual(result["metadata"]["sync_status"], "local_only")

    def test_artifact_nodes_are_detected(self):
        result = normalize_canvas_artifact(
            title="交付链路",
            diagram_type="delivery_pipeline",
            task_id="task_delivery",
            nodes=[
                {"id": "generate_doc", "text": "生成文档"},
                {"id": "generate_slides", "text": "生成 PPT"},
            ],
        )

        artifact_types = {node.get("artifact_type") for node in result["nodes"]}
        self.assertIn("doc", artifact_types)
        self.assertIn("slides", artifact_types)
        self.assertEqual(result["diagram_type"], "delivery_pipeline")


if __name__ == "__main__":
    unittest.main()
