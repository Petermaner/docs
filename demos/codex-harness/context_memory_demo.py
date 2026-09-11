"""Original SQLite history/window/memory example; all inputs are fictional."""
import json
import sqlite3


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS history(
          id INTEGER PRIMARY KEY, thread TEXT, unit TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS evidence(
          source TEXT PRIMARY KEY, project TEXT, key TEXT, value TEXT,
          observed INTEGER, confirmed INTEGER, revoked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS memory(
          project TEXT, key TEXT, value TEXT, source TEXT, observed INTEGER,
          PRIMARY KEY(project,key));
        """)

    def append_unit(self, thread, unit, messages):
        # A unit contains a complete interaction, including call + output.
        calls = {m["call_id"] for m in messages if m["type"] == "function_call"}
        outputs = {m["call_id"] for m in messages if m["type"] == "function_call_output"}
        if calls != outputs:
            raise ValueError("unpaired tool interaction")
        with self.db:
            self.db.execute("INSERT INTO history(thread,unit,body) VALUES(?,?,?)",
                            (thread, unit, json.dumps(messages, ensure_ascii=False)))

    def window(self, thread, goal, keep_units=2):
        if keep_units < 1:
            raise ValueError("keep_units must be positive")
        rows = list(self.db.execute("SELECT * FROM history WHERE thread=? ORDER BY id DESC LIMIT ?", (thread, keep_units)))
        return {"pinned_goal": goal, "recent_units": [json.loads(r["body"]) for r in reversed(rows)]}

    def search(self, thread, term):
        if not term:
            raise ValueError("empty search")
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM history WHERE thread=? AND instr(lower(body),lower(?))>0 ORDER BY id LIMIT 5", (thread, term))]

    def add_evidence(self, source, project, key, value, observed, confirmed):
        with self.db:
            self.db.execute("INSERT INTO evidence(source,project,key,value,observed,confirmed) VALUES(?,?,?,?,?,?)",
                            (source, project, key, value, observed, int(confirmed)))

    def revoke(self, source):
        with self.db:
            self.db.execute("UPDATE evidence SET revoked=1 WHERE source=?", (source,))

    def consolidate(self):
        # Small teaching version: deterministic extraction, single writer,
        # full rebuild. Not Codex's model-based leased two-phase pipeline.
        winners = {}
        rows = self.db.execute("SELECT * FROM evidence WHERE confirmed=1 AND revoked=0 ORDER BY observed,source")
        for row in rows:
            winners[(row["project"], row["key"])] = row
        # All-or-nothing replacement of the materialized memory view.
        with self.db:
            self.db.execute("DELETE FROM memory")
            self.db.executemany("INSERT INTO memory VALUES(?,?,?,?,?)", [
                (r["project"], r["key"], r["value"], r["source"], r["observed"])
                for r in winners.values()])

    def recall(self, project, now, max_age=30):
        return [{**dict(r), "needs_refresh": now-r["observed"] > max_age}
                for r in self.db.execute("SELECT * FROM memory WHERE project=? ORDER BY key", (project,))]


def main():
    store = Store()
    try:
        store.append_unit("a", "u1", [{"type": "message", "text": "错误码 E42 是旧登录模块的故障"}])
        store.append_unit("a", "u2", [
            {"type": "function_call", "call_id": "c1", "name": "test"},
            {"type": "function_call_output", "call_id": "c1", "output": "failed"}])
        store.append_unit("a", "u3", [{"type": "message", "text": "当前目标：只读诊断"}])
        print("当前窗口:", json.dumps(store.window("a", "只读诊断"), ensure_ascii=False))
        print("历史召回:", store.search("a", "E42"))
        store.add_evidence("rollout-1", "project-A", "jdk", "8", 1, True)
        store.add_evidence("rollout-2", "project-A", "jdk", "17", 10, True)
        store.add_evidence("web-guess", "project-A", "jdk", "99", 11, False)
        store.consolidate()
        print("长期记忆:", store.recall("project-A", now=50))
        store.revoke("rollout-2")
        store.consolidate()
        print("撤回来源后:", store.recall("project-A", now=50))
    finally:
        store.db.close()


if __name__ == "__main__":
    main()
