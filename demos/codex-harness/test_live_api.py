"""Offline contract tests with fake responses. Never contacts OpenAI."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
import live_api as api


class ApiContractTests(unittest.TestCase):
    def test_ptc_output_keeps_caller_and_error_shape(self):
        caller = {"type": "program", "caller_id": "program-1"}
        call = {"name": "scan", "call_id": "c1", "arguments": '{"module":"bad"}', "caller": caller}
        out = api.output_for(call)
        self.assertEqual(out["caller"], caller)
        data = json.loads(out["output"])
        self.assertFalse(data["ok"])
        self.assertEqual(set(data), set(api.definition("ptc")[0]["output_schema"]["required"]))

    def test_modes_do_not_mix_async_and_ptc(self):
        self.assertTrue(api.definition("async")[0]["async"])
        self.assertNotIn("allowed_callers", api.definition("async")[0])
        self.assertNotIn("async", api.definition("ptc")[0])

    def test_sse_comments_crlf_multiline_and_done(self):
        wire = b': keepalive\r\ndata: {"type":\r\ndata: "demo"}\r\n\r\ndata: [DONE]\r\n\r\n'
        self.assertEqual(list(api.events(io.BytesIO(wire))), [{"type": "demo"}])

    def test_compact_preserves_all_returned_items(self):
        packed = [{"type": "message", "role": "user", "content": "retained"},
                  {"type": "compaction", "encrypted_content": "opaque"}]
        replies = [{"status": "completed", "output": []}, {"output": packed},
                   {"status": "completed", "output": []}]
        with patch.object(api, "request", side_effect=replies) as mocked:
            api.compact_demo()
        self.assertEqual(mocked.call_args_list[2].args[1]["input"][:-1], packed)

    def test_async_dispatch_before_stream_finishes(self):
        final = {"id": "r1", "status": "completed", "output": []}
        call = {"type": "function_call", "name": "scan", "call_id": "c1",
                "arguments": '{"module":"api"}', "async": True}
        submitted = []

        class ImmediatePool:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def submit(self, fn, item):
                submitted.append(item["call_id"])
                class Future:
                    def result(self):
                        return {"type": "function_call_output", "call_id": "c1", "output": "{}"}
                return Future()

        def stream(_):
            yield {"type": "response.output_item.done", "item": call}
            self.assertEqual(submitted, ["c1"])
            yield {"type": "response.completed", "response": final}

        with patch.object(api, "request", side_effect=[io.BytesIO(), final]) as mocked, \
             patch.object(api, "events", side_effect=stream), \
             patch.object(api.concurrent.futures, "ThreadPoolExecutor", ImmediatePool), \
             contextlib.redirect_stdout(io.StringIO()):
            api.async_demo()
        continuation = mocked.call_args_list[1].args[1]
        self.assertEqual(continuation["previous_response_id"], "r1")
        self.assertEqual(continuation["input"][0]["call_id"], "c1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
