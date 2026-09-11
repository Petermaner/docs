"""Original teaching runtime. No LLM, network, shell execution, or Codex dependency."""
import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field


class Journal:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, thread TEXT, kind TEXT, payload TEXT)")

    def append(self, thread, kind, **payload):
        with self.db:
            cur = self.db.execute("INSERT INTO events(thread,kind,payload) VALUES(?,?,?)",
                                  (thread, kind, json.dumps(payload, ensure_ascii=False)))
        return cur.lastrowid

    def replay(self, thread, after=0):
        rows = self.db.execute("SELECT seq,kind,payload FROM events WHERE thread=? AND seq>? ORDER BY seq", (thread, after))
        return [{"seq": s, "kind": k, **json.loads(p)} for s, k, p in rows]


@dataclass
class Turn:
    id: str
    revision: int = 0
    state: str = "running"
    updates: list = field(default_factory=list)


@dataclass
class Job:
    thread: str
    turn: str
    revision: int
    signature: str
    task: asyncio.Task


class Runtime:
    def __init__(self, journal=None, concurrency=2):
        self.journal = journal or Journal()
        self.turns = {}
        self.jobs = {}
        self.slots = asyncio.Semaphore(concurrency)

    def start(self, thread):
        old = self.turns.get(thread)
        if old and old.state == "running":
            raise ValueError("thread already has an active turn")
        turn = Turn(uuid.uuid4().hex)
        self.turns[thread] = turn
        self.journal.append(thread, "turn.started", turn_id=turn.id)
        return turn.id

    def active(self, thread, expected):
        turn = self.turns[thread]
        if turn.id != expected or turn.state != "running":
            raise ValueError("stale or inactive turn")
        return turn

    def steer(self, thread, expected, text):
        turn = self.active(thread, expected)
        turn.revision += 1
        turn.updates.append(text)
        self.journal.append(thread, "steer.accepted", revision=turn.revision, text=text)
        return turn.revision

    def launch(self, thread, expected, call_id, name, args, timeout=1):
        turn = self.active(thread, expected)
        if name not in {"read_docs", "run_tests", "fail"}:
            raise ValueError("tool not allowed")
        delay = args.get("delay", 0.01)
        if type(delay) not in (int, float) or not 0 <= delay <= 2:
            raise ValueError("invalid delay")
        signature = json.dumps([name, args], sort_keys=True)
        key = (thread, expected, call_id)
        if key in self.jobs:
            if self.jobs[key].signature != signature:
                raise ValueError("call_id reused with different arguments")
            return key
        revision = turn.revision

        async def execute():
            try:
                # Timeout includes queue time. Demo tools are cancellable coroutines.
                async with asyncio.timeout(timeout):
                    async with self.slots:
                        self.journal.append(thread, "tool.started", call_id=call_id)
                        await asyncio.sleep(delay)
                        if name == "fail":
                            raise RuntimeError("synthetic tool error")
                        value = {"source": "synthetic fixture", "tool": name, "revision": revision}
                        self.journal.append(thread, "tool.completed", call_id=call_id)
                        return {"ok": True, "value": value}
            except TimeoutError:
                self.journal.append(thread, "tool.timeout", call_id=call_id)
                return {"ok": False, "error": "timeout"}
            except asyncio.CancelledError:
                self.journal.append(thread, "tool.cancelled", call_id=call_id)
                raise
            except Exception as exc:
                self.journal.append(thread, "tool.failed", call_id=call_id)
                return {"ok": False, "error": str(exc)}

        self.jobs[key] = Job(thread, expected, revision, signature, asyncio.create_task(execute()))
        return key

    async def result(self, thread, expected, key):
        self.active(thread, expected)
        job = self.jobs[key]
        if (job.thread, job.turn) != (thread, expected):
            raise PermissionError("job belongs to another thread or turn")
        value = await asyncio.shield(job.task)
        current = self.active(thread, expected)
        return {**value, "stale": job.revision != current.revision, "call_id": key[2]}

    def commit(self, thread, expected, revision, proposal):
        turn = self.active(thread, expected)
        if revision != turn.revision:
            raise ValueError("proposal predates user update; revalidate first")
        # Records a proposal only; does not authorize or perform external writes.
        self.journal.append(thread, "proposal.committed", revision=revision, proposal=proposal)

    async def cancel(self, thread, expected):
        turn = self.active(thread, expected)
        turn.state = "cancelled"
        tasks = [j.task for j in self.jobs.values() if (j.thread, j.turn) == (thread, expected)]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.journal.append(thread, "turn.cancelled", turn_id=expected)

    async def close(self):
        tasks = [j.task for j in self.jobs.values()]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.journal.db.close()


async def main():
    started = time.perf_counter()
    runtime = Runtime()
    try:
        turn = runtime.start("demo")
        docs = runtime.launch("demo", turn, "call-docs", "read_docs", {"delay": 0.08})
        tests = runtime.launch("demo", turn, "call-tests", "run_tests", {"delay": 0.12})
        # Scripted stand-in for independent model work, not actual inference.
        await asyncio.sleep(0.02)
        runtime.journal.append("demo", "independent.work", text="先整理验收清单")
        runtime.steer("demo", turn, "只给修复方案，不修改文件")
        results = await asyncio.gather(runtime.result("demo", turn, docs), runtime.result("demo", turn, tests))
        try:
            runtime.commit("demo", turn, 0, "旧方案")
        except ValueError as exc:
            print("旧方案被拒绝:", exc)
        runtime.commit("demo", turn, 1, "已按最新要求重新检查的只读方案")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(runtime.journal.replay("demo"), ensure_ascii=False, indent=2))
        print(f"elapsed={time.perf_counter()-started:.3f}s (synthetic, not a Codex benchmark)")
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
