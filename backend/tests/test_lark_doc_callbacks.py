import json
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.api import endpoints
from backend.database.models import Document, Event, Task
from backend.services.lark_bot_service import LarkBotService, build_delivery_status_card


class _FakeResult:
    def __init__(self, item):
        self._item = item

    def scalar_one_or_none(self):
        return self._item


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False

    async def execute(self, _statement):
        return _FakeResult(self._results.pop(0))

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True


class _FakeSessionMaker:
    def __init__(self, sessions):
        self._sessions = list(sessions)

    def __call__(self):
        return self._sessions.pop(0)


class _NoopBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


class LarkDocCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_nested_card_action_and_returns_toast(self):
        payload = {
            "event": {
                "operator": {"operator_id": {"open_id": "ou_1"}},
                "action": {
                    "tag": "button",
                    "value": json.dumps({"action": "doc_edited", "task_id": "task_1"}),
                },
            }
        }

        action, value, open_id = endpoints._extract_lark_card_action(payload)
        toast = endpoints._lark_card_toast("已接收")

        self.assertEqual(action["tag"], "button")
        self.assertEqual(value["action"], "doc_edited")
        self.assertEqual(open_id, "ou_1")
        self.assertEqual(toast["toast"]["content"], "已接收")

    async def test_extracts_legacy_card_action_payload(self):
        payload = {
            "open_id": "ou_legacy",
            "action": {
                "tag": "button",
                "value": {"action": "confirm_delivery", "task_id": "task_1"},
            },
        }

        action, value, open_id = endpoints._extract_lark_card_action(payload)

        self.assertEqual(action["tag"], "button")
        self.assertEqual(value["action"], "confirm_delivery")
        self.assertEqual(open_id, "ou_legacy")

    async def test_card_toast_can_replace_original_card(self):
        card = build_delivery_status_card(
            task_id="task_1",
            status_text="已确认交付",
            detail="任务已锁定。",
            doc_title="测试文档",
            slides_title="测试 PPT",
            slides_count=3,
        )

        response = endpoints._lark_card_toast("已确认交付", card=card)

        self.assertEqual(response["toast"]["content"], "已确认交付")
        self.assertEqual(response["card"]["type"], "raw")
        self.assertEqual(response["card"]["data"]["header"]["title"]["content"], "Agent-Pilot 已确认交付")
        self.assertNotIn('"actions"', json.dumps(response["card"]["data"], ensure_ascii=False))

    async def test_confirm_delivery_returns_replacement_card(self):
        task = Task(
            id="task_1",
            session_id="session_1",
            intent="测试",
            status="completed",
            current_step="deliver_result",
            result_json={
                "chat_id": "oc_1",
                "result": {
                    "document": {"title": "测试文档", "doc_url": "https://example.feishu.cn/docx/doc_1"},
                    "slides": {"title": "测试 PPT", "slides_count": 3},
                },
            },
        )
        payload = {
            "open_id": "ou_1",
            "action": {
                "tag": "button",
                "value": {
                    "action": "confirm_delivery",
                    "task_id": "task_1",
                    "chat_id": "oc_1",
                },
            },
        }

        with patch("backend.api.endpoints.async_session_maker", _FakeSessionMaker([_FakeSession([task])])):
            response = await endpoints.lark_card_action(payload, _NoopBackgroundTasks())

        self.assertEqual(response["toast"]["type"], "success")
        self.assertEqual(response["card"]["data"]["header"]["title"]["content"], "Agent-Pilot 已确认交付")
        self.assertNotIn('"actions"', json.dumps(response["card"]["data"], ensure_ascii=False))

    async def test_matches_pending_lark_feedback_task(self):
        task = Task(
            id="task_1",
            session_id="session_1",
            intent="测试",
            status="pending",
            current_step="confirm_or_modify",
            result_json={
                "chat_id": "oc_1",
                "pending_feedback": {
                    "chat_id": "oc_1",
                    "user_id": "ou_1",
                },
            },
        )

        self.assertTrue(endpoints._task_matches_pending_lark_feedback(task, "oc_1", "ou_1"))
        self.assertFalse(endpoints._task_matches_pending_lark_feedback(task, "oc_other", "ou_1"))
        self.assertFalse(endpoints._task_matches_pending_lark_feedback(task, "oc_1", "ou_other"))

    async def test_confirmed_delivery_cannot_be_switched_back_to_modification(self):
        task = Task(
            id="task_1",
            session_id="session_1",
            intent="测试",
            status="completed",
            current_step="deliver_result",
            result_json={
                "chat_id": "oc_1",
                "delivery_confirmed": {
                    "chat_id": "oc_1",
                    "user_id": "ou_1",
                    "confirmed_at": "2026-04-29T00:00:00",
                },
            },
        )
        payload = {
            "open_id": "ou_1",
            "action": {
                "tag": "button",
                "value": {
                    "action": "request_modification",
                    "task_id": "task_1",
                    "chat_id": "oc_1",
                },
            },
        }

        with patch("backend.api.endpoints.async_session_maker", _FakeSessionMaker([_FakeSession([task])])):
            response = await endpoints.lark_card_action(payload, _NoopBackgroundTasks())

        self.assertEqual(response["toast"]["type"], "warning")
        self.assertEqual(task.status, "completed")
        self.assertNotIn("pending_feedback", task.result_json)

    async def test_create_doc_sends_folder_token(self):
        captured_payload = {}
        service = LarkBotService()
        service.app_id = "app"
        service.app_secret = "secret"
        service._tenant_access_token = "tenant_token"
        service._token_expires_at = time.time() + 3600

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_payload.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "document": {
                            "document_id": "doc_1",
                            "title": "标题",
                            "url": "https://example.feishu.cn/docx/doc_1",
                        }
                    },
                },
            )

        service._client = httpx.AsyncClient(
            base_url=service.base_url,
            transport=httpx.MockTransport(handler),
        )

        try:
            result = await service.create_doc(title="标题", folder_token="fld_1")
        finally:
            await service.close()

        self.assertTrue(result["success"])
        self.assertEqual(captured_payload["folder_token"], "fld_1")
        self.assertEqual(result["url"], "https://example.feishu.cn/docx/doc_1")

    async def test_sync_lark_doc_edit_updates_document_and_records_event(self):
        doc = Document(
            id="local_doc",
            task_id="task_1",
            content="旧内容",
            version=1,
            lark_doc_id="doc_1",
            lark_doc_url="https://example.feishu.cn/docx/doc_1",
        )
        task = Task(id="task_1", session_id="session_1", intent="测试", result_json={"chat_id": "chat_1"})
        first_session = _FakeSession([doc, task])
        second_session = _FakeSession([doc])

        with (
            patch("backend.api.endpoints.async_session_maker", _FakeSessionMaker([first_session, second_session])),
            patch.object(
                endpoints.lark_bot_service,
                "get_doc_raw_content",
                new=AsyncMock(return_value={"success": True, "content": "旧内容\n新增内容"}),
            ),
            patch.object(endpoints.sync_service, "broadcast_doc_update", new=AsyncMock()) as broadcast,
        ):
            result = await endpoints._sync_lark_doc_edit("doc_1", editor="ou_1", source="unit_test")

        self.assertTrue(result["success"])
        self.assertEqual(doc.version, 2)
        self.assertEqual(doc.content, "旧内容\n新增内容")
        self.assertEqual(doc.last_edited_by, "ou_1")
        self.assertEqual(len(second_session.added), 1)
        self.assertIsInstance(second_session.added[0], Event)
        self.assertEqual(second_session.added[0].payload["new_version"], 2)
        broadcast.assert_awaited_once()

    async def test_sync_lark_doc_edit_handles_fetch_failure(self):
        doc = Document(id="local_doc", task_id="task_1", content="旧内容", version=1, lark_doc_id="doc_1")
        task = Task(id="task_1", session_id="session_1", intent="测试", result_json={})
        first_session = _FakeSession([doc, task])

        with (
            patch("backend.api.endpoints.async_session_maker", _FakeSessionMaker([first_session])),
            patch.object(
                endpoints.lark_bot_service,
                "get_doc_raw_content",
                new=AsyncMock(return_value={"success": False, "error": "network"}),
            ),
            patch.object(endpoints.logger, "warning"),
        ):
            result = await endpoints._sync_lark_doc_edit("doc_1", editor="ou_1", source="unit_test")

        self.assertFalse(result["success"])
        self.assertEqual(doc.version, 1)


if __name__ == "__main__":
    unittest.main()
