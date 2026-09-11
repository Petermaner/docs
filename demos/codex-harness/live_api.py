"""Real API examples, NOT executed during tutorial creation. Python stdlib only.
Usage: OPENAI_API_KEY supplied privately in environment; python3 live_api.py MODE
MODE: direct | ptc | async | compact. Requires a permitted gpt-6-astra API model.
"""
import concurrent.futures
import json
import os
import sys
import time
import urllib.request

MODEL = "gpt-6-astra"
INSTRUCTIONS = "数据全是教学 fixture。保留 source。工具失败必须披露，不可编造结果。"


def request(path, payload, stream=False):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("Set OPENAI_API_KEY in your environment; do not paste it into this file.")
    req = urllib.request.Request("https://api.openai.com/v1/"+path,
        data=json.dumps(payload).encode(), headers={
            "Authorization": "Bearer "+key, "Content-Type": "application/json"})
    response = urllib.request.urlopen(req, timeout=120)
    if stream:
        return response
    with response:
        return json.load(response)


def scan(args):
    if set(args) != {"module"} or args["module"] not in {"api", "ui"}:
        raise ValueError("invalid module")
    time.sleep(0.1)  # Synthetic external I/O.
    return {"ok": True, "module": args["module"], "high": 2 if args["module"] == "api" else 0,
            "source": "fictional-fixture-v1", "error": ""}


def output_for(call):
    try:
        if call["name"] != "scan":
            raise ValueError("unknown tool")
        value = scan(json.loads(call["arguments"]))
    except Exception as exc:
        value = {"ok": False, "module": "", "high": 0,
                 "error": str(exc), "source": "local-dispatcher"}
    result = {"type": "function_call_output", "call_id": call["call_id"],
              "output": json.dumps(value)}
    if "caller" in call:
        result["caller"] = call["caller"]  # Required for nested PTC resumption.
    return result


def definition(mode):
    tool = {"type": "function", "name": "scan", "description": "读取指定模块的虚构风险统计。先检查 ok；失败时不可使用 high 作为统计结果。",
            "strict": True, "parameters": {"type": "object", "properties": {
                "module": {"type": "string", "enum": ["api", "ui"]}},
                "required": ["module"], "additionalProperties": False}}
    if mode == "async":
        tool["async"] = True
    if mode == "ptc":
        tool["allowed_callers"] = ["programmatic"]
        tool["output_schema"] = {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "error": {"type": "string"},
            "module": {"type": "string"}, "high": {"type": "integer"},
            "source": {"type": "string"}}, "required": ["ok", "error", "module", "high", "source"],
            "additionalProperties": False}
    return [tool] + ([{"type": "programmatic_tool_calling"}] if mode == "ptc" else [])


def show(response):
    for item in response.get("output", []):
        if item["type"] == "message":
            for part in item["content"]:
                if part["type"] == "output_text":
                    print(part["text"])
                elif part["type"] == "refusal":
                    print("REFUSAL:", part["refusal"])


def checked(response):
    if response.get("status") != "completed":
        raise RuntimeError("Response did not complete: "+str(response.get("status")))


def loop(mode):
    tools = definition(mode)
    history = [{"role": "user", "content": "查 api 和 ui 的虚构风险统计，计算 high 总数并注明来源。"}]
    # Per-run cached results: avoid re-executing duplicate call IDs.
    done = {}
    for _ in range(12):
        response = request("responses", {"model": MODEL, "store": False,
            "input": history, "tools": tools, "instructions": INSTRUCTIONS,
            "include": ["reasoning.encrypted_content"]})
        checked(response)
        history.extend(response["output"])  # Keep program, fingerprint, reasoning, etc.
        calls = [x for x in response["output"] if x["type"] == "function_call"]
        if not calls and any(x["type"] == "message" for x in response["output"]):
            show(response)
            return
        # Serial client dispatch is intentional for this small direct/PTC demo.
        # PTC can request concurrency; this application still owns execution policy.
        for call in calls:
            signature = json.dumps([call["name"], call["arguments"], call.get("caller")], sort_keys=True)
            key = call["call_id"]
            if key in done and done[key][0] != signature:
                raise RuntimeError("call ID collision")
            if key not in done:
                done[key] = (signature, output_for(call))
            history.append(done[key][1])
    raise RuntimeError("Reached demo turn budget")


def events(response):
    data = []
    for raw in response:
        line = raw.decode().rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif line == "" and data:
            text = "\n".join(data)
            data.clear()
            if text != "[DONE]":
                yield json.loads(text)


def async_demo():
    tools = definition("async")
    jobs = {}
    final = None
    # Launch tools as complete call items arrive; don't wait for the entire stream.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        with request("responses", {"model": MODEL, "tools": tools, "stream": True,
            "instructions": INSTRUCTIONS,
            "input": "启动 api 模块查询，同时先解释什么是单元测试；结果到达后再解释风险统计。"}, stream=True) as response:
            for event in events(response):
                if event["type"] == "response.output_item.done":
                    item = event["item"]
                    if item["type"] == "function_call":
                        if not item.get("async"):
                            raise RuntimeError("Expected async call; check model and API support")
                        if item["call_id"] in jobs:
                            raise RuntimeError("Duplicate stream call item; reconcile before retry")
                        jobs[item["call_id"]] = pool.submit(output_for, item)
                elif event["type"] == "response.output_text.delta":
                    print(event["delta"], end="", flush=True)
                elif event["type"] == "response.completed":
                    final = event["response"]
                elif event["type"] in {"response.failed", "response.incomplete", "error"}:
                    raise RuntimeError("Stream failed: "+event["type"])
        if final is None or not jobs:
            raise RuntimeError("No completed response or async call observed")
        # Original call IDs, latest response ID. This demo makes no intermediate turns.
        outputs = [future.result() for future in jobs.values()]
        follow = request("responses", {"model": MODEL, "tools": tools, "tool_choice": "none",
            "instructions": INSTRUCTIONS, "previous_response_id": final["id"], "input": outputs})
        checked(follow)
        print()
        show(follow)


def compact_demo():
    history = [{"role": "user", "content": "项目约束：Python 标准库、只读分析、不要改文件。请复述。"}]
    first = request("responses", {"model": MODEL, "store": False, "input": history,
        "include": ["reasoning.encrypted_content"], "instructions": INSTRUCTIONS})
    checked(first)
    history.extend(first["output"])
    compacted = request("responses/compact", {"model": MODEL, "input": history})
    # Never extract just encrypted_content or prune the compact endpoint's output.
    follow = request("responses", {"model": MODEL, "store": False, "instructions": INSTRUCTIONS,
        "input": [*compacted["output"], {"role": "user", "content": "继续，列出必须遵守的三个约束。"}]})
    checked(follow)
    show(follow)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "help"
    if mode in {"direct", "ptc"}:
        loop(mode)
    elif mode == "async":
        async_demo()
    elif mode == "compact":
        compact_demo()
    else:
        print(__doc__)
