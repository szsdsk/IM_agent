import unittest

from backend.services.sync_service import EventType, SyncService


class SyncServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_sends_flattened_event_to_session_clients(self):
        service = SyncService()
        received = []

        async def send(message):
            received.append(message)

        await service.subscribe("session_1", "client_a", "desktop", send)
        await service.publish(
            EventType.TASK_PROGRESS,
            session_id="session_1",
            task_id="task_1",
            data={"step": "generate_slides", "progress": 0.75},
            persist=False,
        )

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["type"], "task.progress")
        self.assertEqual(received[0]["session_id"], "session_1")
        self.assertEqual(received[0]["task_id"], "task_1")
        self.assertEqual(received[0]["step"], "generate_slides")
        self.assertEqual(received[0]["progress"], 0.75)
        self.assertIn("event_id", received[0])

    async def test_publish_can_exclude_source_client(self):
        service = SyncService()
        received_a = []
        received_b = []

        async def send_a(message):
            received_a.append(message)

        async def send_b(message):
            received_b.append(message)

        await service.subscribe("session_1", "client_a", "desktop", send_a)
        await service.subscribe("session_1", "client_b", "mobile", send_b)
        await service.publish(
            EventType.MESSAGE_CREATED,
            session_id="session_1",
            task_id="task_1",
            source_client_id="client_a",
            exclude_client="client_a",
            data={"role": "user", "content": "hello"},
            persist=False,
        )

        self.assertEqual(received_a, [])
        self.assertEqual(len(received_b), 1)
        self.assertEqual(received_b[0]["source_client_id"], "client_a")


if __name__ == "__main__":
    unittest.main()
