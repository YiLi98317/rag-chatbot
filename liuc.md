部署结果（已上线，可直接用）
服务器 47.110.33.91 上跑的是你的 rag-chatbot 主项目（FastAPI api.app:app，端口 80，systemd 服务 ragchatbot）。我做的：

把 masanduo 挂件传上去：/root/ragchatbot/src/chatbot/masanduo/（含 5 个数据文件）。
把 /v1/qa 接口改走 masanduo 引擎（前端 AiChat 调的就是这个）。业务问题（回收价/算租机/复合/红线/办单…）走马三多工作流，闲聊走快速人设，未命中才回落原 RAG。前端一行没改。
修了一个老毛病：systemd 服务其实从 4 月起一直起不来——一个手工启动的老 uvicorn 占着 80 端口，导致 systemd 撞端口失败重启了 56 万次。我杀掉老进程后，systemd 正常接管，现在服务归 systemd 管了。
线上实测全部正常（公网可达）：

能套机吗 → 红线固定文案（秒回，不烧 token）
16pm回收多少 → 回收价表
5000 5折 12期 → 租机方案表（750/5800/2500/300，数字对）
怎么办单 → 6 步流程
你好 → 快速人设回复（约几秒，远低于前端 50s 超时）
你以后怎么换代码（不用宝塔）
我在仓库根目录放了个一键脚本 deploy_masanduo.sh。改完本地代码后，在 rag-chatbot 目录下跑：

SSHPASS='你的服务器root密码' ./deploy_masanduo.sh
它会自动：备份服务器 app.py → 上传 masanduo 子包和 app.py → systemctl restart ragchatbot → 冒烟测一条。

需要先装 sshpass：brew install hudochenkov/sshpass/sshpass。不装也行，脚本会改成每步让你手输密码。

手动版（不想用脚本时）两条命令也够：

scp -r src/chatbot/masanduo api/app.py root@47.110.33.91:/root/ragchatbot/... # 传文件
ssh root@47.110.33.91 'systemctl restart ragchatbot' # 重启
重启/排错常用命令（SSH 上去后）：

systemctl restart ragchatbot # 重启
systemctl status ragchatbot # 看状态
journalctl -u ragchatbot -n 50 # 看日志
两个提醒
回滚：我备份了原接口为 api/app.py.bak.20260618_150148，要回退把它拷回 api/app.py 再 restart 即可。
安全（重要）：同事原 masanduo_624 里那个明文 DeepSeek 密钥 sk-da10cc... 已进过 git，建议去 DeepSeek 后台吊销重发。另外服务器是 root + 弱口令直连公网，测试服无所谓，真上线前建议换密钥登录、关 80 直连。
需要的话，下一步可以让前端带上 session_id（这样复合推演就能跨轮记住旧机/预算），或给挂件单独开个 /v1/masanduo 接口跟纯 RAG 并存。
