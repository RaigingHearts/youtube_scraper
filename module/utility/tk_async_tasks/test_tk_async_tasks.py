"""Tests for GUI requests, worker lifecycle, and progress aggregation."""

import queue
import threading
import unittest
from unittest.mock import patch

from module.utility.tk_async_tasks import tk_async_tasks


class GuiRequestTests(unittest.TestCase):
    def test_request_id_is_generated_and_unique(self):
        first = tk_async_tasks.GuiRequest(kind="progress")
        second = tk_async_tasks.GuiRequest(kind="notification")

        self.assertTrue(first.request_id)
        self.assertTrue(second.request_id)
        self.assertNotEqual(first.request_id, second.request_id)

    def test_default_payload_is_not_shared_between_requests(self):
        first = tk_async_tasks.GuiRequest(kind="notification")
        second = tk_async_tasks.GuiRequest(kind="notification")

        first.payload["message"] = "first"

        self.assertEqual(second.payload, {})

    def test_confirmation_requests_have_independent_events(self):
        first = tk_async_tasks.GuiRequest(kind="confirmation")
        second = tk_async_tasks.GuiRequest(kind="confirmation")

        self.assertIsNotNone(first.response_event)
        self.assertIsNotNone(second.response_event)
        self.assertIsNot(first.response_event, second.response_event)
        self.assertFalse(first.response_event.is_set())
        self.assertFalse(second.response_event.is_set())
        self.assertIsNone(first.response)
        self.assertFalse(first.answered)
        self.assertIsNone(first.response_reason)

    def test_non_confirmation_request_does_not_create_response_event(self):
        request = tk_async_tasks.GuiRequest(kind="progress")

        self.assertIsNone(request.response_event)


class WorkerHandleTests(unittest.TestCase):
    def test_initial_state_matches_worker_contract(self):
        handle = tk_async_tasks.WorkerHandle(gui_request_queue=queue.Queue())

        self.assertIsNone(handle.thread)
        self.assertFalse(handle.cancel_event.is_set())
        self.assertFalse(handle.done_event.is_set())
        self.assertFalse(handle.shutdown_decision_event.is_set())
        self.assertIsNone(handle.result)
        self.assertIsNone(handle.exception)
        self.assertIsNone(handle.latest_progress)
        self.assertIsNone(handle.cancel_reason)
        self.assertEqual(handle.partial_result, {"saved_files": []})
        self.assertEqual(handle.pending_confirmations, {})
        self.assertFalse(handle.progress_marker_queued)
        self.assertFalse(handle.shutdown_pending)
        self.assertFalse(handle.save_started)

    def test_synchronization_objects_and_mutable_state_are_not_shared(self):
        first = tk_async_tasks.WorkerHandle(gui_request_queue=queue.Queue())
        second = tk_async_tasks.WorkerHandle(gui_request_queue=queue.Queue())

        self.assertIsNot(first.cancel_event, second.cancel_event)
        self.assertIsNot(first.done_event, second.done_event)
        self.assertIsNot(first.shutdown_decision_event, second.shutdown_decision_event)
        self.assertIsNot(first.progress_lock, second.progress_lock)
        self.assertIsNot(first.confirmation_lock, second.confirmation_lock)
        self.assertIsNot(first.shutdown_lock, second.shutdown_lock)
        self.assertIsNot(first.partial_result, second.partial_result)
        self.assertIsNot(first.partial_result["saved_files"], second.partial_result["saved_files"])
        self.assertIsNot(first.pending_confirmations, second.pending_confirmations)

        first.partial_result["saved_files"].append({"kind": "comments"})
        first.pending_confirmations["request"] = object()
        first.cancel_event.set()

        self.assertEqual(second.partial_result, {"saved_files": []})
        self.assertEqual(second.pending_confirmations, {})
        self.assertFalse(second.cancel_event.is_set())


class ProgressAggregationTests(unittest.TestCase):
    def setUp(self):
        self.request_queue = queue.Queue()
        self.handle = tk_async_tasks.WorkerHandle(
            gui_request_queue=self.request_queue
        )

    def test_multiple_updates_are_coalesced_into_one_queue_marker(self):
        self.handle.publish_progress({"current": 1})
        self.handle.publish_progress({"current": 2})
        self.handle.publish_progress({"current": 3})

        self.assertEqual(self.request_queue.qsize(), 1)
        request = self.request_queue.get_nowait()
        self.assertEqual(request.kind, "progress")
        self.assertEqual(self.handle.take_latest_progress(), {"current": 3})
        self.assertFalse(self.handle.progress_marker_queued)

    def test_new_update_after_marker_consumption_queues_another_marker(self):
        self.handle.publish_progress({"current": 1})
        first_marker = self.request_queue.get_nowait()
        self.assertEqual(first_marker.kind, "progress")

        self.assertEqual(self.handle.take_latest_progress(), {"current": 1})

        self.handle.publish_progress({"current": 2})

        self.assertEqual(self.request_queue.qsize(), 1)
        second_marker = self.request_queue.get_nowait()
        self.assertEqual(second_marker.kind, "progress")
        self.assertEqual(self.handle.take_latest_progress(), {"current": 2})

    def test_take_latest_progress_returns_none_when_no_value_exists(self):
        self.assertIsNone(self.handle.take_latest_progress())
        self.assertFalse(self.handle.progress_marker_queued)

    def test_concurrent_updates_keep_one_marker_and_a_valid_latest_value(self):
        worker_count = 5
        barrier = threading.Barrier(worker_count + 1)
        values = [{"current": index} for index in range(worker_count)]
        workers = []

        def publish(value):
            barrier.wait(timeout=2)
            self.handle.publish_progress(value)

        for value in values:
            worker = threading.Thread(target=publish, args=(value,))
            workers.append(worker)
            worker.start()

        barrier.wait(timeout=2)
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

        self.assertEqual(self.request_queue.qsize(), 1)
        self.assertIn(self.handle.latest_progress, values)
        marker = self.request_queue.get_nowait()
        self.assertEqual(marker.kind, "progress")
        self.assertIn(self.handle.take_latest_progress(), values)


class RunTaskInThreadTests(unittest.TestCase):
    def _join_worker(self, handle):
        handle.thread.join(timeout=2)
        self.assertFalse(handle.thread.is_alive(), "worker thread did not finish")

    def test_worker_receives_handle_arguments_and_runs_on_named_background_thread(self):
        request_queue = queue.Queue()
        started = threading.Event()
        release = threading.Event()
        observed = {}

        def task(handle, positional, keyword=None):
            observed["handle"] = handle
            observed["positional"] = positional
            observed["keyword"] = keyword
            observed["thread_id"] = threading.get_ident()
            observed["thread_name"] = threading.current_thread().name
            started.set()
            if not release.wait(timeout=2):
                raise RuntimeError("test did not release worker")
            return {"result": "complete"}

        handle = tk_async_tasks.run_task_in_thread(
            task, request_queue, "argument", keyword="value"
        )

        try:
            self.assertTrue(started.wait(timeout=2))
            self.assertIs(observed["handle"], handle)
            self.assertIs(handle.gui_request_queue, request_queue)
            self.assertEqual(observed["positional"], "argument")
            self.assertEqual(observed["keyword"], "value")
            self.assertNotEqual(observed["thread_id"], threading.get_ident())
            self.assertEqual(observed["thread_name"], "youtube-scraper-worker")
        finally:
            release.set()
            self._join_worker(handle)

        self.assertEqual(handle.result, {"result": "complete"})
        self.assertIsNone(handle.exception)
        self.assertTrue(handle.done_event.is_set())

    def test_worker_exception_is_retained_and_done_event_is_set(self):
        def task(_handle):
            raise ValueError("worker failed")

        with self.assertLogs(tk_async_tasks.logger, level="ERROR") as captured:
            handle = tk_async_tasks.run_task_in_thread(task, queue.Queue())
            self._join_worker(handle)

        self.assertIsNone(handle.result)
        self.assertIsInstance(handle.exception, ValueError)
        self.assertEqual(str(handle.exception), "worker failed")
        self.assertTrue(handle.done_event.is_set())
        self.assertIn("worker failed", "\n".join(captured.output))

    def test_non_queue_argument_is_rejected_before_thread_creation(self):
        with patch.object(tk_async_tasks.threading, "Thread") as thread_class:
            with self.assertRaises(TypeError):
                tk_async_tasks.run_task_in_thread(lambda _handle: None, object())

        thread_class.assert_not_called()

    def test_thread_start_failure_is_propagated_and_marks_handle_done(self):
        original_worker_handle = tk_async_tasks.WorkerHandle
        created_handles = []

        def create_handle(*args, **kwargs):
            handle = original_worker_handle(*args, **kwargs)
            created_handles.append(handle)
            return handle

        with patch.object(
            tk_async_tasks, "WorkerHandle", side_effect=create_handle
        ):
            with patch.object(
                tk_async_tasks.threading.Thread,
                "start",
                side_effect=RuntimeError("thread start failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "thread start failed"):
                    tk_async_tasks.run_task_in_thread(
                        lambda _handle: None, queue.Queue()
                    )

        self.assertEqual(len(created_handles), 1)
        handle = created_handles[0]
        self.assertIsNotNone(handle.thread)
        self.assertTrue(handle.done_event.is_set())
        self.assertIsNone(handle.exception)
        self.assertIsNone(handle.result)


if __name__ == "__main__":
    unittest.main()
