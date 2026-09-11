// Real WebSocket API example; not live-tested. Install dependency: npm install ws
// No client tools: demonstrates only accepted -> successor -> completed.
import WebSocket from "ws";
if (!process.env.OPENAI_API_KEY) throw Error("Set OPENAI_API_KEY privately in your environment");
const socket = new WebSocket("wss://api.openai.com/v1/responses", {
  headers: {Authorization: `Bearer ${process.env.OPENAI_API_KEY}`},
  handshakeTimeout: 10000,
});
let parent;
let successor;
let finished = false;
const timeout = setTimeout(() => fail("timed out; acceptance outcome may be unknown"), 120000);
function fail(reason) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  console.error(reason);
  process.exitCode = 1;
  socket.close();
}
socket.on("open", () => socket.send(JSON.stringify({
  type: "response.create", model: "gpt-6-astra",
  input: "为面试练习设计一个任务管理工具，列出功能和交付计划。",
})));
socket.on("error", error => fail(error.message));
socket.on("close", () => {if (!finished) fail("Connection ended before successor completion");});
socket.on("message", raw => {
  try {
    const event = JSON.parse(raw.toString());
    if (event.type === "response.created") {
      if (!parent) {
        parent = event.response.id;
        socket.send(JSON.stringify({type: "response.steer", previous_response_id: parent,
          input: "新增约束：一个人两天完成，只保留最小功能。"}));
      } else {
        successor = event.response.id;
        console.log("steering committed to successor", successor);
      }
    } else if (event.type === "response.steer.accepted") {
      console.log("queued, not yet applied", event.steer.id);
    } else if (["response.steer.failed", "response.failed", "error"].includes(event.type)) {
      fail(JSON.stringify(event));
    } else if (event.type === "response.steer.pending") {
      fail("Unexpected pending in no-tool demo; a tool-enabled client must fill required_input using saved results");
    } else if (event.type === "response.incomplete" &&
        !(event.response.id === parent && event.response.incomplete_details?.reason === "steered")) {
      fail("Unexpected incomplete response");
    } else if (event.type === "response.completed" && event.response.id === successor) {
      for (const item of event.response.output) if (item.type === "message")
        for (const part of item.content) console.log(part.text ?? part.refusal ?? "");
      finished = true;
      clearTimeout(timeout);
      socket.close();
    }
  } catch (error) {fail(error.message);}
});
