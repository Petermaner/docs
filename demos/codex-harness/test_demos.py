import asyncio
import tempfile
import unittest
from pathlib import Path
from runtime_demo import Journal, Runtime
from context_memory_demo import Store


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.r = Runtime()
        self.t = self.r.start("a")

    async def asyncTearDown(self):
        await self.r.close()

    async def test_steering_fences_stale_commit(self):
        key = self.r.launch("a", self.t, "c", "read_docs", {"delay": 0.01})
        self.r.steer("a", self.t, "read only")
        result = await self.r.result("a", self.t, key)
        self.assertTrue(result["stale"])
        with self.assertRaises(ValueError):
            self.r.commit("a", self.t, 0, "old")
        self.r.commit("a", self.t, 1, "revalidated")

    async def test_idempotency_and_argument_collision(self):
        key = self.r.launch("a", self.t, "c", "read_docs", {})
        self.assertEqual(key, self.r.launch("a", self.t, "c", "read_docs", {}))
        with self.assertRaises(ValueError):
            self.r.launch("a", self.t, "c", "run_tests", {})
        await self.r.result("a", self.t, key)
        self.assertEqual(sum(e["kind"] == "tool.started" for e in self.r.journal.replay("a")), 1)

    async def test_owner_isolation(self):
        other = self.r.start("b")
        key = self.r.launch("a", self.t, "c", "read_docs", {})
        with self.assertRaises(PermissionError):
            await self.r.result("b", other, key)

    async def test_timeout_and_failure(self):
        slow = self.r.launch("a", self.t, "s", "read_docs", {"delay": 0.2}, timeout=0.01)
        failed = self.r.launch("a", self.t, "f", "fail", {})
        self.assertEqual((await self.r.result("a", self.t, slow))["error"], "timeout")
        self.assertFalse((await self.r.result("a", self.t, failed))["ok"])

    async def test_cancel_and_stale_turn(self):
        key = self.r.launch("a", self.t, "c", "read_docs", {"delay": 0.2})
        await asyncio.sleep(0)
        await self.r.cancel("a", self.t)
        self.assertTrue(self.r.jobs[key].task.cancelled())
        with self.assertRaises(ValueError):
            self.r.steer("a", self.t, "too late")

    async def test_real_overlap_without_timing_threshold(self):
        keys = [self.r.launch("a", self.t, str(i), "read_docs", {"delay": 0.02}) for i in range(2)]
        await asyncio.gather(*(self.r.result("a", self.t, k) for k in keys))
        kinds = [e["kind"] for e in self.r.journal.replay("a")]
        second_start = [i for i, k in enumerate(kinds) if k == "tool.started"][1]
        first_end = kinds.index("tool.completed")
        self.assertLess(second_start, first_end)


class StorageTests(unittest.TestCase):
    def test_replay_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d)/"log.db")
            j = Journal(p)
            first = j.append("a", "start")
            j.append("b", "secret")
            j.append("a", "done")
            j.db.close()
            j = Journal(p)
            self.assertEqual([e["kind"] for e in j.replay("a", after=first)], ["done"])
            j.db.close()

    def test_window_keeps_pairs_and_archive(self):
        s = Store()
        try:
            s.append_unit("a", "1", [{"type": "message", "text": "E42"}])
            s.append_unit("a", "2", [{"type": "function_call", "call_id": "x"}, {"type": "function_call_output", "call_id": "x"}])
            self.assertEqual(len(s.window("a", "goal", 1)["recent_units"][0]), 2)
            self.assertEqual(len(s.search("a", "E42")), 1)
            self.assertEqual(s.search("b", "E42"), [])
            with self.assertRaises(ValueError):
                s.append_unit("a", "bad", [{"type": "function_call", "call_id": "x"}])
        finally:
            s.db.close()

    def test_memory_provenance_revocation_and_scope(self):
        s = Store()
        try:
            s.add_evidence("a", "p", "jdk", "8", 1, True)
            s.add_evidence("b", "p", "jdk", "17", 2, True)
            s.add_evidence("c", "p", "jdk", "99", 3, False)
            s.consolidate()
            self.assertEqual(s.recall("p", 40)[0]["value"], "17")
            self.assertTrue(s.recall("p", 40)[0]["needs_refresh"])
            self.assertEqual(s.recall("other", 40), [])
            s.revoke("b")
            s.consolidate()
            self.assertEqual(s.recall("p", 40)[0]["source"], "a")
        finally:
            s.db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
