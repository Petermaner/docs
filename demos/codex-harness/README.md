# Codex 与 Harness Demo

这些脚本是教程中的教学实现和协议探测示例。它们不包含 API Key，也不会因为被放入文档仓库就自动执行。

在本目录运行离线 Demo：

```bash
python3 runtime_demo.py
python3 context_memory_demo.py
python3 computer_loop_demo.py
python3 -m unittest test_demos.py
python3 -m unittest test_live_api.py
```

`live_api.py`、`steering_api.mjs` 需要你自行配置凭据或依赖，文档中的命令仅作说明。
