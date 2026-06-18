#!/usr/bin/env bash
# 一键把本地 masanduo 挂件 + api/app.py 部署到测试服并重启服务。
#
# 用法（在 rag-chatbot 目录下执行）：
#   SSHPASS='服务器root密码' ./deploy_masanduo.sh
#
# 依赖：本机需有 sshpass（mac: brew install hudochenkov/sshpass/sshpass）。
# 没装 sshpass 也行，把下面 SSHPASS_CMD 留空，会改成每步手动输密码。

set -euo pipefail

HOST="root@47.110.33.91"
REMOTE_DIR="/root/ragchatbot"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20"

if command -v sshpass >/dev/null 2>&1 && [ -n "${SSHPASS:-}" ]; then
  SSHPASS_CMD="sshpass -e"
else
  SSHPASS_CMD=""   # 没有 sshpass：scp/ssh 会逐步提示输入密码
  echo "[提示] 未用 sshpass，接下来每步会让你输服务器密码。"
fi

echo "==> 1/4 备份服务器 app.py"
$SSHPASS_CMD ssh $SSH_OPTS "$HOST" \
  "cp $REMOTE_DIR/api/app.py $REMOTE_DIR/api/app.py.bak.\$(date +%Y%m%d_%H%M%S)"

echo "==> 2/4 上传 masanduo 子包 + app.py"
rm -rf src/chatbot/masanduo/__pycache__
$SSHPASS_CMD scp -r $SSH_OPTS src/chatbot/masanduo "$HOST:$REMOTE_DIR/src/chatbot/"
$SSHPASS_CMD scp $SSH_OPTS api/app.py "$HOST:$REMOTE_DIR/api/app.py"

echo "==> 3/4 重启服务 (systemd)"
$SSHPASS_CMD ssh $SSH_OPTS "$HOST" "systemctl restart ragchatbot.service && sleep 6 && systemctl is-active ragchatbot.service"

echo "==> 4/4 冒烟测试"
curl -s -m 30 -X POST http://47.110.33.91/v1/qa \
  -H "Content-Type: application/json" \
  -d '{"question":"16pm回收多少"}'
echo
echo "==> 部署完成。"
