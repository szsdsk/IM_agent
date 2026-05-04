import asyncio
import unittest

from backend.services.canvas_layout import normalize_canvas_artifact
from backend.services.llm_service import generate_canvas_spec


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

    def test_content_map_layout_keeps_edges_readable(self):
        result = normalize_canvas_artifact(
            title="项目评审内容结构",
            diagram_type="content_map",
            task_id="task_content",
            nodes=[
                {"id": "topic", "text": "企业知识库智能问答", "type": "theme"},
                {"id": "p1", "text": "业务背景与目标", "type": "insight"},
                {"id": "p2", "text": "核心架构", "type": "insight"},
                {"id": "p3", "text": "落地计划", "type": "action"},
            ],
            edges=[
                {"source": "topic", "target": "p1", "label": "支撑"},
                {"source": "topic", "target": "p2", "label": "支撑"},
                {"source": "topic", "target": "p3", "label": "支撑"},
            ],
        )

        self.assertEqual(result["diagram_type"], "content_map")
        topic = next(node for node in result["nodes"] if node["id"] == "topic")
        children = [node for node in result["nodes"] if node["id"] != "topic"]
        self.assertTrue(all(child["x"] > topic["x"] for child in children))
        self.assertEqual(len(result["edges"]), 3)

    def test_local_canvas_spec_uses_content_not_workflow_steps(self):
        spec = asyncio.run(generate_canvas_spec(
            title="原神项目评审 PPT",
            intent="生成一个原神的项目评审 PPT",
            doc_content="# 背景与目标\n- 介绍产品定位\n- 分析用户体验\n- 给出运营计划",
            steps=[{"action": "generate_doc"}, {"action": "generate_canvas"}, {"action": "generate_slides"}],
            use_llm=False,
        ))

        labels = {node["text"] for node in spec["nodes"]}
        self.assertEqual(spec["diagram_type"], "content_map")
        self.assertNotIn("generate_slides", labels)
        self.assertTrue(any("背景" in label or "用户体验" in label for label in labels))


if __name__ == "__main__":
    unittest.main()
