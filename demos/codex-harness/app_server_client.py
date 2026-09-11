"""Real Codex stdio protocol probe. Creates no thread and calls no model."""
import asyncio
import json


class RpcClient:
    def __init__(self, process):
        self.process = process
        self.pending = {}
        self.notifications = asyncio.Queue(maxsize=256)
        self.serial = 0
        self.reader = asyncio.create_task(self.read_loop())

    async def send(self, message):
        self.process.stdin.write((json.dumps(message)+"\n").encode())
        await self.process.stdin.drain()

    async def read_loop(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message and "id" in message:
                    # Fail closed: this probe has no permission/approval UI.
                    await self.send({"id": message["id"], "error": {
                        "code": -32601, "message": "Probe cannot handle server requests"}})
                elif "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(RuntimeError(str(message["error"])))
                        else:
                            future.set_result(message.get("result"))
                else:
                    # Do not silently discard events when the consumer is slow.
                    self.notifications.put_nowait(message)
        except Exception as exc:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(exc)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("app-server stream ended"))

    async def call(self, method, params):
        self.serial += 1
        request_id = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, 15)
        finally:
            self.pending.pop(request_id, None)

    async def close(self):
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        await self.reader


async def main():
    process = await asyncio.create_subprocess_exec(
        "codex", "app-server", "--listen", "stdio://",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    client = RpcClient(process)
    try:
        result = await client.call("initialize", {
            "clientInfo": {"name": "interview_probe", "title": "Interview Probe", "version": "0.1.0"}})
        await client.send({"method": "initialized", "params": {}})
        print("initialize succeeded; returned keys:", sorted(result))
        print("No thread or model request was created.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
