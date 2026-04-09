# API 上线配置指南

## 当前服务器状态

| 服务 | 端口 | 状态 | 说明 |
|------|------|------|------|
| 旧 API (Docker `rag_api`) | 80 | unhealthy | 旧版本，需要停掉 |
| 新 API (uvicorn 直连) | 8000 | running | 新版本，已完成 embedding |
| Milvus (Docker) | - | running | 旧 Docker 用的，新版用 milvus.db |
| Ollama (Docker) | - | running | 可选保留 |

## 一、替换旧 API

### 1. 停掉旧 Docker API 容器

```bash
docker stop rag_api && docker rm rag_api
echo "旧 API 已停止，端口 80 已释放"
```

### 2. 停掉当前 8000 端口的新 API

```bash
kill $(pgrep uvicorn) 2>/dev/null; sleep 2
```

### 3. 用 port 80 启动新 API（替代旧版）

```bash
source /root/miniconda3/bin/activate rag && cd /root/ragchatbot

nohup bash -c '
export HF_ENDPOINT=https://hf-mirror.com
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
PYTHONPATH=/root/ragchatbot/src uvicorn api.app:app --host 0.0.0.0 --port 80
' > /root/ragchatbot/api.log 2>&1 &

echo "新 API 已启动在 port 80"
echo "Monitor: tail -f /root/ragchatbot/api.log"
```

### 4. 验证

```bash
# 健康检查
curl http://localhost/healthz
# 预期: {"ok":true}

# 非流式问答
curl -X POST http://localhost/v1/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "怎么退款？", "top_k": 5}'

# 流式问答 (SSE)
curl -X POST http://localhost/v1/qa/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "iphone16怎么租", "top_k": 5}'
```

### 5. 外部访问验证

```bash
# 从任何外部机器
curl http://47.110.33.91/healthz

curl -X POST http://47.110.33.91/v1/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "怎么退款？"}'

curl -X POST http://47.110.33.91/v1/qa/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "iphone16怎么租"}'
```

> 确保阿里云安全组已放行 80 端口（HTTP 默认端口，一般已开放）。

---

## 二、API 接口说明

### `POST /v1/qa` — 非流式问答

**请求：**
```json
{
  "question": "怎么退款？",
  "top_k": 5,
  "session_id": "user-123",
  "filters": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | 是 | 用户问题 |
| top_k | int | 否 | 检索条数，默认 5，最大 50 |
| session_id | string | 否 | 会话ID，用于日志追踪 |
| filters | object | 否 | 过滤条件 |

**响应：**
```json
{
  "answer": "退款需要联系客服申请取消...",
  "citations": [
    {
      "source": "data/shangwu11to03.xlsx",
      "score": 0.796,
      "table": "",
      "pk": null,
      "title": null
    }
  ],
  "trace_id": "c16df090-...",
  "performance_metrics": {
    "t_embed_query_s": 0.05,
    "t_retrieve_s": 0.02,
    "t_llm_total_s": 1.6,
    "context_count": 5
  }
}
```

### `POST /v1/qa/stream` — 流式问答 (SSE)

**请求格式同上。**

**响应：** Server-Sent Events 流，包含三类事件：

```
event: start
data: {"trace_id":"xxx","citations":[...],"context_count":5}

event: chunk
data: {"content":"退款"}

event: chunk
data: {"content":"需要"}

event: chunk
data: {"content":"联系客服..."}

event: done
data: {"performance_metrics":{...}}
```

| 事件 | 说明 |
|------|------|
| `start` | 检索完成，返回 citations 和 trace_id |
| `chunk` | LLM 逐字输出，前端拼接 content 即可实时显示 |
| `done` | 生成结束，返回性能指标 |
| `error` | 出错时返回错误详情 |

**前端对接示例（JavaScript）：**
```javascript
const response = await fetch('http://47.110.33.91/v1/qa/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ question: 'iphone16怎么租', top_k: 5 })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let answer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const text = decoder.decode(value);
  for (const line of text.split('\n')) {
    if (line.startsWith('data: ')) {
      const data = JSON.parse(line.slice(6));
      if (data.content) {
        answer += data.content;
        console.log('当前回答:', answer);  // 实时更新UI
      }
    }
  }
}
```

---

## 三、一键替换命令（整合版）

直接粘贴到服务器，一步到位：

```bash
# 停旧启新
docker stop rag_api 2>/dev/null; docker rm rag_api 2>/dev/null
kill $(pgrep uvicorn) 2>/dev/null
sleep 2

# 启动新 API（port 80，GPU 加速）
source /root/miniconda3/bin/activate rag && cd /root/ragchatbot
nohup bash -c '
export HF_ENDPOINT=https://hf-mirror.com
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
PYTHONPATH=/root/ragchatbot/src uvicorn api.app:app --host 0.0.0.0 --port 80
' > /root/ragchatbot/api.log 2>&1 &

echo "API started on port 80, PID: $!"
echo "等待模型加载（首次约 20s）..."
sleep 3 && curl -s http://localhost/healthz && echo " OK"
```

---

## 四、运维

### 重启 API

```bash
kill $(pgrep uvicorn) 2>/dev/null; sleep 2
source /root/miniconda3/bin/activate rag && cd /root/ragchatbot
nohup bash -c '
export HF_ENDPOINT=https://hf-mirror.com
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
PYTHONPATH=/root/ragchatbot/src uvicorn api.app:app --host 0.0.0.0 --port 80
' > /root/ragchatbot/api.log 2>&1 &
```

### 设置开机自启（systemd）

```bash
cat > /etc/systemd/system/ragchatbot.service << 'EOF'
[Unit]
Description=RAG Chatbot API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/ragchatbot
Environment="HF_ENDPOINT=https://hf-mirror.com"
Environment="PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
Environment="PYTHONPATH=/root/ragchatbot/src"
ExecStart=/root/miniconda3/envs/rag/bin/uvicorn api.app:app --host 0.0.0.0 --port 80
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ragchatbot
systemctl start ragchatbot
systemctl status ragchatbot
```

使用 systemd 后，管理命令变为：
```bash
systemctl restart ragchatbot   # 重启
systemctl stop ragchatbot      # 停止
journalctl -u ragchatbot -f    # 查看日志
```

### 查看日志

```bash
tail -f /root/ragchatbot/api.log
```

### GPU 监控

```bash
nvidia-smi  # 首次请求后应看到 ~16GB 显存占用
```

---

## 五、技术架构

```
用户请求
  │
  ▼
[POST /v1/qa 或 /v1/qa/stream]  ← port 80
  │
  ▼
[Query Planner] → 自适应：高分直接返回，低分走 LLM 改写
  │
  ▼
[Embedding] → Qwen3-Embedding-8B (fp16, NVIDIA A10 GPU)
  │
  ▼
[Vector Search] → Milvus Lite (43,269 vectors, 4096维)
  │
  ▼
[Prompt Build] → 注入 top-K 上下文 + 强制中文回答
  │
  ▼
[LLM Generate] → DeepSeek API (deepseek-chat)
  │
  ▼
返回 JSON / SSE Stream
```

## 六、当前数据

| 数据源 | 类型 | 数量 |
|--------|------|------|
| shangwu11to03.xlsx | 客服对话 | 43,259 chunks |
| 知识库.md | 知识文档 | 10 chunks |
| **总计** | | **43,269 vectors** |

向量数据库：`/root/ragchatbot/milvus.db`（724MB）
