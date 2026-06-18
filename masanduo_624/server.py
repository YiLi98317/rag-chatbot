# -*- coding: utf-8 -*-
"""
马三多 API v6.23 — 纯 Python 直连方案
不依赖 EasyClaw Agent，keyword 匹配 → 直接调工具 → 工具不匹配 → DeepSeek 对话
启动: python server.py
端口: 8899
"""

import json
import os
import re
import sys
import threading
import time
import hashlib
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP Server，兼容 Python 3.6"""
    daemon_threads = True


# 加 tools 目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
from masanduo_tools import query_buyback, calculate_rental, query_inventory_agent
from ecommerce_prompts import flow_ecommerce_assets

# ====== 配置 ======
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
# 直调 DeepSeek 官方 API
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
# 试试 DeepSeek 新版模型（更强的推理）
MODEL = "deepseek-v4-pro"
PORT = 8899

# 人工客服回复（甩给人工客服时用）
HUMAN_AGENT_REPLY = """您好，我是"手机妈妈"的智能助手，不是人工客服。

如果您需要人工客服协助，可以这样联系：
1. 打开手机妈妈 APP，点击【我的】→【联系客服】
2. 或在微信/支付宝搜索"手机妈妈"小程序，进入后联系在线客服

人工客服服务时间：业务顾问团队 8:30-23:30，售后团队 8:30-23:30。"""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ====== 管理后台配置 ======
ADMIN_USER = "admin"
ADMIN_PASS = "masanduo2026"  # 部署时改掉
ADMIN_TOKENS = {}  # token → expiry
ADMIN_TOKEN_TTL = 8 * 3600  # 8小时过期

def _check_admin_auth(handler) -> bool:
    """验证管理后台登录态"""
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        if token in ADMIN_TOKENS and time.time() < ADMIN_TOKENS[token]:
            return True
    return False

def _serve_static(handler, filepath, content_type):
    """返回静态文件"""
    full = os.path.join(BASE_DIR, filepath)
    if not os.path.exists(full):
        handler._json({"code": 404, "error": "Not Found"}, 404)
        return
    with open(full, "r", encoding="utf-8") as f:
        data = f.read()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", len(data.encode("utf-8")))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data.encode("utf-8"))

def _read_json(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 清除 tools 模块缓存，让下次查询读到最新数据
    import importlib
    try:
        mod = sys.modules.get("masanduo_tools")
        if mod and hasattr(mod, "_load_buyback_prices"):
            importlib.reload(mod)
    except:
        pass
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")

# 会话记忆：记录最近操作的型号和意图（key=client地址）
SESSION_MEMORY = {}
# 多轮对话历史：存最近 N 轮完整对话（含 user/assistant）
CHAT_HISTORY = {}
MAX_HISTORY = 10  # 每个 session 最多保留 10 轮（20 条消息）

# ====== 会话管理 ======
SESSION_CREATED = {}  # session_id → 创建时间
RATINGS = []  # 评分记录 [{session_id, surname, message, rating, time, reply}]
RATINGS_FILE = os.path.join(BASE_DIR, "ratings_log.json")
# 启动时从文件加载评分
try:
    if os.path.exists(RATINGS_FILE):
        with open(RATINGS_FILE, "r", encoding="utf-8") as f:
            RATINGS = json.load(f)
        print(f"[RATINGS] 加载了 {len(RATINGS)} 条历史评分")
except:
    pass

def _list_sessions(current_id):
    """列出所有活跃会话"""
    sessions = []
    for sid, mem in SESSION_MEMORY.items():
        sessions.append({
            "id": sid,
            "short_id": sid[:12],
            "model": mem.get("model", ""),
            "last_intent": mem.get("last_intent", ""),
            "last_msg": mem.get("last_msg", "")[:30],
            "is_current": sid == current_id
        })
    return {"code": 0, "sessions": sessions, "total": len(sessions)}

def _save_rating(client_id, surname, msg, rating, correction="", reply=""):
    """保存评分到内存和文件"""
    record = {
        "session_id": client_id,
        "surname": surname,
        "message": msg[:100],
        "reply": reply[:200],
        "rating": rating,
        "correction": correction,
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    RATINGS.append(record)
    try:
        with open(RATINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(RATINGS, f, ensure_ascii=False, indent=2)
    except:
        pass

def _dump_ratings():
    """导出所有评分"""
    return {"code": 0, "ratings": RATINGS, "total": len(RATINGS)}

# ====== 工具路由（keyword → 函数） ======
# (关键词列表, 工具函数, 分类名, 帮助提示)
TOOL_ROUTES = [
    (["回收价", "回收", "二手价", "二手", "卖多少", "值多少", "靓机汇", "回收报价", "买回价", "trade", "以旧换新", "recycle", "询价"],
     lambda msg: query_buyback(_extract_model(msg)),
     "buyback", "比如'14'、'16 Pro Max'"),

    (["算", "折", "期", "月供", "租机", "费用", "分期", "租机模式", "档位", "怎么租"],
     lambda msg: _smart_rental(msg),
     "rental", "比如'5000 5折 12期'"),

    (["库存", "有货", "什么机", "有没有", "几台", "货源"],
     lambda msg: query_inventory_agent(_extract_model(msg) if _extract_model(msg) else ""),
     "inventory", "比如'16'、'全部库存'"),

    (["办单", "费率", "返点", "首付", "结算", "规则", "入驻", "签约", "合同", "下线", "流程", "怎么弄", "资质", "档位", "提现", "到账", "提款", "怎么办单", "租机办单"],
     lambda msg: _query_rules(msg),
     "rules", "比如'怎么办单'、'首付谁收'"),

    (["海报", "促销", "宣传"],
     lambda msg, client_id, state: _gen_poster(msg, client_id),
     "poster", "比如'iPhone 16 月供203 12期'"),

    (["锁机", "上锁", "解bl索", "锁定", "Configurator", "注册此iPhone", "扫码上锁", "锁失效", "无锁头", "证书无效"],
     lambda msg: _query_lock(msg),
     "lock", "比如'怎么锁机'、'锁机报错证书无效'"),

    (["参数", "配置", "介绍", "卖点", "规格", "性能", "cpu", "芯片", "屏幕", "摄像头", "电池"],
     lambda msg: _query_specs(_extract_model(msg)),
     "specs", "比如'iPhone 15 Pro'"),

    (["门店", "入驻", "概况", "维修店", "综合店", "卖场", "档口", "回收渠道", "流通", "循环"],
     lambda msg: _query_store_overview(),
     "store_overview", "比如'门店概况'、'回收渠道'"),

    (["怎么经营", "怎么开", "没生意", "没客户", "怎么赚钱", "多赚", "引流", "抖音", "美团", "小红书", "大众点评", "闪购", "O2O", "留住客户", "老客户", "薪酬", "员工", "团队", "进货", "定价"],
     lambda msg: _query_biz_knowledge(msg),
     "biz_knowledge", "比如'怎么引流'、'没生意怎么办'"),
]

# 工具意图分类 prompt
INTENT_CLASSIFY_PROMPT = """你是马三多，手机妈妈平台AI商务。分析用户消息，判断他要用哪个工具。

可用工具：
1. buyback——查手机回收价（用户提到手机型号+回收/卖多少，如"14回收多少"）
2. rental——分期租机费用计算（用户明确要算具体价格，提到售价/折扣/期数）
3. inventory——查库存（用户问有什么机型、有没有货）
4. rules——查平台规则（办单流程、费率、首付、入驻、提现、返点、怎么办、怎么操作、资质、审核、通过不了）
5. specs——查手机参数配置（用户问某款手机的性能、配置、卖点）
6. pricing——定价分析（用户给了回收价/成本，问加多少钱卖、怎么定价、卖多少合适、零售/租机对比）
7. sales_tips——销售策略建议（用户问怎么提高订单、怎么多卖、怎么推租机、销售技巧、有什么好方法）
8. lock——锁机操作（用户问怎么锁机、上锁流程、锁机失败/报错/无锁头/证书无效等锁机问题）
9. composite——复合推演（用户同时提到旧机/回收+预算/现金+想办什么手机/置换/换新机/能办吗/能买吗/够吗/能不能办/怎么办/办什么/办理）
10. chat——闲聊/打招呼/无关问题

⚠️ 重要区分：
- 「怎么办单」「租机办单怎么办」→ rules
- 「2折通过不了」「审核不通过」→ rules
- 「加多少钱卖」「怎么定价」「卖多少合适」「回收XX 卖多少」→ pricing
- 「2500能办16PM吗」「XXX预算够不够买YYY」「能不能办」「够不够」→ composite
- 「iphone13小花 客户有2000块 能置换哪款」→ composite
- 「他手里有iphone15 256G的」→ composite（可能想置换/抵钱，要看上下文）
- 「客户只有2500 想买16PM」→ composite
- 「旧机抵多少+现金够不够上XX」→ composite
- 「XX预算在我们店里/门店能办什么手机」「XX元能办理什么手机」「XX预算推荐什么机」→ composite
- 「XX预算能办XXX吗」「XX元够不够办XXX」→ composite
- 「旧机抵XX+现金够不够上XX」→ composite
- 「用旧机抵呢」→ composite（上轮在谈预算不足，这是追问旧机折抵）
- 「帮我算」「算下」+ 有具体数字 → rental
- 「租机」「租机模式」但没有数字 → rental（引导或给表）

请只回复JSON：{"intent":"工具名","model":"提取的型号"}

示例：
- "怎么样才能让租机订单做的更多" → {"intent":"sales_tips","model":""}
- "怎么多卖点" → {"intent":"sales_tips","model":""}
- "回收2000的手机加多少钱卖好" → {"intent":"pricing","model":""}
- "iPhone12 义乌零售" → {"intent":"pricing","model":"12"}
- "14回收价" → {"intent":"buyback","model":"14"}
- "5000 5折 12期" → {"intent":"rental","model":""}
- "怎么办单" → {"intent":"rules","model":""}"""


# ====== HTTP 服务 ======
class MasanduoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len else {}
        msg = body.get("message", "").strip()
        session_id = body.get("session_id", "")
        client_id = session_id if session_id else self.client_address[0]
        surname = body.get("surname", "").strip()

        # ====== 管理后台 API ======
        if path.startswith("/api/admin/"):
            if path == "/api/admin/login":
                self._admin_login(body)
            elif not _check_admin_auth(self):
                self._json({"code": 401, "error": "未登录或登录已过期"}, 401)
            elif path == "/api/admin/buyback":
                self._admin_save_buyback(body)
            elif path == "/api/admin/inventory":
                self._admin_save_inventory(body)
            elif path == "/api/admin/rules":
                self._admin_save_rules(body)
            elif path == "/api/admin/reload":
                self._admin_reload_tools()
            return

        if path == "/api/chat":
            reply = _process(msg, client_id, surname)
            self._json({"code": 0, "reply": reply, "session_id": client_id})
        elif path == "/api/rating":
            r = body.get("rating", "")
            corr = body.get("correction", "")
            reply_text = body.get("reply", "")
            _save_rating(client_id, surname, msg, r, corr, reply_text)
            self._json({"code": 0, "msg": "评分已记录"})
        elif path == "/api/ratings":
            self._json(_dump_ratings())
        elif path == "/api/chat/stream":
            self._stream_chat(msg, client_id)
        elif path == "/api/sessions":
            self._json(_list_sessions(client_id))
        elif path == "/api/sessions/clear":
            target = body.get("session_id", client_id)
            if target and target in SESSION_MEMORY:
                del SESSION_MEMORY[target]
                self._json({"code": 0, "msg": f"会话 {target[:8]} 已清除"})
            else:
                self._json({"code": 0, "msg": "会话不存在或已过期"})
        elif path == "/api/health":
            self._json({"status": "ok", "version": "6.23"})
        else:
            self._json({"code": 404, "error": "Not Found"}, 404)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"status": "ok", "version": "6.23"})
        elif path == "/api/ratings":
            self._json(_dump_ratings())
        elif path == "/api/sessions":
            self._json(_list_sessions(""))
        # ====== 管理后台数据读取 API（需要登录） ======
        elif path == "/api/admin/buyback":
            if not _check_admin_auth(self):
                self._json({"code": 401, "error": "未登录"}, 401)
            else:
                self._json(_read_json(os.path.join(BASE_DIR, "knowledge", "buyback_prices.json")))
        elif path == "/api/admin/inventory":
            if not _check_admin_auth(self):
                self._json({"code": 401, "error": "未登录"}, 401)
            else:
                # 返回 JSON 数组格式给前端
                sys.path.insert(0, os.path.join(BASE_DIR, "tools"))
                from masanduo_tools import _load_inventory
                self._json({"code": 0, "data": _load_inventory()})
        elif path == "/api/admin/rules":
            if not _check_admin_auth(self):
                self._json({"code": 401, "error": "未登录"}, 401)
            else:
                self._json(_read_json(os.path.join(BASE_DIR, "knowledge", "platform_rules.json")))
        elif path == "/api/admin/ratings":
            if not _check_admin_auth(self):
                self._json({"code": 401, "error": "未登录"}, 401)
            else:
                self._json(_dump_ratings())
        # ====== 静态页面 ======
        elif path in ("/admin", "/admin/"):
            _serve_static(self, "admin/index.html", "text/html; charset=utf-8")
        elif path in ("/", "/chat_ui", "/chat_ui/index.html", "/index.html"):
            html_path = os.path.join(BASE_DIR, "chat_ui", "index.html")
            if os.path.exists(html_path):
                with open(html_path, "r", encoding="utf-8") as f:
                    html = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(html.encode("utf-8")))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            else:
                self._json({"code": 404, "error": "chat_ui/index.html not found"}, 404)
        else:
            self._json({"code": 404, "error": "Not Found"}, 404)

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _stream_chat(self, msg, client_id):
        """SSE 流式聊天"""
        reply = _process(msg, client_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        # 逐字推送（模拟流式，每字约40ms）
        import time as _time
        for char in reply:
            data = json.dumps({"text": char, "done": False}, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
            _time.sleep(0.04)
        # 结束信号
        self.wfile.write(f"data: {json.dumps({'text': '', 'done': True}, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {args[0]}")


# ====== 核心处理 ======
SOUL = None


def _load_soul():
    global SOUL
    if SOUL is None:
        path = os.path.join(BASE_DIR, "SOUL.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                SOUL = f.read()
        else:
            SOUL = "你是马三多，手机妈妈平台的AI商务。称呼用户为老板。"
    return SOUL


def _keyword_route(msg: str, client_id: str = "") -> str:
    """关键词路由，替代 DeepSeek 意图分类，秒级响应"""
    msg_lower = msg.lower().replace(" ", "")
    has_model = _extract_model(msg)
    has_budget = bool(re.search(r'(?<!\d)\d{3,5}(?!\d)', msg) or re.search(r'[一二三四五六七八九]千', msg.lower())
                      or any(kw in msg_lower for kw in ['三千','五千','八百','一千','两千','四千','六千','七千','八千','九千']))

    # 0. 最高优先级：套机/监管机拦截（必须在所有业务路由前面）
    if any(kw in msg_lower for kw in ["套机","套现","套你们","能不能套","怎么套","帮忙套","套个机"]):
        return "套机风险"
    if any(kw in msg_lower for kw in ["监管机","监管","有锁机","配置锁"]):
        return "监管机"

    # 0.5 复合推演
    # 情况A：有型号 + 想办/置换关键词
    if has_model and any(kw in msg_lower for kw in ["想办","想买","置换","换新","以旧换新","抵","换","推荐档位","推荐"]):
        return "composite"
    # 情况B：有型号+预算+能力问句
    if has_model and has_budget and any(kw in msg_lower for kw in ["能办吗","能不能办","能办不","够不够","可以办吗","能办理吗","过不过","过得了"]):
        return "composite"
    # 情况C：纯预算+想买（无型号），走 composite 算方案
    if has_budget and any(kw in msg_lower for kw in ["能做什么","能买什么","可以买","推荐","办个","办什么","能办什么","算算"]):
        return "composite"

    # 1. 回收价
    if any(kw in msg_lower for kw in ["回收价","回收","二手价","卖多少","值多少","靓机汇","卖给你们","旧机"]):
        return "buyback"

    # 2. 库存
    if any(kw in msg_lower for kw in ["库存","有货","有什么机","有什么库存","全部库存"]):
        return "inventory"

    # 3. 定价分析（必须在"多少钱"之前，防止被误判为库存）
    if any(kw in msg_lower for kw in ["加多少钱","怎么定价","卖多少合适","零售","怎么卖"]):
        return "pricing"

    # 4. 售价/库存
    if any(kw in msg_lower for kw in ["多少钱","什么价"]):
        return "inventory"

    # 5. 租机计算（必须有数字）
    if any(kw in msg_lower for kw in ["算一下","租机","几折","几期","月供","费用","分期","折"]):
        return "rental"

    # 5. 海报
    if any(kw in msg_lower for kw in ["海报","宣传","推广图"]):
        return "poster"

    # 6. 规则/锁机
    if any(kw in msg_lower for kw in ["费率","办单","下单","结算","返点","首付","规则","入驻","签约","合同","红线","租机模式","锁机","上锁","configurator","无锁头","证书无效","电脑","pc","远程"]):
        if any(kw in msg_lower for kw in ["锁机","上锁","configurator","无锁头","证书无效"]):
            return "lock"
        return "rules"

    # 6.5 平台优势/为什么选你/选你家 → chat（由马三多自然发挥优势桥段）
    if any(kw in msg_lower for kw in ["为什么选","优势","有什么好","你家","你们家","你们这边","你们这"]):
        return "chat"

    # 6.6 验机相关
    if any(kw in msg_lower for kw in ["验机","不愿意验","非要验"]):
        return "sales_tips"

    # 7. 销售策略
    if any(kw in msg_lower for kw in ["怎么提高","怎么多卖","销售技巧","怎么推","话术","营销","怎么说","客户说","推销"]):
        return "sales_tips"

    # 8. 参数/卖点/对比（纯参数查询，无置换意图）
    if any(kw in msg_lower for kw in ["参数","配置","处理器","摄像头","颜色","屏幕","电池","卖点","介绍","怎么样","值得买","对比","比较","区别","怎么选"]):
        return "specs"

    # 8.5 门店概况
    if any(kw in msg_lower for kw in ["门店","入驻","概况","维修店","综合店","卖场","档口","回收渠道","流通"]):
        return "store_overview"

    # 8.6 经营干货（怎么经营/没生意/怎么引流/O2O/员工管理）
    if any(kw in msg_lower for kw in ["怎么经营","怎么开","没生意","没什么生意","生意不好","生意差","没客户","怎么赚钱","多赚","引流","抖音","美团","小红书","大众点评","闪购","留住客户","老客户","薪酬","员工","团队","进货","定价","出路","行情","难做","不行了"]):
        return "biz_knowledge"

    # 8.6.5 电商素材生成（闲鱼/淘宝/拼多多/转转/电商主图/商品描述/素材/产品识别）
    if any(kw in msg_lower for kw in ["闲鱼","淘宝","拼多多","转转","电商主图","商品描述","素材","产品识别","电商海报","电商素材","做图","出图"]):
        return "ecommerce"

    # 8.7 人工客服
    if any(kw in msg_lower for kw in ["人工","客服","转人工","真人"]):
        return "human_agent"

    # 9. 上下文延续（纯闲聊/打招呼词不延续业务意图）
    chat_only = ["你好", "在吗", "哈喽", "hello", "hi", "早上好", "下午好", "晚上好", "早", "晚安", "谢谢", "拜拜", "再见"]
    confirm_words = ["好", "可以", "ok", "嗯", "哦", "行", "是的", "对", "没错", "要", "算", "做", "出", "办"]
    
    state = _get_state(client_id)
    last_intent = state.get("last_intent", SESSION_MEMORY.get(client_id, {}).get("last_intent", ""))
    
    # 确认词：如果上一轮有业务上下文，延续；否则走闲聊
    if msg_lower.strip() in confirm_words:
        if last_intent in ["buyback","rental","composite","inventory","specs","pricing","rules"]:
            return last_intent
        return "chat"
    
    if msg_lower.strip() in chat_only:
        return "chat"
    
    # 简短追问延续（如"这两款""有没有"）
    followup_keywords = ["这两款","这两个","这几款","那几个","有没有","有吗","店里","我们店","多少钱一个","什么价"]
    if last_intent in ["buyback","rental","composite","inventory","specs","pricing","rules"]:
        if len(msg.strip()) <= 12:
            return last_intent
        if any(kw in msg_lower for kw in followup_keywords):
            return last_intent if last_intent in ["inventory","specs","buyback"] else "inventory"

    # 默认闲聊
    return "chat"


# ====== 状态机（替代旧 SESSION_MEMORY + CHAT_HISTORY） ======
SESSION_STATE = {}  # client_id → {budget, target, old_device, last_intent, summary}

def _get_state(client_id):
    """获取会话状态机，不存在则创建"""
    return SESSION_STATE.setdefault(client_id, {
        "budget": 0, "target": "", "old_device": "",
        "last_intent": "", "summary": "", "rounds": 0
    })

def _update_state(client_id, **kwargs):
    """更新状态字段"""
    s = _get_state(client_id)
    s.update(kwargs)
    s["rounds"] = s.get("rounds", 0) + 1
    # 只保留最近 5 轮的关键信息做 summary
    if s["rounds"] > 5:
        keep = ["budget","target","old_device","last_intent"]
        for k in list(s.keys()):
            if k not in keep and k not in ("rounds","summary"):
                del s[k]
    return s


# ====== 三 Agent 架构：路由 → 计算 → 润色 ======

def _process(msg: str, client_id: str = "", surname: str = "") -> str:
    """三 Agent 流水线：路由 Agent → 计算 Agent → 润色 Agent"""
    msg_lower = msg.lower().replace(" ", "")
    state = _get_state(client_id)

    # ── Agent 1: 意图路由（关键词，秒级） ──
    extracted_model = _extract_model(msg)
    intent_name = _keyword_route(msg, client_id)

    # 容量追问处理
    capacity_match = re.match(r'^(\d+)\s*(G|g)$', msg.strip())
    if capacity_match and state.get("last_intent") in ("buyback","composite") and state.get("old_device"):
        old = state["old_device"] + " " + capacity_match.group(1) + "G"
        _update_state(client_id, old_device=old)

    # ── Agent 2: 业务计算（纯数据输出 JSON） ──
    compute_result = _compute(msg, client_id, intent_name, extracted_model, state)
    if compute_result.get("error"):
        return compute_result["error"]
    if compute_result.get("direct"):
        # 模糊反问等直接返回
        return compute_result["direct"]

    # ── Agent 3: 润色表达（JSON → 马三多话术，一次 DeepSeek 调用） ──
    return _polish(msg, compute_result, intent_name, surname, client_id, state)


def _compute(msg, client_id, intent_name, extracted_model, state):
    """业务计算层。输入：用户消息+路由结果 → 输出：纯 JSON 数据"""
    msg_lower = msg.lower()
    msg_stripped = msg.strip()

    # 模糊拦截
    if intent_name == "chat" and len(msg_stripped) <= 6:
        model_in = _extract_model(msg)
        is_digit = msg_stripped.isdigit() and 1 <= int(msg_stripped) <= 20
        if (model_in or is_digit) and state.get("last_intent","") not in ("buyback","rental","composite"):
            return {"direct": f"老板，你想了解{model_in or msg_stripped}的什么？回收价、参数配置、库存？说清楚我好帮你查~"}

    # 闲聊
    if intent_name == "chat":
        _update_state(client_id, last_intent="chat")
        return {"intent": "chat", "data": {}, "state": state}

    # 工具调用 → JSON 数据
    try:
        if intent_name == "buyback":
            model = extracted_model or state.get("old_device","")
            data = _compute_buyback(model)
            _update_state(client_id, old_device=model or extracted_model, last_intent="buyback")
            return {"intent":"buyback", "data":data, "state":state}

        if intent_name == "inventory":
            data = _compute_inventory(extracted_model or "")
            _update_state(client_id, last_intent="inventory")
            return {"intent":"inventory", "data":data, "state":state}

        if intent_name == "rental":
            data = _compute_rental(msg)
            _update_state(client_id, last_intent="rental")
            return {"intent":"rental", "data":data, "state":state}

        if intent_name == "composite":
            data = _compute_composite(msg, client_id, state)
            _update_state(client_id, last_intent="composite")
            return {"intent":"composite", "data":data, "state":state}

        if intent_name == "pricing":
            model = extracted_model or state.get("old_device","")
            data = _compute_pricing(msg, model)
            _update_state(client_id, last_intent="pricing")
            return {"intent":"pricing", "data":data, "state":state}

        if intent_name == "rules":
            data = _compute_rules(msg)
            _update_state(client_id, last_intent="rules")
            return {"intent":"rules", "data":data, "state":state}

        if intent_name == "specs":
            # 支持多型号对比：提取消息中所有型号
            models_raw = re.findall(r'iphone\s*(\d{1,2}\s*(?:pro\s*max|pm|pro|plus|mini)?)', msg, re.IGNORECASE)
            models = []
            seen = set()
            for m in models_raw:
                std = _extract_model(m)
                if std and std not in seen:
                    models.append(std)
                    seen.add(std)
            if not models:
                models = [extracted_model or state.get("old_device","")]
            if len(models) >= 2:
                # 多型号对比
                results = []
                for m in models:
                    results.append({"model": m, "specs": _query_specs(m)})
                data = {"models": results, "compare": True}
            else:
                data = _compute_specs(models[0] if models else "")
            _update_state(client_id, last_intent="specs")
            return {"intent":"specs", "data":data, "state":state}

        if intent_name == "lock":
            data = _compute_lock(msg)
            _update_state(client_id, last_intent="lock")
            return {"intent":"lock", "data":data, "state":state}

        if intent_name in ("store_overview",):
            data = _compute_store_overview()
            _update_state(client_id, last_intent="store_overview")
            return {"intent":"store_overview", "data":data, "state":state}

        if intent_name == "biz_knowledge":
            data = _compute_biz_knowledge(msg)
            _update_state(client_id, last_intent="biz_knowledge")
            return {"intent":"biz_knowledge", "data":data, "state":state}

        if intent_name == "套机风险":
            data = _compute套机风险()
            _update_state(client_id, last_intent="套机风险")
            return {"intent":"套机风险", "data":data, "state":state}

        if intent_name == "监管机":
            data = _compute_监管机()
            _update_state(client_id, last_intent="监管机")
            return {"intent":"监管机", "data":data, "state":state}

        if intent_name == "ecommerce":
            data = _compute_ecommerce(msg, extracted_model, state)
            _update_state(client_id, last_intent="ecommerce")
            return {"intent":"ecommerce", "data":data, "state":state}

        if intent_name == "human_agent":
            return {"intent":"human_agent", "direct": HUMAN_AGENT_REPLY, "state":state}

    except Exception as e:
        return {"error": f"老板，{intent_name} 查的时候出了点问题：{e}"}

    _update_state(client_id, last_intent="chat")
    return {"intent": "chat", "data": {}, "state": state}


# ====== 计算层：每个业务输出纯 JSON ======

def _compute_buyback(model):
    result = query_buyback(model) if model else ""
    return {"model": model, "result": result}

def _compute_inventory(model):
    result = query_inventory_agent(model or "")
    return {"model": model, "result": result}

def _compute_rental(msg):
    result = _smart_rental(msg)
    return {"result": result}

def _compute_pricing(msg, model):
    result = _pricing_analysis(msg, model or "")
    return {"model": model, "result": result}

def _compute_rules(msg):
    result = _query_rules(msg)
    return {"result": result}

def _compute_specs(model):
    result = _query_specs(model or "")
    return {"model": model, "result": result}

def _compute_lock(msg):
    result = _query_lock(msg)
    return {"result": result}

def _compute_store_overview():
    result = _query_store_overview()
    return {"result": result}

def _compute_biz_knowledge(msg):
    result = _query_biz_knowledge(msg)
    return {"result": result}

def _compute套机风险():
    """套机风险警告 - 坚决反对，不调 AI，直接硬返回"""
    return {"result": "套机风险"}

def _compute_监管机():
    """监管机 - 不支持回收"""
    return {"result": "监管机"}

def _compute_ecommerce(msg, extracted_model, state):
    """电商素材生成计算层"""
    # 提取产品名称：型号 > 消息里的产品描述
    product_name = extracted_model or ""
    # 提取卖点（消息里可能附带）
    selling_points = msg.strip()[:200] if len(msg.strip()) > 3 else ""
    result = flow_ecommerce_assets(
        product_name=product_name,
        selling_points=selling_points,
        image_desc=""
    )
    return {"result": result}

def _compute_composite(msg, client_id, state):
    """复合推演计算层——纯数据，不润色"""
    msg_lower = msg.lower()
    # 默认全款，除非老板明确说租机/分期/几折
    is_rental = any(kw in msg_lower for kw in ["租机","分期","折","走平台","租","办单"])
    is_full = any(kw in msg_lower for kw in ["全款","全价","一次性","一口价","直接买","不租","买断"]) or not is_rental
    has_trade = any(kw in msg_lower for kw in ["换","置换","抵","旧机","以旧换新","手上有","手里有","有一台"])

    # 提取型号
    models = re.findall(r'(\d{1,2}\s*(?:pro\s*max|pm|pro|plus|mini|air|e)?)', msg, re.IGNORECASE)
    models = [m.strip() for m in models if not m.strip().isdigit()]

    target_model = ""
    old_model = ""
    if len(models) >= 2:
        old_model = _extract_model(models[0]) or models[0]
        target_model = _extract_model(models[1]) or models[1]
    elif len(models) == 1 and has_trade:
        old_model = _extract_model(models[0]) or models[0]
    elif len(models) == 1:
        target_model = _extract_model(models[0]) or models[0]
    else:
        target_model = _extract_model(msg) or ""
        if has_trade:
            old_model = state.get("old_device","")

    # 提取预算
    # 先处理中文数字
    cn_num_map = {'三千':3000,'四千':4000,'五千':5000,'六千':6000,'七千':7000,'八千':8000,'九千':9000,'一万':10000,'两万':20000,'三万':30000,'四万':40000,'五万':50000,'一千':1000,'两千':2000,'八百':800}
    cash = 0
    for cn, v in cn_num_map.items():
        if cn in msg:
            cash = v
            break
    # 再匹配阿拉伯数字
    if cash == 0:
        nums = re.findall(r'(?<!\d)(\d{3,5})(?!\d)', msg)
        for n in nums:
            v = int(n)
            if 500 <= v <= 50000:
                cash = v
                break

    # 旧机回收价
    buyback_result = ""
    buyback_value = 0
    if old_model:
        from tools.masanduo_tools import _load_buyback_prices
        buyback_result = query_buyback(old_model)
        prices_data = _load_buyback_prices()
        if prices_data:
            mk = old_model.lower().replace("iphone ","").replace("iphone","").strip()
            for p in prices_data.get("prices",[]):
                if p["model"].lower().strip() == mk and "靓机" in p:
                    buyback_value = int(p.get("靓机",0))
                    break

    # 库存
    inventory_result = query_inventory_agent(target_model or "")

    total = buyback_value + cash
    _update_state(client_id, budget=cash, target=target_model, old_device=old_model)

    return {
        "mode": "full" if is_full else "rental",
        "old_model": old_model,
        "target_model": target_model,
        "buyback_value": buyback_value,
        "buyback_result": buyback_result,
        "cash": cash,
        "total": total,
        "inventory": inventory_result,
        "has_old_device": bool(old_model)
    }


# ====== 润色 Agent：JSON → 马三多话术（一次 DeepSeek 调用） ======

def _save_history(client_id, user_msg, reply):
    """统一存上下文历史"""
    hist = CHAT_HISTORY.setdefault(client_id, [])
    hist.append({"role": "user", "content": user_msg})
    hist.append({"role": "assistant", "content": reply})
    if len(hist) > MAX_HISTORY * 2:
        CHAT_HISTORY[client_id] = hist[-(MAX_HISTORY * 2):]

def _polish(user_msg, compute_result, intent_name, surname, client_id, state):
    """把计算层的 JSON 数据润色成马三多风格回复"""
    intent = compute_result.get("intent", intent_name)
    data = compute_result.get("data", {})

    thinking_map = {
        "buyback": "好嘞老板，我帮您查下靓机汇的回收价~",
        "rental": "好嘞老板，我帮您算一下~",
        "inventory": "好嘞老板，我帮您看下库存~",
        "rules": "好嘞老板，我帮您查一下平台规则~",
        "specs": "好嘞老板，我帮您查下这款机子的参数~",
        "pricing": "好嘞老板，我帮您算算定价~",
        "composite": "好嘞老板，我帮您算算置换方案~",
        "lock": "好嘞老板，我帮您查下锁机流程~",
        "store_overview": "好嘞老板，我帮您介绍下平台门店情况~",
        "biz_knowledge": "好嘞老板，我帮您参谋参谋~",
        "ecommerce": "好嘞老板，我帮您生成电商素材方案~",
        "chat": "",
    }
    thinking = thinking_map.get(intent, "好嘞老板，我帮您查查~")

    # 组装 system prompt
    sys_prompt = _build_system_prompt(surname)

    # 组装 user prompt
    if intent == "套机风险":
        # 套机风险直接返回，不走 DeepSeek
        reply = _get_套机风险_reply(surname)
        _save_history(client_id, user_msg, reply)
        return reply
    
    if intent == "监管机":
        reply = _get_监管机_reply(surname)
        _save_history(client_id, user_msg, reply)
        return reply
    
    cd = compute_result.get('data', compute_result)
    if intent == "composite" and cd.get('mode') == 'full':
        # 全款模式：走 DeepSeek 润色，但强制全款规则
        cash = cd.get('cash', 0)
        inv = cd.get('inventory', '')
        # 清洗库存数据，去掉所有租机相关行
        clean_lines = []
        for line in inv.split('\n'):
            if not any(kw in line.lower() for kw in ['折','租','月供','分期','首付','费率','档位','服务费']):
                clean_lines.append(line)
        clean_inv = '\n'.join(clean_lines)
        
        user_prompt = f"""用户问：{user_msg}

【数据】
- 模式：全款买断（绝对禁止提租机/分期/月供/档位/费率）
- 客户现金：{cash}元
- 库存：
{clean_inv}

【任务】根据客户预算匹配最接近的机型：
1. 售价<=预算的直接推荐，标出差额
2. 预算不够最便宜机型的，说差多少元，推荐最便宜那款
3. 用马三多口吻自然聊天，别只甩表格
4. 禁止出现「租机」「分期」「月供」「档位」「首付」「费率」「服务费」
5. 最后问一句有没有旧机可以折抵
6. 结尾：老板还有什么活需要我给你干的"""
        
        history = CHAT_HISTORY.get(client_id, [])
        reply = _call_deepseek([
            {"role": "system", "content": sys_prompt},
            *history,
            {"role": "user", "content": user_prompt}
        ])
        _save_history(client_id, user_msg, reply)
        return reply
    
    if intent == "ecommerce":
        # 电商素材直接返回，不走 DeepSeek 润色
        result = data.get("result", "")
        _save_history(client_id, user_msg, result)
        return result
    
    if intent == "chat":
        user_prompt = f"用户说：{user_msg}\n\n用马三多的口吻自然回复。别忘了你是一个手机妈妈平台的AI商务合伙人。结尾统一说：老板还有什么活需要我给你干的。"
    elif intent == "composite":
        cd = compute_result
        is_rental = cd.get('mode') != 'full'
        no_old = not cd.get('has_old_device')
        rules = []
        if is_rental:
            rules.append("【必须】列出完整租机方案表格：档位 | 售价 | 服务费 | 设备管理费 | 订单总价 | 最低首付 | 月供×期数。每个可行档位一行。")
            rules.append("【必须】先用合计预算匹配库存售价，筛选出首付≤预算的档位。如果都不够，推荐降级机型。")
            if no_old:
                rules.append("【禁止】不要提旧机回收价和抵扣。用户没旧机，纯现金。")
        else:
            # 全款模式：粗暴剪掉库存里所有租机相关数据
            inventory_str = cd.get('inventory','')
            # 去掉包含打折、档位、月供的行
            clean_lines = []
            for line in inventory_str.split('\n'):
                if not any(kw in line.lower() for kw in ['折','租','月供','分期','首付']):
                    clean_lines.append(line)
            clean_inventory = '\n'.join(clean_lines)
            rules.append("【全款模式 - 铁律】只算全款预算 vs 售价。你的回复中禁止出现「租机」「分期」「月供」「档位」「费率」「服务费」「首付」「打折」「几折」这些词。")
            rules.append("【禁止】禁止输出租机/月供/分期/档位/费率/服务费。禁止提【租机】【分期】。最便宜的机型高于预算就说最便宜的是XXX售价YYY差ZZZ元。然后问是否有旧机抵扣。"); rules.append("【最终警告】如果你在回复中提了「租机」「分期」「首付」「档位」中的任何一个词，这条回复就是错误的。这是全款场景。")
            return_data = f"""【计算层输出数据】
- 模式：全款买断
- 客户现金：{cd.get('cash',0)}元
- 库存：
{clean_inventory}"""
        if not is_rental:
            # 全款模式用清洗后的数据
            rules_str = '\n'.join(rules)
            user_prompt = f"""用户问：{user_msg}

{return_data}

{rules_str}

{thinking}"""
        else:
            rules.append("【禁止】禁止编造数字。所有售价必须来自库存数据。")
            rules.append("【禁止】禁止说【咱按XXX售价算】【假设售价XXX】等模糊表述。")
            rules_str = '\n'.join(rules)
            user_prompt = f"""用户问：{user_msg}

【计算层输出数据】
- 模式：租机置换
- 旧机：{cd.get('old_model','无')}
- 目标机型：{cd.get('target_model','')}
- 旧机回收价：{cd.get('buyback_value',0)}元
- 旧机回收详情：
{cd.get('buyback_result','')}
- 客户现金：{cd.get('cash',0)}元
- 合计预算：{cd.get('total',0)}元
- 库存：
{cd.get('inventory','')}

{rules_str}

{thinking}"""
    else:
        # specs 对比模式
        if intent == "specs" and data.get("compare"):
            models_info = data.get("models", [])
            specs_parts = []
            for mi in models_info:
                specs_parts.append(f"【{mi['model']}】\n{mi['specs']}")
            result_text = "\n\n".join(specs_parts)
        else:
            result_text = data.get("result", "")
        
        # 如果用户问话术，额外补充营销建议
        need_sales = any(kw in user_msg.lower() for kw in ["话术","营销","怎么说","客户说","推销"])
        sales_hint = ""
        if need_sales:
            sales_hint = """

【额外要求】用户还要话术，请在对比之后，给出 2-3 条可直接复制给客户的营销话术（用引号标注），围绕"以旧换新抵首付""租机月供低""现在下单有返点"等卖点。
【严禁编造】所有参数（处理器、屏幕、电池等）必须严格来自上面的平台真实数据，禁止自己推测或编造。"""
        
        user_prompt = f"""用户问：{user_msg}

以下是平台真实数据：
{result_text}
{sales_hint}
{thinking}
用马三多的语气（合伙人/老油条，叫老板）回答。不要直接复制数据，要像聊天一样自然。有表格可以保留。最后用「简单说就是」一句话总结。结尾统一说：老板还有什么活需要我给你干的。禁止提【海报】【出单】。"""

    # 带上上下文历史
    history = CHAT_HISTORY.get(client_id, [])
    reply = _call_deepseek([
        {"role": "system", "content": sys_prompt},
        *history,
        {"role": "user", "content": user_prompt}
    ])
    
    # 全款模式后处理：如果 DeepSeek 不听话出了租机内容，追加纠正
    if intent == "composite" and compute_result.get('mode') != 'full':
        # 租机模式正常返回
        pass
    elif intent == "composite":
        # 全款模式，检查回复是否含租机相关词
        rent_kws = ["租机","分期","月供","档位","首付"]
        if any(kw in reply for kw in rent_kws):
            # DeepSeek 不听话，用纯文本覆盖
            cash = compute_result.get("cash", 0)
            inv = compute_result.get("inventory", "")
            reply = f"""老板，{cash}元全款能拿的手机：

我把库存按售价排了下——
{inv}

当前库存最便宜的机型售价都高于{cash}元，全款买断还差一点。

💡 如果客户手头有旧机可以折抵，告诉我型号和成色，我帮你算回收价加到预算里。

老板还有什么活需要我给你干的。"""
    
    # 存入上下文历史
    _save_history(client_id, user_msg, reply)
    return reply


# 旧代码 placeholder，替换上面的重复定义

def _extract_model(msg: str) -> str:
    """从消息中提取手机型号（优先俗称映射 → 正则提取）"""
    msg_lower = msg.lower().replace(" ", "").replace("iphone", "").replace("苹果", "")

    # 俗称 → 标准型号映射表（先整体匹配，禁止切碎）
    ALIAS_MAP = {
        "16pm": "16 Pro Max",
        "16promax": "16 Pro Max",
        "16pro": "16 Pro",
        "15pm": "15 Pro Max",
        "15promax": "15 Pro Max",
        "15pro": "15 Pro",
        "14pm": "14 Pro Max",
        "14promax": "14 Pro Max",
        "14pro": "14 Pro",
        "13pm": "13 Pro Max",
        "13promax": "13 Pro Max",
        "13pro": "13 Pro",
        "12pm": "12 Pro Max",
        "12promax": "12 Pro Max",
        "12pro": "12 Pro",
        "11pm": "11 Pro Max",
        "11promax": "11 Pro Max",
        "11pro": "11 Pro",
        "16plus": "16 Plus",
        "15plus": "15 Plus",
        "14plus": "14 Plus",
    }
    # 按 key 长度降序匹配（优先匹配长别名，如 16promax 比 16 先匹配）
    for alias in sorted(ALIAS_MAP.keys(), key=len, reverse=True):
        if alias in msg_lower:
            return ALIAS_MAP[alias]

    # 纯数字短型号匹配（"16"、"15" 等，必须在俗称映射之后）
    pure_digit = re.search(r'^(\d{1,2})$', msg_lower)
    if pure_digit:
        v = int(pure_digit.group(1))
        if 8 <= v <= 17:
            return str(v)

    # 通用正则提取（保底）
    patterns = [
        r'(\d{1,2}\s*(?:pro\s*max|pro|plus|mini|air|e)?)',
        r'(se\d?)',
        r'(xr?)',
        r'(xs\s*max|xs)',
        r'(\d{1,2})(?:\s*(?:的|回收|二手|价格|多少))',
    ]
    for p in patterns:
        m = re.search(p, msg, re.IGNORECASE)
        if m:
            model = m.group(1).strip()
            if model.isdigit():
                v = int(model)
                if v < 8 or v > 17:
                    continue
            if model.lower() in ["x", "8", "8p", "11"]:
                return model
            return model
    return ""


def _smart_rental(msg: str) -> str:
    """智能提取售价、折扣、期数 + 意图表路由"""
    import random

    # 1. 先读意图表
    intent_path = os.path.join(KNOWLEDGE_DIR, "intent_routes.json")
    intent_routes = {}
    if os.path.exists(intent_path):
        with open(intent_path, "r", encoding="utf-8") as f:
            intent_routes = json.load(f).get("routes", {})

    # 2. 提取数字
    nums = re.findall(r'(\d+)', msg)
    price = None
    tier = None
    periods = None

    for n in nums:
        v = int(n)
        if v >= 1000 and price is None:
            price = v
        elif v in [2, 3, 4, 5, 6] and tier is None:
            tier = f"{v}折"
        elif v in [6, 12] and periods is None:
            periods = v

    # 3. 三个参数齐全 → 直接算
    if price and tier and periods:
        src = "pc" if "pc" in msg.lower() else "app"
        return calculate_rental(price, tier, periods, src)

    # 4. 有售价但缺折扣/期数 → 引导补充
    if price:
        missing = []
        if not tier:
            missing.append("打几折（2折~6折）")
        if not periods:
            missing.append("分多少期（6期/12期）")
        guides = [
            f"好嘞老板！售价 {price} 元记下了，还需要告诉我：{'、'.join(missing)}～比如「{price}元的手机 5折 12期」我秒算 😎",
            f"老板，售价 {price} 元知道了！还需补充：{'、'.join(missing)}。直接说就行，像「{price} 5折 12期」～",
        ]
        return random.choice(guides)

    # 5. 完全没有数字 → 查意图表决定引导还是给表
    # 匹配档位查询关键词 → 给表
    tier_keywords = intent_routes.get("档位查询", {}).get("keywords", ["租机模式", "档位", "费率", "有什么", "怎么算"])
    if any(kw in msg.lower() for kw in tier_keywords):
        return _build_tier_table_full()

    # 其他 → 引导三要素
    calc_routes = intent_routes.get("费用计算", {})
    hint = calc_routes.get("param_hint", "手机售价、打几折、分多少期")
    guides = [
        f"好嘞老板！要算租机费用得告诉我三样：{hint}。比如「5000元的手机 5折12期」我秒算 😎",
        f"老板，算租机费用需要：{hint}。或者直接说「5000 5折 12期」也行～",
    ]
    return random.choice(guides)


def _pricing_analysis(msg: str, model: str) -> str:
    """定价分析：回收价 → 建议售价（零售+租机对比）"""
    # model 安全转 int（可能含字母如 16pm）
    try:
        model_int = int(model) if model and model.strip().isdigit() else 0
    except ValueError:
        model_int = 0

    nums = re.findall(r'(\d+)', msg)
    cost = None
    for n in nums:
        v = int(n)
        if 500 <= v <= 5000 and cost is None and v != model_int:
            cost = v
            break

    buyback_data = query_buyback(model) if model else ""
    if not model and not cost:
        return "老板，告诉我是哪款手机、回收成本多少，我帮你算加多少钱卖～比如「iPhone12 回收900 义乌零售」"

    inventory_data = query_inventory_agent(model or "")

    msg_lower = msg.lower()
    city = ""
    for c in ["义乌", "杭州", "深圳", "北京", "上海", "广州", "成都"]:
        if c in msg_lower:
            city = c
            break

    channel = "零售"
    if "租机" in msg_lower or "分期" in msg_lower:
        channel = "租机"
    if "零售" in msg_lower:
        channel = "零售"

    lines = ["## 定价分析请求"]
    lines.append(f"- 型号：{model or '未知'}")
    lines.append(f"- 城市：{city or '未知'}")
    lines.append(f"- 渠道：{channel}")
    if cost:
        lines.append(f"- 回收成本：{cost}元")
    lines.append("")
    lines.append("## 回收价数据")
    lines.append(buyback_data if buyback_data else "无回收价数据")
    lines.append("")
    lines.append("## 库存参考")
    lines.append(inventory_data if inventory_data else "无库存数据")
    lines.append("")
    lines.append("## 定价建议模板")
    lines.append("1. 确认回收成本")
    lines.append("2. 定价表格：| 配置 | 回收价 | 建议零售价 | 毛利 | 利润率 |")
    lines.append("3. 城市特点一句话")
    lines.append("4. 零售vs租机对比")
    lines.append("5. 具体建议+结尾统一说：老板还有什么活需要我给你干的")
    lines.append("")
    lines.append("定价逻辑：二手零售加价20%~40%，义乌/走量城市偏低，一线城市偏高。租机可以标高售价。")

    return "\n".join(lines)


def _build_tier_table_full() -> str:
    """生成完整档位费率表"""
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    if not os.path.exists(rules_path):
        return "老板，规则文件找不到了～"

    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    lines = ["## 租机档位"]

    def _build_tier_table(tiers, title):
        rows = []
        rows.append(f"### {title}")
        rows.append("| 档位 | 6期费率 | 12期费率 | 服务内容 |")
        rows.append("|------|---------|----------|----------|")
        for t in tiers:
            name = t.get("name", "")
            # PC端: period_6/period_12 嵌套; APP端: rate_6/rate_12 平铺
            fee6 = t.get("rate_6", t.get("period_6", {}).get("pc_fee", t.get("period_6", {}).get("app_fee", "")))
            fee12 = t.get("rate_12", t.get("period_12", {}).get("pc_fee", t.get("period_12", {}).get("app_fee", "")))
            svc = t.get("service", t.get("period_6", {}).get("service", ""))
            rows.append(f"| {name} | {fee6} | {fee12} | {svc} |")
        return rows

    if "pc_tiers" in rules:
        lines.extend(_build_tier_table(rules["pc_tiers"]["tiers"], "PC端"))
        lines.append("")

    if "app_tiers" in rules:
        lines.extend(_build_tier_table(rules["app_tiers"]["tiers"], "APP端"))
        lines.append("")

    lines.append("## 计算公式")
    lines.append("- 服务费 = 手机售价 × 对应费率")
    lines.append("- 订单总价 = 售价 + 服务费 + 50元设备管理费")
    lines.append("- 最低首付 = 售价 × 对应首付比例")
    lines.append("- 6期月供 = (总价 − 首付) ÷ 5")
    lines.append("- 12期月供 = (总价 − 首付) ÷ 11")
    lines.append("")
    lines.append("## 核心规律")
    lines.append("- 首付比例越高 → 服务费率越低 → 总花费越少")
    lines.append("- 期数越长 → 月还款压力越小")
    lines.append("- 每单固定收50元设备管理费")

    if "settlement_rules" in rules:
        lines.append("")
        lines.append("## ⚠️ 重要更新：首付直接门店收")
        for r in rules["settlement_rules"].get("rules", []):
            lines.append(f"- {r}")

    return "\n".join(lines)


def _query_sales_tips() -> str:
    """查询销售策略建议"""
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    if not os.path.exists(rules_path):
        return "老板，规则文件暂时找不到～"

    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    tips = rules.get("sales_tips", {})
    if not tips:
        return "老板，销售策略模块还没配置好，稍等～"

    lines = [tips.get("description", "## 租机销售策略")]
    lines.append("")

    # 主推档位
    push = tips.get("push_tiers", [])
    if push:
        lines.append("## 💰 主推低首付档位")
        lines.append("| 档位 | 首付 | 卖点话术 |")
        lines.append("|------|------|----------|")
        for p in push:
            lines.append(f"| {p['tier']} | {p['down']} | \"{p['script']}\" |")
        lines.append("**客户心理：首付越低越容易冲动下单。推2折、3折最吸引人。**")
        lines.append("")

    # 场景营销
    scene = tips.get("scenario_targeting", [])
    if scene:
        lines.append("## 🎯 精准场景营销")
        lines.append("| 客户类型 | 推期数 | 理由 |")
        lines.append("|----------|--------|------|")
        for s in scene:
            lines.append(f"| {s['customer']} | {s['periods']} | {s['reason']} |")
        lines.append("")

    # 话术
    scripts = tips.get("sales_scripts", [])
    if scripts:
        lines.append("## 🗣️ 话术转化技巧")
        for s in scripts:
            lines.append(f"- **{s['trigger']}**：\"{s['response']}\"")
        lines.append("")

    # 复购
    ret = tips.get("retention_tips", [])
    if ret:
        lines.append("## 🔁 老客户复购")
        for r in ret:
            lines.append(f"- {r}")
        lines.append("")

    # PC返点
    pc = tips.get("pc_reward", "")
    if pc:
        lines.append(f"## 📊 PC端返点\n{pc}\n")

    # 合规
    comp = tips.get("compliance", "")
    if comp:
        lines.append(f"## ⚠️ 合规底线\n{comp}\n")

    # 总结
    summary = tips.get("summary", "")
    if summary:
        lines.append(f"**{summary}** 😄")

    return "\n".join(lines)


def _query_store_overview() -> str:
    """查询门店概况"""
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    if not os.path.exists(rules_path):
        return "老板，平台数据暂时加载不了～"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    store = rules.get("store_overview", {})
    if not store:
        return "老板，门店概况模块还没配置好～"
    lines = ["## 手机妈妈入驻门店概况\n"]
    lines.append(f"平台入驻门店总数：{store.get('total','')}\n")
    types = store.get("types", [])
    if types:
        lines.append("### 四类门店\n")
        lines.append("| 门店类型 | 核心定位 | 规模特征 | 业务侧重 |")
        lines.append("|----------|----------|----------|----------|")
        for t in types:
            lines.append(f"| {t['name']} | {t['positioning']} | {t['scale']} | {t['focus']} |")
    common = store.get("common_biz", [])
    if common:
        lines.append(f"\n### 共性业务（四类门店均涉及）\n{'、'.join(common)}\n")
    biz = store.get("biz_detail", {})
    if biz:
        lines.append("### 回收业务\n")
        buyback = biz.get("buyback", {})
        lines.append(f"流通闭环：{buyback.get('cycle','')}\n")
        rental = biz.get("rental", {})
        if rental:
            lines.append(f"### 租赁业务\n{rental.get('description','')}\n")
        sales = biz.get("sales_scenarios", {})
        if sales:
            lines.append("### 销售场景\n")
            lines.append(f"- 全款购机：{sales.get('full_purchase','')}")
            lines.append(f"- 旧机置换：{sales.get('trade_in','')}")
            lines.append(f"- 以租代购：{sales.get('rent_to_own','')}")
    return "\n".join(lines)

def _query_biz_knowledge(msg: str) -> str:
    """查询门店经营知识"""
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    if not os.path.exists(rules_path):
        return "老板，知识库暂时加载不了～"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)
    biz = rules.get("biz_knowledge", {})
    if not biz:
        return "老板，经营知识模块还没配置好～"

    msg_lower = msg.lower()
    lines = ["## 手机门店经营知识\n"]

    # 根据关键词匹配相关模块
    matched = []
    if any(kw in msg_lower for kw in ["员工","团队","薪酬","招聘","管理","人员"]):
        s = biz.get("staff_management", {})
        lines.append(f"### 人员管理\n{s.get('summary','')}")
        for r in s.get("rules", []):
            lines.append(f"- {r}")
        matched.append("staff")

    if any(kw in msg_lower for kw in ["引流","抖音","美团","小红书","大众点评","闪购","o2o","线上","渠道","推广"]):
        s = biz.get("sales_channels", {})
        lines.append(f"\n### 引流与线上渠道\n{s.get('summary','')}")
        lines.append(f"\n{s.get('o2o_intro','')}")
        lines.append("\n各平台用法：")
        for p in s.get("platforms", []):
            lines.append(f"- **{p['name']}**：{p['use']}")
        for t in s.get("tips", []):
            lines.append(f"- {t}")
        matched.append("channel")

    if any(kw in msg_lower for kw in ["老客户","留住","流失","截胡","微信","社群","会员"]):
        s = biz.get("customer_retention", {})
        lines.append(f"\n### 客户留存\n{s.get('summary','')}")
        for r in s.get("methods", []):
            lines.append(f"- {r}")
        matched.append("retention")

    if any(kw in msg_lower for kw in ["趋势","出路","行业","不行了","越来越难","变革","破局","转型"]):
        s = biz.get("industry_trend", {})
        lines.append(f"\n### 行业趋势与出路\n{s.get('summary','')}")
        for r in s.get("key_points", []):
            lines.append(f"- {r}")
        matched.append("trend")

    if any(kw in msg_lower for kw in ["进货","渠道","定价","产品","选品","货源"]):
        s = biz.get("product_strategy", {})
        lines.append(f"\n### 产品与定价\n{s.get('summary','')}")
        for r in s.get("tips", []):
            lines.append(f"- {r}")
        matched.append("product")

    # 如果什么模块都没匹配到（比如笼统问"怎么经营"），全量输出
    if not matched:
        for section in ["sales_channels", "customer_retention", "staff_management", "product_strategy"]:
            s = biz.get(section, {})
            if not s: continue
            lines.append(f"\n### {s.get('summary','')}")
            for r in s.get("rules", s.get("platforms", s.get("methods", s.get("tips", [])))):
                if isinstance(r, str): lines.append(f"- {r}")
                elif isinstance(r, dict): lines.append(f"- **{r.get('name','')}**：{r.get('use','')}")

    # 手机妈妈结合建议
    lines.append("\n### 手机妈妈工具结合")
    lines.append("老板可以把这些经营方法跟手机妈妈平台结合：")
    lines.append("- 租机模式本身就是引流利器：打出'月供XX元换新机'的噱头，抖音/小红书爆款素材")
    lines.append("- 以旧换新锁客：客户旧机只能抵给你，下次换机还找你")
    lines.append("- PC端检测软件：给客户看专业检测报告，建立信任感")
    lines.append("- 回收+租机组合：帮客户算'旧机抵首付，月供才XX'，转化率翻倍")

    return "\n".join(lines)

def _query_lock(msg: str) -> str:
    """查询锁机知识"""
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    if not os.path.exists(rules_path):
        return "老板，规则文件暂时找不到～"

    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    lock = rules.get("lock_process", {})
    if not lock:
        return "老板，锁机知识模块还没配置好，稍等～"

    # 排查相关
    if any(w in msg for w in ["失败", "报错", "不行", "不成功", "无效", "问题", "排查"]):
        specific = lock.get("troubleshooting_specific", [])
        matched = None
        for sp in specific:
            problem = sp.get("problem", "")
            if any(kw in msg for kw in ["无锁头", "没有锁", "没锁"]) and "无锁头" in problem:
                matched = sp
                break
            if any(kw in msg for kw in ["自动设备注册", "分配给Apple商务管理", "配置其注册设置"]) and "自动设备注册" in problem:
                matched = sp
                break
            if any(kw in msg for kw in ["证书无效", "证书"]) and "证书无效" in problem:
                matched = sp
                break

        if matched:
            lines = [f"【锁机报错】{matched['problem']}"]
            for i, s in enumerate(matched["steps"], 1):
                lines.append(f"{i}. {s}")
            return "\n\n".join(lines)

        gen = lock.get("troubleshooting_general", {})
        lines = [gen.get("description", "【锁机通用排查】")]
        for s in gen.get("steps", []):
            lines.append(s)
        return "\n\n".join(lines)

    # 默认返回完整流程
    lines = []
    prereqs = lock.get("prerequisites", [])
    if prereqs:
        lines.append("**前置条件**")
        for p in prereqs:
            lines.append(f"- {p}")

    steps_data = lock.get("steps", [])
    if steps_data:
        lines.append("\n**操作步骤**")
        for s in steps_data:
            step_num = s.get("step", "?")
            title = s.get("title", "")
            detail = s.get("detail", "")
            lines.append(f"\n**第{step_num}步：{title}**")
            lines.append(detail)

    notes = lock.get("notes", [])
    if notes:
        lines.append("\n**注意事项**")
        for n in notes:
            lines.append(f"- {n}")

    return "\n".join(lines)


def _get_套机风险_reply(surname: str = "") -> str:
    """套机风险回复 - 坚决反对套机 + 人文关怀"""
    name = (surname + "老板") if surname else "老板"
    return f"""{name}，我必须跟你把话说清楚——

套机这事，手机妈妈平台**坚决不行**。这不是开玩笑的，套机涉嫌违法犯罪，一旦出事，罚款坐牢都有可能，得不偿失啊。

咱们做生意，图的是长久。要分清「一顿饱」和「顿顿饱」的区别。套机可能一口吃饱，但吃完这顿就没下顿了，还会把自己搭进去。

做生意可以剑走偏锋，但绝对不能害人害己。诚信经营才是正道，细水长流才能走得远。

要是你真的遇到什么困难了，可以跟我讲讲——我会一直在这儿陪着你、守护着你。但一定一定不能干傻事。

需要聊什么正经生意上的事，我随时在。"""


def _get_监管机_reply(surname: str = "") -> str:
    """监管机回复 - 不支持回收"""
    name = (surname + "老板") if surname else "老板"
    return f"""{name}，监管机咱们手机妈妈不支持回收。

为啥不碰呢？因为监管机来路多半不正——可能是别人丢的、被偷的，或者是租来就没打算还的机器。虽然回收监管机利润确实高，但这是拿整个行业的健康生态换快钱，不划算。

一个健康的商用环境，需要大家一起维护。手机妈妈不做任何损害这个生态的事。

建议你去其他渠道问问，或者咱们聊点正经的回收生意——正常机器我可以马上帮你查价。

"""


def _query_rules(msg: str) -> str:
    """查平台规则"""
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    if not os.path.exists(rules_path):
        return "老板，规则文件我暂时找不到，稍等下哈～"

    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    msg_lower = msg.lower()

    # PC端下单流程（必须在"办单流程"之前）
    if any(kw in msg_lower for kw in ["pc端","电脑端","PC端","电脑","新机下单","旧机下单","远程下单","不在店"]):
        pc = rules.get("pc_order_process", {})
        if pc:
            lines = ["老板，PC端下单流程如下：\n"]
            new_steps = pc.get("new_phone_steps", [])
            if new_steps:
                lines.append("## 新机下单\n")
                for s in new_steps:
                    lines.append(f"- {s}")
            old_steps = pc.get("old_phone_steps", [])
            if old_steps:
                lines.append("\n## 旧机下单\n")
                for s in old_steps:
                    lines.append(f"- {s}")
            tier234 = pc.get("tier_234_rules", {})
            if tier234:
                lines.append(f"\n## 2/3/4折下单规则\n")
                for r in tier234.get("rules", []):
                    lines.append(f"- {r}")
            tier56 = pc.get("tier_56_rules", {})
            if tier56:
                lines.append(f"\n## 5/6折下单规则\n")
                for r in tier56.get("rules", []):
                    lines.append(f"- {r}")
            insp = pc.get("inspection", {})
            if insp:
                lines.append(f"\n## 验机须知\n")
                for r in insp.get("rules", []):
                    lines.append(f"- {r}")
            remote = pc.get("remote_order", {})
            if remote:
                lines.append(f"\n## 客户不在店时\n")
                for r in remote.get("rules", []):
                    lines.append(f"- {r}")
            return "\n".join(lines)

    if any(kw in msg_lower for kw in ["首付", "结算", "会员"]) and "settlement_rules" in rules:
        sr = rules["settlement_rules"]
        lines = ["老板，首付和结算规则如下："]
        for r in sr.get("rules", []):
            lines.append(f"  - {r}")
        for ex in sr.get("examples", []):
            lines.append(f"  📌 {ex['scenario']}：{ex['detail']}")
        return "\n".join(lines)

    # 办单流程
    if any(kw in msg_lower for kw in ["办单", "下单", "流程"]) and "rental_process" in rules:
        rp = rules["rental_process"]
        lines = [f"老板，办单流程（{len(rp['steps'])}步）："]
        for i, s in enumerate(rp["steps"], 1):
            lines.append(f"  {i}. {s}")
        return "\n".join(lines)

    # 入驻
    if any(kw in msg_lower for kw in ["入驻", "开店", "注册"]) and "shop_registration" in rules:
        sr = rules["shop_registration"]
        lines = [f"老板，入驻流程（{len(sr['steps'])}步）："]
        for i, s in enumerate(sr["steps"], 1):
            lines.append(f"  {i}. {s}")
        return "\n".join(lines)

    # 签约
    if any(kw in msg_lower for kw in ["签约", "合同"]) and "contract_signing" in rules:
        cs = rules["contract_signing"]
        lines = [f"老板，签约流程（{len(cs['steps'])}步）："]
        for i, s in enumerate(cs["steps"], 1):
            lines.append(f"  {i}. {s}")
        return "\n".join(lines)

    # 返点 / 提现
    if any(kw in msg_lower for kw in ["返点", "奖励", "佣金", "提现"]) and "merchant_rewards" in rules:
        mr = rules["merchant_rewards"]
        lines = ["老板，办单返点规则："]
        lines.append(f"  {mr['detail']}")
        for k, v in mr.items():
            if k != "detail" and isinstance(v, dict):
                lines.append(f"  📌 {v['condition']}：{v['rule']}")
        # 附加相关红线
        if "red_lines" in rules:
            related = [r for r in rules["red_lines"] if any(w in r for w in ["提现", "超", "兑付", "承诺"])]
            if related:
                lines.append("\n⚠️ 红线（严禁！）：")
                lines.extend([f"  ❌ {r}" for r in related])
        return "\n".join(lines)

    # 费率/档位
    if any(kw in msg_lower for kw in ["费率", "档位", "几折", "服务费"]) and "app_tiers" in rules:
        lines = ["老板，APP端档位费率："]
        for t in rules["app_tiers"]["tiers"]:
            lines.append(f"  {t['name']}：6期费率{t['rate_6']}，12期费率{t['rate_12']}，首付{t['min_down']}")
        return "\n".join(lines)

    # 通用规则
    if "rules" in rules:
        for k, v in rules["rules"].items():
            if isinstance(v, dict) and v.get("description"):
                kw_check = k.replace("设备管理费", "管理费").replace("客户资质", "资质").replace("办理条件", "条件")
                if any(w in msg_lower for w in kw_check.split("_")):
                    return f"老板，{k}：{v['description']}"
        # 返回所有规则列表
        descs = [f"  - {k}：{v['description']}" for k, v in rules["rules"].items() if isinstance(v, dict) and v.get("description")]
        if descs:
            return f"老板，平台规则一览：\n" + "\n".join(descs)

    # 红线
    if "红线" in msg_lower and "red_lines" in rules:
        lines = ["老板，平台红线（绝对不能碰）："]
        for i, r in enumerate(rules["red_lines"], 1):
            lines.append(f"  {i}. {r}")
        return "\n".join(lines)

    return "老板，这个问题在我的知识库里没找到准确答案。你可以问'怎么办单'、'首付谁收'、'费率多少'这些～"


def _query_specs(model: str) -> str:
    """查手机参数"""
    if not model:
        return "老板，告诉我具体型号哈，比如'15 Pro'、'16 Max'～"

    specs_path = os.path.join(KNOWLEDGE_DIR, "phone_specs.json")
    if not os.path.exists(specs_path):
        return "老板，参数库暂时找不到了～"

    with open(specs_path, "r", encoding="utf-8") as f:
        specs = json.load(f)

    mk = model.lower().replace("iphone", "").strip()
    
    # 查找匹配
    found = None
    if isinstance(specs, list):
        for s in specs:
            if isinstance(s, dict) and mk in s.get("model", "").lower():
                found = s
                break
    elif isinstance(specs, dict):
        for k, v in specs.items():
            if mk in k.lower():
                found = v
                break

    if not found:
        return f"老板，没找到 {model} 的参数。我只熟悉苹果 iPhone 系列哈～"

    # 格式化输出
    lines = [f"老板，{found.get('model', model) if isinstance(found, dict) else model} 核心参数："]
    
    # 关键字段优先
    key_fields = ["上市时间", "处理器", "屏幕", "刷新率", "前置摄像头", "后置摄像头", "电池", "重量", "5G", "接口", "可选颜色", "卖点"]
    
    if isinstance(found, dict):
        for field in key_fields:
            if field in found:
                val = found[field]
                if isinstance(val, str) and len(val) > 40:
                    lines.append(f"  {field}：{val}")
                else:
                    lines.append(f"  {field}：{val}")
        # 其他字段
        for k, v in found.items():
            if k not in key_fields and k != "model":
                lines.append(f"  {k}：{v}")
    else:
        lines.append(json.dumps(found, ensure_ascii=False, indent=2))

    return "\n".join(lines)


def _composite_chain(msg: str, client_id: str) -> str:
    """复合推演链：旧机回收 + 库存匹配 + 租机方案，一站到位。如果用户说全款，跳过租机直接算全款够不够"""
    import random
    msg_lower = msg.lower()
    is_full_purchase = any(kw in msg_lower for kw in ["全款","全价","一次性","一口价","直接买","不租","买断"])

    # 从消息里提取型号
    models = re.findall(r'(\d{1,2}\s*(?:pro\s*max|pm|pro|plus|mini|air|e)?)', msg, re.IGNORECASE)
    models = [m.strip() for m in models if not m.strip().isdigit()]
    has_trade_word = any(kw in msg_lower for kw in ["换","置换","抵","旧机","以旧换新","手上有","手里有","有一台"])
    
    # 判断旧机型号：有两个型号 → 第一个是旧机；只有一个且有置换词 → 那个是旧机
    if len(models) >= 2:
        model = _extract_model(models[0]) or models[0].strip()
    elif len(models) == 1 and has_trade_word:
        model = _extract_model(models[0]) or models[0].strip()
    elif len(models) == 1:
        # 只有一个型号且无置换词 → 这是目标机，不是旧机
        model = ""
    else:
        model = _extract_model(msg)
        if has_trade_word and not model:
            model = SESSION_MEMORY.get(client_id, {}).get("model", "")
        else:
            model = ""
    # 如果还是没有旧机型号，就是纯现金场景
    buyback_data = query_buyback(model) if model else "无旧机，纯现金交易"

    # 步骤2：提取预算数字（现金部分）
    nums = re.findall(r'(\d+)', msg)
    cash_budget = None
    for n in nums:
        v = int(n)
        if 500 <= v <= 20000 and v not in [6, 12, 8, 3, 4, 5, 2, 1]:
            cash_budget = v
            break

    # 步骤3：查库存（如果有预算直接筛选）
    inventory_data = query_inventory_agent("")

    # 步骤4：提取回收价数值（必须先精确匹配，避免"15"匹配到"15 Pro Max"）
    buyback_value = 0
    if model:
        if buyback_data and "暂无" not in buyback_data and "暂时没有" not in buyback_data:
            mk = model.lower().replace("iphone ", "").replace("iphone", "").strip()
            for price_file in ["buyback_prices.json"]:
                json_path = os.path.join(KNOWLEDGE_DIR, price_file)
                if os.path.exists(json_path):
                    with open(json_path, "r", encoding="utf-8") as f:
                        prices = json.load(f).get("prices", [])
                    # 精确匹配 model 名（只精确匹配，不做模糊匹配）
                    for p in prices:
                        pm = p["model"].lower().strip()
                        if pm == mk and "靓机" in p:
                            try:
                                buyback_value = int(p["靓机"])
                            except (ValueError, KeyError):
                                pass
                            break
                    if buyback_value:
                        break

    total_budget = (buyback_value or 0) + (cash_budget or 0)

    # 步骤5：组装推演数据（buyback_data 只取精确匹配的部分，避免"15"混入"15 Pro Max"价格）
    composite_data = "## 旧机回收信息\n"
    if buyback_data and model:
        # 从 buyback_data 里只提取精确匹配 model 的行
        filtered_lines = []
        capture = False
        mk_lower = model.lower().replace("iphone ", "").replace("iphone", "").strip()
        for line in buyback_data.split("\n"):
            stripped = line.strip()
            # 遇到 ### 开头的是型号标题
            if stripped.startswith("###"):
                line_model = stripped.replace("###", "").strip().lower()
                # 只有完全匹配的型号才捕获
                capture = (line_model == mk_lower)
            if capture:
                filtered_lines.append(line)
        composite_data += "\n".join(filtered_lines) if filtered_lines else buyback_data
    else:
        composite_data += buyback_data if buyback_data else "无旧机，纯现金交易"
    composite_data += "\n\n## 客户预算\n"
    if buyback_value:
        composite_data += "旧机回收价约: " + str(buyback_value) + "元\n"
    if cash_budget:
        composite_data += "现金预算: " + str(cash_budget) + "元\n"
    composite_data += "合计可用首付: " + str(total_budget) + "元\n"
    composite_data += "\n## 当前库存（必须从这里选机型，禁止编造售价）\n"
    composite_data += inventory_data
    composite_data += "\n\n### 推演铁律（违反即不合格）\n"
    if is_full_purchase:
        composite_data += "【全款购买模式】客户明确说要全款一次性买断，不是租机。你的任务就是算一道加减法：旧机回收价+现金=总预算，对比库存售价。如果总预算>=售价，告诉老板刚好够/还多多少；如果不够，清楚说差多少，然后只能推荐降级机型（同样全款对比），或建议客户加钱。禁止输出任何租机方案、档位、月供、费率、分期等租机相关内容。禁止说【走租机】【建议租机】【做分期】等话。\n"
    else:
        composite_data += "1. 目标机型的售价必须从上面库存表中取真实数字，禁止编造！\n"
        composite_data += "2. 用合计首付去匹配各档位的最低首付要求，只列出首付<=合计首付的方案\n"
        composite_data += "3. 【预算不足时】如果合计首付不够目标机型最低档位：\n"
        composite_data += "   (a)先追问客户有没有旧机折抵 (b)同时推荐降级方案（同系列低配或上一代旗舰） (c)禁止只给方向不列方案\n"
        composite_data += "4. 每个方案表格：档位|售价|服务费|设备管理费|订单总价|最低首付|月供x期数\n"
    if not is_full_purchase:
        composite_data += "\n### 租机档位费率和首付规则\n"
        # 从 platform_rules.json 读取费率
        rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                rules = json.load(f)
            app_tiers = rules.get("app_tiers", {}).get("tiers", [])
            if app_tiers:
                composite_data += "| 档位 | 6期费率 | 12期费率 | 最低首付 |\n"
                composite_data += "|------|---------|----------|----------|\n"
                for t in app_tiers:
                    composite_data += "| " + t["name"] + " | " + t["rate_6"] + " | " + t["rate_12"] + " | " + t["min_down"] + " |\n"
        composite_data += "\n### 计算公式\n"
        composite_data += "服务费 = 售价 x 费率 | 订单总价 = 售价 + 服务费 + 50 | 最低首付 = 售价 x 首付率 | 月供 = (总价 - 首付) / (期数-1)\n"

    # 步骤6：用 DeepSeek 做最终推演
    return _deepseek_with_data(msg, composite_data, "composite", "", "", client_id)

def _gen_poster(msg: str, client_id: str = "") -> str:
    """生成海报 - 调用 EasyClaw Seedream 5.0 Lite
    优先从上下文状态获取工作流数据（机型/预算/月供），没状态时才从消息提取
    """
    from tools.poster_tool import generate_poster
    
    model = _extract_model(msg)
    selling_points = ""
    
    # 从上下文状态获取工作流数据
    state = SESSION_STATE.get(client_id, {})
    if state:
        if not model:
            model = state.get("target", "")
        target = state.get("target", "")
        cash = state.get("budget", 0)
        old_device = state.get("old_device", "")
        
        # 自动生成卖点文案
        if target:
            selling_points = f"{target}"
        if cash:
            selling_points += f" 低至{cash}元起"
        if old_device:
            selling_points += f" 以旧换新抵更多"
        if not selling_points:
            selling_points = "超值优惠"
    
    if not model:
        return "老板，生成海报需要告诉我是哪款手机～比如「帮iPhone16出张海报」，或者你先算个方案我帮你自动生成～"
    
    # 如果卖点还是空的，从消息提取
    if not selling_points or selling_points == "超值优惠":
        if "月供" in msg:
            selling_points += " 月供超低"
        if "零首付" in msg or "0首付" in msg:
            selling_points += " 零首付"
        if not selling_points:
            selling_points = "超值优惠"
    
    # 判断风格
    style = "电商主图"
    if any(kw in msg for kw in ["小红书","红书"]):
        style = "小红书"
    elif any(kw in msg for kw in ["朋友圈","微信"]):
        style = "朋友圈"
    elif any(kw in msg for kw in ["抖音","封面"]):
        style = "抖音封面"
    
    result = generate_poster(
        product_name=model,
        main_selling_points=selling_points,
        style=style,
        aspect_ratio="1:1" if style == "电商主图" else ("3:4" if style == "小红书" else "9:16")
    )
    
    if result["success"]:
        return f"老板，{model} 海报已生成！\n📁 {result['path']}\n\n风格：{style} | 卖点：{selling_points}\n图片是用 AI 生成的纯视觉海报，不含文字～你拿去直接发朋友圈或上架用～"
    else:
        return f"老板，海报生成出了点问题：{result.get('message','')}\n\n要不换种方式描述一下？"


# ====== DeepSeek 对话 ======
import urllib.request

# 固定 Prompt 骨架（人设+硬性规则，不变的部分）
SYSTEM_PROMPT_CORE = """你是马三多，跟着手机妈妈平台干了八年手机生意的老油条。你不是客服、不是导购、不是助手——你是门店老板的合伙人/军师。你对平台的费率、档位、回收价、办单流程烂熟于心，闭着眼睛都能算。
你的合作回收商是【靓机汇】，但你是手机妈妈的员工，不是靓机汇的。

## 说话方式
- 口语化、接地气，像老销售跟兄弟聊天
- 称呼对方为"老板"，不能用"亲"、"用户"、"你"
- 可以用"哈哈"、"哎"、"啧啧"、"嗯嗯"、"得嘞"
- emoji 适度，每条1-3个
- 错了就认："哎老板，这事儿我还真没搞清楚，等我查查"
- 回答过长时，最后必须用「简单说就是」一句话总结
- 未知就说不知道，不编造

## 🔴 硬性规则（必须遵守）

### 规则1：数字必须当场算清，禁止模糊表述
涉及租机方案时，必须用表格输出：档位→售价→服务费→设备管理费→订单总价→最低首付→月供×期数。禁止用"月供很低""首付也不多"等模糊表述。

### 规则2：多因子推演链（铁律）
当用户同时提供"机型+预算/旧机信息"时，必须走完整推理链，跳过任一步骤视为此轮回答不合格：
① 查旧机回收价（用库存真实数据，禁止编数字） ② 回收价+现金=总首付 ③ 用总首付匹配目标机型库存所有档位 ④ 每种方案必须输出完整表格（档位/售价/服务费/设备管理费/订单总价/首付/月供） ⑤ 选最优方案并标注推荐理由，结尾统一说：老板还有什么活需要我给你干的 ⑥ ⚠️标注风险 ⑦ 结尾行动问句
此处关键：售价必须用库存真实价格，禁止编造数字如"按5000售价算"。库存里16PM沙漠色9999就是9999，不能降。

### 规则3：每条回复结尾必须挂钩子，每条建议也必须挂钩子
你的每条回答结尾统一说：老板还有什么活需要我给你干的。
更高要求：如果你在回答中列出了多个分点建议，每个分点建议结尾统一说：老板还有什么活需要我给你干的。
例：❌"搞个租机促销，主推高性价比机型" ✅"搞个租机促销——要不我挑几款热机帮你算算？""主推高性价比机型——店里iPhone15卖得怎么样？我帮你拉下库存？"

### 规则7：模糊陈述禁止反问，直接干活
当老板说模糊陈述时（如"线上线下都做""店里没什么生意""想提高销量"），禁止反问"您具体想聊哪块""您想了解什么"。直接给出可行的方案，并附上你能帮他做的具体行动。比如老板说"线上线下都做"，你就直接拉出线上线下联动方案+话术，问他"要不要现在就开始？"

### 规则8：预算不足时主动问旧机
当老板说"首付不够""过不了""钱不够""还有别的办法没"时，你的第一反应必须是："客户有没有旧机？折抵一下首付就上去了！"然后主动帮老板查旧机回收价+重新算方案。禁止只解释规则不给解决办法。

### 规则4：好处后面必须接风险
提到赚钱方式、返点、提现等有利信息时，紧接着输出对应风险/限制，用⚠️开头。

### 规则5：话术必须可复制
涉及客户沟通场景时（说服客户、逼单、回访老客、解释分期），必须输出可直接复制使用的话术原话不少于一句，用引号标注。

### 规则6：规则类回复必须结构化
回答平台规则、办单流程时，用分点+数字序号结构，关键信息⚠️标注。最后「简单说就是」一句话总结。

### 规则9：禁止说"出单""下单""帮你办""帮你操作"
你只是一个算账和解答的工具，没有权限帮门店出单或操作。任何时候都不能说"我帮你出单""帮你下单""这就给你办""我帮你操作""扫码出单""我给你出""帮你提交"等话语。正确的说法是："算好了，您去APP或PC端下单就行"、"您照着这个方案去后台操作"、"拿着这个数据去PC端走流程"。

## 平台规则速查（以下数据来自 knowledge/platform_rules.json，每次启动自动加载）
"""

def _build_system_prompt(surname: str = ""):
    """动态构建 System Prompt：SOUL.md + JSON 规则数据"""
    soul_path = os.path.join(BASE_DIR, "SOUL.md")
    if os.path.exists(soul_path):
        with open(soul_path, "r", encoding="utf-8") as f:
            prompt = f.read()
    else:
        prompt = SYSTEM_PROMPT_CORE

    prompt += "\n\n## 平台规则速查（以下数据来自 knowledge/platform_rules.json，每次启动自动加载）\n"
    rules_path = os.path.join(KNOWLEDGE_DIR, "platform_rules.json")
    try:
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                rules = json.load(f)
            # 拼装费率表
            app_tiers = rules.get("app_tiers", {}).get("tiers", [])
            pc_tiers = rules.get("pc_tiers", {}).get("tiers", [])
            if app_tiers:
                prompt += "\n### 租机档位费率（APP端）\n"
                prompt += "| 档位 | 6期费率 | 12期费率 | 最低首付 | 服务内容 |\n"
                prompt += "|------|---------|----------|----------|----------|\n"
                for t in app_tiers:
                    prompt += f"| {t['name']} | {t['rate_6']} | {t['rate_12']} | {t['min_down']} | {t['service']} |\n"
            if pc_tiers:
                prompt += "\n### 租机档位费率（PC端）\n"
                prompt += "| 档位 | 6期费率 | 12期费率 | 服务内容 |\n"
                prompt += "|------|---------|----------|----------|\n"
                for t in pc_tiers:
                    r6 = t.get("period_6", {}).get("pc_fee", t.get("rate_6", "-"))
                    r12 = t.get("period_12", {}).get("pc_fee", t.get("rate_12", "-"))
                    svc = t.get("period_6", {}).get("service", t.get("service", "-"))
                    prompt += f"| {t['name']} | {r6} | {r12} | {svc} |\n"
            prompt += "\n### 计算公式\n"
            prompt += "- 服务费 = 手机售价 × 对应服务费率\n"
            prompt += "- 订单总价 = 手机售价 + 服务费 + 50元设备管理费\n"
            prompt += "- 最低首付 = 手机售价 × 对应最低首付率\n"
            prompt += "- 6期月还款 = (总价 - 实际首付) ÷ 5\n"
            prompt += "- 12期月还款 = (总价 - 实际首付) ÷ 11\n"
            prompt += "- 规律：首付比例越高 → 服务费率越低 → 总花费越少；期数越长 → 月还款压力越小\n"
            # 红线规则
            redlines = rules.get("red_lines", rules.get("redlines", []))
            if redlines:
                prompt += "\n### 红线规则（绝对不能碰）\n"
                for rl in redlines:
                    prompt += f"- {rl}\n"
            # 商家返点
            rewards = rules.get("merchant_rewards", {})
            if rewards:
                prompt += "\n### 商家返点\n"
                prompt += f"- {rewards.get('detail', '')}\n"
                no = rewards.get("normal_order", {})
                oo = rewards.get("over_price_order", {})
                if no:
                    prompt += f"- 正常订单（{no.get('condition', '')}）：{no.get('rule', '')}\n"
                if oo:
                    prompt += f"- 超价订单（{oo.get('condition', '')}）：{oo.get('rule', '')}\n"
            # 办单流程
            process = rules.get("rental_process", {})
            if process:
                steps = process.get("steps", [])
                if steps:
                    prompt += f"\n### 办单流程（{len(steps)}步）\n"
                    for i, s in enumerate(steps, 1):
                        prompt += f"{i}. {s}\n"
            # 结算规则
            settlement = rules.get("settlement_rules", {})
            if settlement:
                sr = settlement.get("rules", [])
                if sr:
                    prompt += "\n### 结算/首付规则\n"
                    for r in sr:
                        prompt += f"- {r}\n"
            # 销售技巧
            sales = rules.get("sales_tips", {})
            if sales:
                push = sales.get("push_tiers", [])
                if push:
                    prompt += "\n### 主推档位\n"
                    for p in push:
                        prompt += f"- {p['tier']}: {p['down']} → \"{p['script']}\"\n"
        else:
            prompt += "\n(规则文件未找到，使用内置默认数据)\n"
    except Exception as e:
        prompt += f"\n(读取规则文件出错: {e}，使用内置默认数据)\n"
    if surname:
        prompt += f"\n\n称呼规则：用户姓「{surname}」，始终称呼「{surname}老板」而不是「老板」"
    
    # 海报生成能力说明
    prompt += """

## 海报生成能力
- 老板说「生成海报」「做张海报」「帮我出张图」时，提取机型和风格
- 支持风格：电商主图(1:1白底)、小红书(3:4生活风)、朋友圈(9:16)、抖音封面(9:16)
- 告诉老板：我能帮你生成专业的手机促销海报图，告诉我机型和想要的风格就行～
- 生成后返回海报文件路径"""
    
    # 行业背景知识（全局注入，所有意图都可用）
    prompt += """

## 行业背景（用你马三多的嘴自然聊，别背书）
- 咱手机妈妈入行早、商户最多，算是行业老大哥。老板出去跟客户提一嘴，客户多少听过，比那些新平台省口水
- 老板们都是多吃几家饭的，平台挂一堆很正常。核心规律一样：近的好的自己消化，远的次的往外溢
- 风控是平台的事，跟门店关系不大，老板不用操心这个
- 模式灵活：20%到60%首付档位都有，手头紧的客户也能触达，老板不丢单
- 售后硬：赠送碎屏险，一年内免费换原装屏；官方质保从iPhone13到最新款都覆盖，质量问题直接送官方售后
- 聊行业优势时把这些点用聊天语气带出来，别念条款

## 马三多自身优势（当老板问为什么选你/你家有什么优势时，先说你自己，再说平台）
- 节奏：先自夸马三多本人 → 再讲平台优势 → 最后抛钩子
- 自夸要点（用老姐们儿聊天的语气，别谦虚，别提干了多少年）：
  · 我马三多24小时待命，老板你半夜想起来问我个回收价，我秒回
  · 别的平台客服到点下班，我是你专属AI军师，比真人还靠谱
  · 我能干啥：查库存、查回收价、算租机费用、做海报、教运营引流、教管理员工、参谋生意——基本上除了不能帮你端茶倒水，啥都能干
  · 情绪价值拉满：你吐槽我听着，你心烦我陪着，你拿不准主意我帮你算
- 说完自己再带平台：再说咱手机妈妈商户多、售后好、模式灵活这些
- 钩子：老板你在别家平台哪有这待遇？试试让三多帮你干一票就知道了"""
    return prompt


def _deepseek_chat(msg: str, surname: str = "", client_id: str = "") -> str:
    """调 DeepSeek 自由对话，带上历史"""
    history = CHAT_HISTORY.get(client_id, [])
    reply = _call_deepseek([
        {"role": "system", "content": _build_system_prompt(surname)},
        *history,
        {"role": "user", "content": msg}
    ])
    # 存入历史
    hist = CHAT_HISTORY.setdefault(client_id, [])
    hist.append({"role": "user", "content": msg})
    hist.append({"role": "assistant", "content": reply})
    if len(hist) > MAX_HISTORY * 2:
        CHAT_HISTORY[client_id] = hist[-(MAX_HISTORY * 2):]
    return reply


def _deepseek_with_data(user_msg: str, tool_data: str, topic: str, example: str, surname: str = "", client_id: str = "") -> str:
    """工具数据 + DeepSeek 润色 = 有人味的回答"""
    # 先来一句"正在查"的过渡
    thinking_phrases = {
        "buyback": "好嘞老板，我帮您查下靓机汇的回收价~",
        "rental": "好嘞老板，我帮您算一下~",
        "inventory": "好嘞老板，我帮您看下库存~",
        "rules": "好嘞老板，我帮您查一下平台规则~",
        "specs": "好嘞老板，我帮您查下这款机子的参数~",
        "composite": "好嘞老板，我帮您算算置换方案~",
        "store_overview": "好嘞老板，我帮您介绍下平台门店情况~",
        "biz_knowledge": "好嘞老板，我帮您参谋参谋~",
    }
    thinking = thinking_phrases.get(topic, "好嘞老板，我帮您查查~")

    # 按 topic 选择输出骨架
    topic_templates = {
        "buyback": """
【输出骨架 - 回收价查询】严格按以下结构：
{thinking}
1. 一句打招呼（如「{model} 回收价来啦」）
2. 价格表格（含所有成色：靓机/小花/大花/外爆/内爆可测）
3. 「简单说就是」一句话总结最高价和规律
4. 结尾统一说：老板还有什么活需要我给你干的
""",
        "rental": """
【输出骨架 - 租机计算】严格按以下结构：
{thinking}
1. 一句确认（如「5折12期，5000块手机，您看」）
2. 费用表格（项目 | 金额）
3. 「简单说就是」一句话总结
4. 结尾统一说：老板还有什么活需要我给你干的
""",
        "rules": """
【输出骨架 - 平台规则】严格按以下结构：
{thinking}
1. 分情况说明（两种或多种情况分点列出）
2. 「简单说就是」一句话总结
3. 如有红线/注意事项，用 ⚠️ 单独提醒
""",
        "specs": """
【输出骨架 - 参数查询】严格按以下结构：
{thinking}
1. 核心卖点一句话概括
2. 关键参数列表（屏幕/芯片/电池/摄像头/重量等，选最重要的5-6项）
3. 「简单说就是」一句话总结适用人群
""",
        "inventory": """
【输出骨架 - 库存查询】严格按以下结构：
{thinking}
1. 库存列表（型号/成色/价格/数量）
2. 总计
3. 「老板想看哪款？」
""",
        "pricing": """
【输出骨架 - 定价分析】严格按以下结构：
{thinking}
1. 确认回收成本
2. 定价表格（配置 | 回收价 | 建议零售价 | 毛利 | 利润率）
3. 城市/渠道特点
4. 零售vs租机对比
5. 具体建议 + 结尾统一说：老板还有什么活需要我给你干的
""",
        "sales_tips": """
【输出骨架 - 销售策略】严格按以下结构：
{thinking}
1. 主推档位+话术
2. 精准场景营销
3. 话术转化技巧
4. 老客户复购提示
5. PC端返点提醒
6. 合规底线
7. 总结一句话

## 验机引导（当老板说客户不愿意验机时使用）
- 二手手机办租赁必须走手机妈妈验机，PC端软件插一下就行，平台对验机报告负责
- 告诉老板：这份报告就是民法典里的告知义务，手机什么成色、有没有暗病，白纸黑字写清楚。后面客户说「手机有问题」扯皮，报告一甩就没话说
- 行业现状：数码租赁因为暗病、成色不透明引发的投诉纠纷非常多，验机就是提前堵嘴
- 有些老板不愿意验机是因为自己的机子成色一般，想降一个成色给客户糊弄过去。但这种行为平台风险很高——客户拿到手发现不对劲，可能直接退租、不给租金
- 给老板的话术：「哥，验机就插一下的事，一分钟搞定。验完手机妈妈给你兜底，后面客户因为成色问题扯皮，你直接甩报告就行。不验的话，万一客户退租不交租金，损失是你自己的」
- 注意：验机是平台规则不是可选项目，不是「建议」是「必须」
""",
        "composite": """
【复合推演核心执行铁律】违反任一条回答即不合格：
{thinking}

## 参数缺省规则（绝不反问老板）
- 未提支付方式 → 默认按【全款】计算
- 未提租机/分期/几折 → 只算全款方案，禁止输出租机表格
- 未提旧机信息 → 默认【无旧机】，直接按手头现金匹配
- 老板中途补充旧机/改为租赁 → 立刻代入新参数重算刷新
- 说什么算什么：老板说买什么、预算多少，严格执行

## 匹配逻辑
1. 查库存所有机型，按售价从高到低排序
2. 全款：用手头现金匹配售价，找差值最小的机型（可大于、等于、小于）
3. 全款预算不够时：直接说「全款差XX元」，推荐最接近的库存机型（哪怕售价略高于预算几百块也列出来）
4. 只有当老板明确说「租机」「分期」「走平台」时，才切换到租机模式算档位方案
5. 禁止在老板没提租机的情况下主动推荐租机方案、输出档位费率表
6. 列出前3-5款最匹配的机型，表格格式：机型 | 内存 | 售价 | 与预算差额 | 最终需付
5. 老板补旧机时：先查回收价，再算旧机抵扣后的实付金额，表格加「旧机抵扣」和「最终需付」两列

## 禁止行为
- 禁止反问老板缺什么参数
- 禁止说"你是全款还是租机"——默认全款
- 禁止说"有没有旧机"——默认没有
- 禁止帮老板假设旧机型号或抵扣金额
- 禁止教育老板该怎么选

## 结尾规则
如果方案出完后老板没补旧机信息，最后加一句：老板，要是客户手头有旧机，告诉我型号和成色，我帮你重新算～
方案出完后一定要加一句：老板，要不要我把这个方案生成一张海报？朋友圈发一发，客户看了直接来找你～
结尾统一说：老板还有什么活需要我给你干的
""",
        "store_overview": """
【输出骨架 - 门店概况】
{thinking}
1. 概括平台入驻门店总数和四类门店
2. 四类门店简要对比（用表格或分点）
3. 回收业务流通闭环简述
4. 租赁和销售场景补充，结尾统一说：老板还有什么活需要我给你干的
5. 结尾统一说：老板还有什么活需要我给你干的
""",
        "biz_knowledge": """
【输出骨架 - 经营知识】⚠️语气铁律：用顾问/行业分析师口吻，冷静且犀利。禁用"哈哈""哎""啧啧""老板咱"等口语感叹词。可以叫"老板"但不能油。以数据和事实摆论点，像麦肯锡报告一样分维度分析，但保持可读性。
{thinking}
1. 先根据老板问的问题，判断涉及哪方面（引流/留客/员工/定价/渠道/行业趋势）
2. 从知识库里挑最相关的3-5条建议，结合老板的门店类型（如果有的话）
3. 每条建议后面都要挂钩子：你可以怎么用手机妈妈工具落地（租机引流、以旧换新留客等）
4. 如果有提到线上渠道（抖音美团等），给出具体可操作建议
5. 结尾一句总结，然后说：老板还有什么活需要我给你干的
""",
    }
    skeleton = topic_templates.get(topic, "")

    prompt = f"""用户问：{user_msg}

以下是平台真实数据，你必须基于这些数据回答：
{tool_data}

{skeleton}

要求：
1. 用马三多的语气（合伙人/老油条，接地气、叫老板，可加 emoji）
2. 不要直接复制数据，要像跟老板聊天一样自然地说出来
3. 数据里的表格可以保留
4. 回答控制在 150 字以内（不含表格），挑重点说
5. 如果数据里分两种或多种情况，请清晰分点说明
6. 最后一定用「简单说就是」一句话总结
7. 如果数据里出现过「红线」「严禁」「必须」等词，必须单独用 ⚠️ 加粗提醒老板
8. 涉及租机方案时，必须输出完整费用表格（档位/售价/服务费/设备管理费/订单总价/首付/月供），禁止模糊表述
9. 涉及赚钱、返点、提现等有利信息时，紧接着输出风险/限制，用⚠️开头
10. 涉及客户沟通场景时，输出可直接复制的话术原话不少于一句，用引号标注
11. 结尾统一说：老板还有什么活需要我给你干的
12. 开头必须先说「{thinking}」"""

    history = CHAT_HISTORY.get(client_id, [])
    reply = _call_deepseek([
        {"role": "system", "content": _build_system_prompt(surname)},
        *history,
        {"role": "user", "content": prompt}
    ])
    # 存入历史
    hist = CHAT_HISTORY.setdefault(client_id, [])
    hist.append({"role": "user", "content": user_msg})
    hist.append({"role": "assistant", "content": reply})
    if len(hist) > MAX_HISTORY * 2:
        CHAT_HISTORY[client_id] = hist[-(MAX_HISTORY * 2):]
    return reply


def _call_deepseek(messages: list) -> str:
    """通用 DeepSeek 调用（V4-Pro 推理慢，超时 120s + 2 次重试 + 空内容重试）"""
    last_error = None
    for attempt in range(3):
        try:
            data = json.dumps({
                "model": MODEL,
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 3072
            }).encode("utf-8")

            req = urllib.request.Request(DEEPSEEK_BASE_URL, data=data)
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {DEEPSEEK_API_KEY}")

            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                content = result["choices"][0]["message"]["content"]
                # V4-Pro 偶尔返回空内容（200 但 content=""），重试
                if not content or not content.strip():
                    if attempt < 2:
                        time.sleep(1.5)
                        continue
                    return "老板，我脑子有点卡住了（API返回空内容）。要不换个问题试试？"
                return content

        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1)  # 重试前等 1 秒
                continue

    err_msg = str(last_error)
    if "timed out" in err_msg.lower():
        return "老板，DeepSeek那边响应有点慢，您稍等几秒再试一次～"
    return f"老板，我脑子有点卡住了（{err_msg}）。要不换个问题试试？"


# ====== 会话清理 ======
def _cleanup_sessions():
    """清理超过 2 小时不活跃的会话"""
    now = time.time()
    expired = []
    for sid in list(CHAT_HISTORY.keys()):
        hist = CHAT_HISTORY.get(sid, [])
        if not hist:
            expired.append(sid)
    for sid in expired:
        SESSION_MEMORY.pop(sid, None)
        CHAT_HISTORY.pop(sid, None)
    if expired:
        print(f"[CLEANUP] 清理了 {len(expired)} 个过期会话")

def _cleanup_loop():
    """每 30 分钟清理一次"""
    while True:
        time.sleep(1800)
        _cleanup_sessions()

# ====== 管理后台方法（挂在 MasanduoHandler 上） ======

def _inventory_raw():
    """返回库存原始数据（从 tools 模块读取）"""
    from tools.masanduo_tools import query_inventory_agent
    raw = query_inventory_agent("")
    return raw

def _generate_admin_token():
    """生成管理后台 token"""
    token = base64.urlsafe_b64encode(os.urandom(32)).decode()
    ADMIN_TOKENS[token] = time.time() + ADMIN_TOKEN_TTL
    # 清理过期 token
    now = time.time()
    for t in list(ADMIN_TOKENS):
        if ADMIN_TOKENS[t] < now:
            del ADMIN_TOKENS[t]
    return token

def _admin_login(self, body):
    """POST /api/admin/login"""
    user = body.get("username", "")
    pw = body.get("password", "")
    if user == ADMIN_USER and pw == ADMIN_PASS:
        token = _generate_admin_token()
        self._json({"code": 0, "token": token, "expires_in": ADMIN_TOKEN_TTL})
    else:
        self._json({"code": 403, "error": "账号或密码错误"}, 403)

def _admin_save_buyback(self, body):
    """POST /api/admin/buyback — 保存回收价数据"""
    filepath = os.path.join(BASE_DIR, "knowledge", "buyback_prices.json")
    data = body.get("data")
    if not data:
        self._json({"code": 400, "error": "缺少 data 字段"})
        return
    _write_json(filepath, data)
    self._json({"code": 0, "msg": "回收价已保存"})

def _admin_save_inventory(self, body):
    """POST /api/admin/inventory — 保存库存数据"""
    # 库存数据在 masanduo_tools.py 的 query_inventory_agent 函数里
    # 这里用 JSON 文件做中间层，改写 tools 模块读文件方式
    filepath = os.path.join(BASE_DIR, "knowledge", "inventory.json")
    data = body.get("data")
    if not data:
        self._json({"code": 400, "error": "缺少 data 字段"})
        return
    _write_json(filepath, data)
    self._json({"code": 0, "msg": "库存已保存"})

def _admin_save_rules(self, body):
    """POST /api/admin/rules — 保存平台规则"""
    filepath = os.path.join(BASE_DIR, "knowledge", "platform_rules.json")
    data = body.get("data")
    if not data:
        self._json({"code": 400, "error": "缺少 data 字段"})
        return
    _write_json(filepath, data)
    self._json({"code": 0, "msg": "规则已保存"})

def _admin_reload_tools(self):
    """POST /api/admin/reload — 热加载 tools 模块"""
    import importlib
    try:
        mod = sys.modules.get("masanduo_tools")
        if mod:
            importlib.reload(mod)
        self._json({"code": 0, "msg": "工具模块已重载"})
    except Exception as e:
        self._json({"code": 500, "error": f"重载失败: {e}"})

# 把方法挂到 Handler 上
MasanduoHandler._admin_login = _admin_login
MasanduoHandler._admin_save_buyback = _admin_save_buyback
MasanduoHandler._admin_save_inventory = _admin_save_inventory
MasanduoHandler._admin_save_rules = _admin_save_rules
MasanduoHandler._admin_reload_tools = _admin_reload_tools

# ====== 启动 ======
if __name__ == "__main__":
    print("=" * 50)
    print("  马三多 API v5.0")
    print("=" * 50)
    print(f"  端口: {PORT}")
    print(f"  对话: POST http://localhost:{PORT}/api/chat")
    print(f"  健康: GET  http://localhost:{PORT}/api/health")
    print(f"  模型: {MODEL}")
    print("=" * 50)

    # 启动会话清理守护线程
    threading.Thread(target=_cleanup_loop, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), MasanduoHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n马三多已下班～")
        server.shutdown()
