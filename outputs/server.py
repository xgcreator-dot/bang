"""Local, persistent demo server for the Bid Intelligence Suite."""
from __future__ import annotations

import json
import hashlib
import hmac
from email.utils import parsedate_to_datetime
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / "work" / "bid_suite.sqlite3"
DB.parent.mkdir(parents=True, exist_ok=True)
PORT = 8765
SESSIONS = {}
SESSION_TTL = 60 * 60 * 24 * 7


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240_000).hex()
    return salt + "$" + digest


def check_password(password, stored):
    try:
        salt, expected = stored.split("$", 1)
        actual = password_hash(password, salt).split("$", 1)[1]
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def normalize_published_date(value):
    raw=(value or "").strip()
    if not raw:
        return ""
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}",raw):
            return datetime.fromisoformat(raw.replace("Z","+00:00")).date().isoformat()
        return parsedate_to_datetime(raw).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return raw[:10]


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS notices(
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, unit TEXT DEFAULT '',
          region TEXT DEFAULT '', type TEXT DEFAULT '', budget TEXT DEFAULT '', deadline TEXT DEFAULT '',
          source TEXT DEFAULT '', kind TEXT DEFAULT '招标公告', status TEXT DEFAULT '报名中',
          published_at TEXT DEFAULT '', source_url TEXT DEFAULT '', source_url_status TEXT DEFAULT 'missing', description TEXT DEFAULT '',
          collected_at TEXT NOT NULL, updated_at TEXT NOT NULL, source_notice_id TEXT DEFAULT '',
          UNIQUE(source, source_notice_id));
        CREATE TABLE IF NOT EXISTS sources(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, feed_url TEXT NOT NULL,
          allowed_host TEXT NOT NULL, category TEXT DEFAULT '招标公告', enabled INTEGER DEFAULT 1,
          platform_id INTEGER, last_checked TEXT DEFAULT '', last_status TEXT DEFAULT '未运行', last_error TEXT DEFAULT '',
          FOREIGN KEY(platform_id) REFERENCES platforms(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS platforms(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, homepage_url TEXT NOT NULL,
          region TEXT DEFAULT '全国', categories TEXT DEFAULT '', access_method TEXT DEFAULT '待核验',
          policy_note TEXT DEFAULT '', review_status TEXT DEFAULT '待核验', enabled INTEGER DEFAULT 0,
          last_reviewed TEXT DEFAULT '', last_seen TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, source_id INTEGER,
          cadence TEXT DEFAULT '手动运行', enabled INTEGER DEFAULT 1, last_run TEXT DEFAULT '',
          last_status TEXT DEFAULT '待运行', added_count INTEGER DEFAULT 0,
          FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS members(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT DEFAULT '',
          level TEXT DEFAULT '基础版', status TEXT DEFAULT '正常', created_at TEXT NOT NULL,
          expires_at TEXT DEFAULT '', logins INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS member_auth(
          member_id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT NOT NULL);
        """)
        notice_cols={r[1] for r in db.execute("PRAGMA table_info(notices)")}
        if "description" not in notice_cols:
            db.execute("ALTER TABLE notices ADD COLUMN description TEXT DEFAULT ''")
        source_cols={r[1] for r in db.execute("PRAGMA table_info(sources)")}
        if "platform_id" not in source_cols:
            db.execute("ALTER TABLE sources ADD COLUMN platform_id INTEGER")
        if db.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 0:
            seed = [
              ("国家重点实验室科研仪器设备更新采购项目","中国科学院·先进技术研究院","北京市","政府采购","¥ 2,860 万","2026-11-12","中国政府采购网","招标公告","报名中","2026-11-04","","missing","DEMO-0001"),
              ("智慧园区综合管理平台建设项目（一期）","杭州市滨江区城市建设发展有限公司","浙江省","工程建设","¥ 1,240 万","2026-11-06","浙江省公共资源交易中心","招标公告","即将截止","2026-11-04","","missing","DEMO-0002"),
              ("2026年度医疗设备及耗材集中采购意向公告","上海市第六人民医院","上海市","医疗卫生","¥ 3,500 万","2026-12-01","中国政府采购网","采购意向","意向公开","2026-11-04","","missing","DEMO-0003"),
              ("省级政务云平台扩容与安全运维服务项目","广东省政务服务和数据管理局","广东省","政府采购","¥ 986 万","2026-11-18","中国政府采购网","招标公告","报名中","2026-11-03","","missing","DEMO-0004"),
              ("城市快速路东延段工程施工总承包招标公告","南京市公共工程建设中心","江苏省","工程建设","¥ 8.62 亿","2026-11-14","全国公共资源交易平台","招标公告","报名中","2026-11-03","","missing","DEMO-0005"),
            ]
            stamp = now()
            db.executemany("""INSERT INTO notices(title,unit,region,type,budget,deadline,source,kind,status,published_at,source_url,source_url_status,source_notice_id,collected_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", [x[:12]+(x[12],stamp,stamp) for x in seed])
        if db.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0:
            db.executemany("INSERT INTO members(name,phone,level,status,created_at,expires_at,logins) VALUES(?,?,?,?,?,?,?)", [
              ("王晓明","138****2601","企业版","正常","2025-08-12","2027-08-11",24),
              ("陈女士","139****5816","专业版","正常","2025-10-03","2026-11-30",18),
              ("李建国","186****0927","专业版","即将到期","2024-11-22","2026-11-15",9)])
        if db.execute("SELECT COUNT(*) FROM member_auth").fetchone()[0] == 0:
            demo = db.execute("SELECT id FROM members WHERE phone='13800000000'").fetchone()
            if not demo:
                cur = db.execute("INSERT INTO members(name,phone,level,status,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                                 ("演示会员","13800000000","专业版","正常",now()[:10],""))
                member_id = cur.lastrowid
            else:
                member_id = demo["id"]
            db.execute("INSERT OR IGNORE INTO member_auth(member_id,phone,password_hash) VALUES(?,?,?)",
                       (member_id,"13800000000",password_hash("BidDemo123!")))
        if db.execute("SELECT COUNT(*) FROM platforms").fetchone()[0] == 0:
            stamp=now()
            db.executemany("INSERT INTO platforms(name,homepage_url,region,categories,access_method,policy_note,review_status,created_at) VALUES(?,?,?,?,?,?,?,?)",[
              ("中国招标投标公共服务平台","https://www.cebpubservice.com/","全国","招标公告、资格预审、中标公示、更正公告","官方平台目录 / 待核验接口","优先确认官方数据接口与发布媒介目录接入条件","待核验",stamp),
              ("中国政府采购网","https://www.ccgp.gov.cn/","全国","政府采购公告、采购意向、结果公告","官方数据接口 / 待申请","按官网当前接口规范及申请流程核验第三方获取权限","待核验",stamp),
              ("全国公共资源交易平台","https://www.ggzy.gov.cn/","全国","工程建设、政府采购、公共资源交易","官方平台目录 / 待核验接口","逐类核验数据服务范围、调用权限和来源公告直达地址","待核验",stamp),
              ("全国公共资源交易平台数据服务","https://data.ggzy.gov.cn/","全国","公共资源交易结果数据","官方数据服务 / 待核验","确认可用字段、时间范围、查询方式及数据使用条件","待核验",stamp)])
        if db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0:
            db.executemany("INSERT INTO sources(name,feed_url,allowed_host,category) VALUES(?,?,?,?)", [
              ("示例 RSS 来源（请替换为获准使用的公开 feed）","https://example.org/notices.xml","example.org","招标公告")])
            sid = db.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
            db.execute("INSERT INTO tasks(name,source_id,cadence) VALUES(?,?,?)", ("示例 RSS 采集任务",sid,"手动运行"))


def notice_dict(row):
    x = dict(row)
    x["date"] = (x.get("published_at") or "")[-5:].replace("-", "-")
    x["sourceUrl"] = x.get("source_url") or ""
    return x


def safe_host(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("仅允许 HTTPS 来源链接")
    return parsed.hostname.lower()


def fetch_feed(source):
    url = source["feed_url"]
    host = safe_host(url)
    if host != source["allowed_host"].lower():
        raise ValueError("Feed 域名与已登记来源域名不一致")
    req = urllib.request.Request(url, headers={"User-Agent": "BidSuiteDemo/1.0 (public RSS/Atom feed reader)"})
    with urllib.request.urlopen(req, timeout=20) as response:
        final_url = response.geturl()
        if safe_host(final_url) != host:
            raise ValueError("Feed 跳转到了未登记域名，已阻止")
        payload = response.read(5_000_001)
        if len(payload) > 5_000_000:
            raise ValueError("Feed 超过 5MB 限制")
    root = ET.fromstring(payload)
    items = root.findall(".//item")
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//a:entry", ns)
    out = []
    for item in items[:100]:
        def child_text(names):
            for name in names:
                el = item.find(name)
                if el is not None and el.text:
                    return el.text.strip()
            return ""
        title = child_text(["title", "{http://www.w3.org/2005/Atom}title"])
        link_el = item.find("link")
        if link_el is None:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        if not link:
            continue
        link = urllib.parse.urljoin(url, link)
        if safe_host(link) != host:
            continue
        pub = normalize_published_date(child_text(["pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"]))
        ident = child_text(["guid", "id", "{http://www.w3.org/2005/Atom}id"]) or link
        desc = child_text(["description", "summary", "{http://www.w3.org/2005/Atom}summary"])
        out.append({"title": title or "（无标题）", "source_url": link, "source_notice_id": ident,
                    "published_at": pub, "description": re.sub(r"<[^>]+>", " ", desc)[:1200]})
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def member_id(self):
        raw = self.headers.get("Cookie", "")
        token = ""
        for part in raw.split(";"):
            key, sep, value = part.strip().partition("=")
            if sep and key == "bid_session":
                token = value
                break
        session = SESSIONS.get(token)
        if not session:
            return None
        member_id, expires = session
        if expires < time.time():
            SESSIONS.pop(token, None)
            return None
        with connect() as db:
            active=db.execute("SELECT status,expires_at FROM members WHERE id=?",(member_id,)).fetchone()
        if not active or active["status"] not in ("正常","即将到期") or (active["expires_at"] and active["expires_at"]<now()[:10]):
            SESSIONS.pop(token, None)
            return None
        return member_id

    def is_local_operator(self):
        address=self.client_address[0].lower()
        return address in ("127.0.0.1","::1") or address.startswith("::ffff:127.")

    def send_json(self, payload, status=200, extra_headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(min(length, 1_000_000)) or b"{}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/members.html","/maintenance.html","/collection.html") and not self.is_local_operator():
            return self.send_json({"error":"管理平台仅允许在部署电脑上打开"},403)
        if path in ("/api/tasks","/api/members","/api/status") and not self.is_local_operator():
            return self.send_json({"error":"管理接口仅允许在部署电脑本机访问"},403)
        if path == "/api/session":
            member_id = self.member_id()
            if not member_id:
                return self.send_json({"authenticated":False})
            with connect() as db:
                row = db.execute("SELECT id,name,level FROM members WHERE id=?", (member_id,)).fetchone()
            return self.send_json({"authenticated":bool(row),"member":dict(row) if row else None})
        if path == "/api/status":
            with connect() as db:
                stats={"notices":db.execute("SELECT COUNT(*) FROM notices").fetchone()[0],
                       "members":db.execute("SELECT COUNT(*) FROM members").fetchone()[0],
                       "sources":db.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                       "enabled_sources":db.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0],
                       "tasks":db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                       "enabled_tasks":db.execute("SELECT COUNT(*) FROM tasks WHERE enabled=1").fetchone()[0],
                       "platforms":db.execute("SELECT COUNT(*) FROM platforms").fetchone()[0],
                       "verified_platforms":db.execute("SELECT COUNT(*) FROM platforms WHERE enabled=1").fetchone()[0]}
                logs=db.execute("SELECT action,detail,created_at FROM audit ORDER BY id DESC LIMIT 12").fetchall()
            stats["database_bytes"]=DB.stat().st_size if DB.exists() else 0
            stats["checked_at"]=now()
            return self.send_json({"stats":stats,"logs":[dict(x) for x in logs]})
        if path == "/api/notices":
            with connect() as db:
                rows = db.execute("SELECT * FROM notices ORDER BY published_at DESC,id DESC LIMIT 500").fetchall()
            items = [notice_dict(x) for x in rows]
            if not self.member_id():
                for item in items:
                    item["source_url"] = ""
                    item["sourceUrl"] = ""
            return self.send_json(items)
        if path == "/api/tasks":
            with connect() as db:
                rows = db.execute("""SELECT t.*,s.name source_name FROM tasks t LEFT JOIN sources s ON s.id=t.source_id ORDER BY t.id DESC""").fetchall()
                sources = db.execute("SELECT * FROM sources ORDER BY id").fetchall()
                counts = db.execute("SELECT COUNT(*) total, COALESCE(SUM(CASE WHEN source_url_status='valid' THEN 1 ELSE 0 END),0) linked, COALESCE(SUM(CASE WHEN date(collected_at)=date('now','localtime') THEN 1 ELSE 0 END),0) today FROM notices").fetchone()
            return self.send_json({"tasks":[dict(x) for x in rows],"sources":[dict(x) for x in sources],"notices":dict(counts)})
        if path == "/api/members":
            with connect() as db:
                rows = db.execute("SELECT * FROM members ORDER BY id DESC").fetchall()
            return self.send_json([dict(x) for x in rows])
        if path == "/api/platforms":
            with connect() as db:
                rows=db.execute("SELECT p.*,COUNT(s.id) connector_count FROM platforms p LEFT JOIN sources s ON s.platform_id=p.id GROUP BY p.id ORDER BY p.id").fetchall()
            return self.send_json([dict(x) for x in rows])
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if not self.is_local_operator() and (path in ("/api/notices","/api/sources","/api/platforms","/api/tasks","/api/members") or path.startswith("/api/tasks/")):
                return self.send_json({"error":"管理接口仅允许在部署电脑本机访问"},403)
            data = self.body()
            with connect() as db:
                if path == "/api/login":
                    phone=(data.get("phone") or "").strip()
                    password=data.get("password") or ""
                    row=db.execute("SELECT m.id,m.name,m.status,a.password_hash FROM member_auth a JOIN members m ON m.id=a.member_id WHERE a.phone=?",(phone,)).fetchone()
                    if not row or row["status"] not in ("正常","即将到期") or not check_password(password,row["password_hash"]):
                        return self.send_json({"error":"手机号、密码不正确，或账号已停用"},401)
                    token=secrets.token_urlsafe(32)
                    SESSIONS[token]=(row["id"],time.time()+SESSION_TTL)
                    db.execute("UPDATE members SET logins=logins+1 WHERE id=?",(row["id"],))
                    db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("会员登录",row["name"],now()))
                    return self.send_json({"ok":True,"member":{"id":row["id"],"name":row["name"]}},extra_headers={"Set-Cookie":f"bid_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}"})
                if path == "/api/register":
                    name=(data.get("name") or "").strip(); phone=(data.get("phone") or "").strip(); password=data.get("password") or ""
                    if not name or not re.fullmatch(r"1[3-9]\d{9}",phone) or len(password)<8:
                        return self.send_json({"error":"请填写姓名、有效的 11 位手机号，密码至少 8 位"},400)
                    cur=db.execute("INSERT INTO members(name,phone,level,status,created_at) VALUES(?,?,?,'正常',?)",(name,phone,"基础版",now()[:10]))
                    member_id=cur.lastrowid
                    db.execute("INSERT INTO member_auth(member_id,phone,password_hash) VALUES(?,?,?)",(member_id,phone,password_hash(password)))
                    token=secrets.token_urlsafe(32); SESSIONS[token]=(member_id,time.time()+SESSION_TTL)
                    db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("会员注册",phone,now()))
                    return self.send_json({"ok":True,"member":{"id":member_id,"name":name}},extra_headers={"Set-Cookie":f"bid_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}"})
                if path == "/api/logout":
                    raw=self.headers.get("Cookie","")
                    for part in raw.split(";"):
                        key,sep,value=part.strip().partition("=")
                        if sep and key=="bid_session": SESSIONS.pop(value,None)
                    return self.send_json({"ok":True},extra_headers={"Set-Cookie":"bid_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})
                if path == "/api/notices":
                    title = (data.get("title") or "").strip()
                    if not title:
                        return self.send_json({"error":"项目标题必填"},400)
                    url = (data.get("source_url") or "").strip()
                    status = "missing"
                    if url:
                        host = safe_host(url)
                        source = db.execute("SELECT * FROM sources WHERE lower(allowed_host)=? AND enabled=1",(host,)).fetchone()
                        if not source:
                            return self.send_json({"error":"原文链接域名未登记在启用来源中"},400)
                        status = "valid"
                    stamp=now()
                    values=[title,data.get("unit",""),data.get("region",""),data.get("type",""),data.get("budget",""),data.get("deadline",""),data.get("source",""),data.get("kind","招标公告"),data.get("status","报名中"),data.get("published_at",stamp[:10]),url,status,data.get("source_notice_id",""),data.get("description",""),stamp,stamp]
                    if values[12]:
                        db.execute("""INSERT INTO notices(title,unit,region,type,budget,deadline,source,kind,status,published_at,source_url,source_url_status,source_notice_id,description,collected_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,source_notice_id) DO UPDATE SET title=excluded.title,unit=excluded.unit,region=excluded.region,type=excluded.type,budget=excluded.budget,deadline=excluded.deadline,kind=excluded.kind,status=excluded.status,published_at=excluded.published_at,source_url=excluded.source_url,source_url_status=excluded.source_url_status,description=excluded.description,updated_at=excluded.updated_at""",values)
                    else:
                        db.execute("""INSERT INTO notices(title,unit,region,type,budget,deadline,source,kind,status,published_at,source_url,source_url_status,source_notice_id,description,collected_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",values)
                    db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("保存公告",title,stamp))
                    return self.send_json({"ok":True,"source_url_status":status})
                if path == "/api/sources":
                    name=(data.get("name") or "").strip(); url=(data.get("feed_url") or "").strip()
                    if not name or not url: return self.send_json({"error":"来源名称和 Feed URL 必填"},400)
                    host=safe_host(url)
                    db.execute("INSERT INTO sources(name,feed_url,allowed_host,category,platform_id) VALUES(?,?,?,?,?)",(name,url,host,data.get("category","招标公告"),data.get("platform_id") or None))
                    db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("新增来源",name,now()))
                    return self.send_json({"ok":True})
                if path == "/api/platforms":
                    name=(data.get("name") or "").strip(); url=(data.get("homepage_url") or "").strip()
                    if not name or not url: return self.send_json({"error":"平台名称与官网地址必填"},400)
                    safe_host(url)
                    db.execute("INSERT INTO platforms(name,homepage_url,region,categories,access_method,policy_note,review_status,created_at) VALUES(?,?,?,?,?,?,?,?)",(name,url,data.get("region","全国"),data.get("categories",""),data.get("access_method","待核验"),data.get("policy_note",""),"待核验",now()))
                    db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("登记公开平台",name,now()))
                    return self.send_json({"ok":True})
                if path == "/api/tasks":
                    name=(data.get("name") or "").strip(); source_id=data.get("source_id")
                    if not name or not source_id: return self.send_json({"error":"任务名称和来源必填"},400)
                    db.execute("INSERT INTO tasks(name,source_id,cadence) VALUES(?,?,?)",(name,source_id,data.get("cadence","手动运行")))
                    return self.send_json({"ok":True})
                if path.startswith("/api/tasks/") and path.endswith("/run"):
                    task_id=int(path.split("/")[3])
                    task=db.execute("SELECT t.*,s.name AS feed_source_name,s.feed_url,s.allowed_host,s.category,s.enabled AS source_enabled,s.platform_id,p.enabled AS platform_enabled,p.review_status AS platform_review_status FROM tasks t JOIN sources s ON s.id=t.source_id LEFT JOIN platforms p ON p.id=s.platform_id WHERE t.id=?",(task_id,)).fetchone()
                    if not task: return self.send_json({"error":"未找到任务"},404)
                    if not task["enabled"] or not task["source_enabled"]: return self.send_json({"error":"来源或任务已停用"},400)
                    if not task["platform_id"] or not task["platform_enabled"]: return self.send_json({"error":"该平台尚未完成来源规则核验和启用，暂不能采集"},400)
                    try:
                        fetched=fetch_feed(task)
                        added=0; stamp=now()
                        for item in fetched:
                            title=item["title"]
                            db.execute("""INSERT INTO notices(title,source,kind,published_at,source_url,source_url_status,source_notice_id,description,collected_at,updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,source_notice_id) DO UPDATE SET title=excluded.title,published_at=excluded.published_at,source_url=excluded.source_url,source_url_status='valid',description=excluded.description,updated_at=excluded.updated_at""",
                              (title,task["feed_source_name"],task["category"],item["published_at"],item["source_url"],"valid",item["source_notice_id"],item["description"],stamp,stamp))
                            if db.execute("SELECT changes()").fetchone()[0]: added+=1
                        db.execute("UPDATE tasks SET last_run=?,last_status=?,added_count=? WHERE id=?",(stamp,f"完成 · 读取 {len(fetched)} 条",added,task_id))
                        db.execute("UPDATE sources SET last_checked=?,last_status=?,last_error='' WHERE id=?",(stamp,"运行正常",task["source_id"]))
                        db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("运行采集任务",task["name"]+f" · {added} 条更新",stamp))
                        return self.send_json({"ok":True,"read":len(fetched),"upserted":added})
                    except Exception as exc:
                        stamp=now(); err=str(exc)[:500]
                        db.execute("UPDATE tasks SET last_run=?,last_status=? WHERE id=?",(stamp,"异常 · "+err,task_id))
                        db.execute("UPDATE sources SET last_checked=?,last_status=?,last_error=? WHERE id=?",(stamp,"异常",err,task["source_id"]))
                        return self.send_json({"error":err},400)
                if path == "/api/members":
                    name=(data.get("name") or "").strip(); phone=(data.get("phone") or "").strip()
                    password=data.get("password") or ""
                    if not name or not re.fullmatch(r"1[3-9]\d{9}",phone) or len(password)<8: return self.send_json({"error":"请填写姓名、有效的 11 位手机号和至少 8 位初始密码"},400)
                    cur=db.execute("INSERT INTO members(name,phone,level,status,created_at,expires_at) VALUES(?,?,?,?,?,?)",(name,phone,data.get("level","基础版"),"正常",now()[:10],data.get("expires_at","")))
                    db.execute("INSERT INTO member_auth(member_id,phone,password_hash) VALUES(?,?,?)",(cur.lastrowid,phone,password_hash(password)))
                    db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("新增会员",phone,now()))
                    return self.send_json({"ok":True})
            return self.send_json({"error":"未找到接口"},404)
        except (ValueError, json.JSONDecodeError, sqlite3.IntegrityError) as exc:
            return self.send_json({"error":str(exc)},400)

    def do_PATCH(self):
        path=urllib.parse.urlparse(self.path).path
        try:
            if not self.is_local_operator(): return self.send_json({"error":"管理接口仅允许在部署电脑本机访问"},403)
            data=self.body()
            if path.startswith("/api/members/"):
                member_id=int(path.split("/")[3])
                with connect() as db:
                    row=db.execute("SELECT id,name FROM members WHERE id=?",(member_id,)).fetchone()
                    if not row: return self.send_json({"error":"未找到会员"},404)
                    allowed={"level","status","expires_at"}
                    updates={k:v for k,v in data.items() if k in allowed}
                    if not updates: return self.send_json({"error":"没有可更新的会员字段"},400)
                    if "level" in updates and updates["level"] not in ("基础版","专业版","企业版"):
                        return self.send_json({"error":"会员等级无效"},400)
                    if "status" in updates and updates["status"] not in ("正常","即将到期","已停用"):
                        return self.send_json({"error":"会员状态无效"},400)
                    assignments=",".join(f"{key}=?" for key in updates)
                    db.execute(f"UPDATE members SET {assignments} WHERE id=?",(*updates.values(),member_id))
                    db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("更新会员",row["name"],now()))
                return self.send_json({"ok":True})
            if path.startswith("/api/platforms/"):
                platform_id=int(path.split("/")[3]); stamp=now()
                with connect() as db:
                    db.execute("UPDATE platforms SET review_status=?,enabled=?,last_reviewed=? WHERE id=?",(data.get("review_status","已核验待接入"),1 if data.get("enabled") else 0,stamp,platform_id))
                    if not db.execute("SELECT changes()").fetchone()[0]: return self.send_json({"error":"未找到平台"},404)
                return self.send_json({"ok":True})
            if path.startswith("/api/tasks/"):
                task_id=int(path.split("/")[3]); enabled=1 if data.get("enabled") else 0
                with connect() as db:
                    db.execute("UPDATE tasks SET enabled=? WHERE id=?",(enabled,task_id))
                    if not db.execute("SELECT changes()").fetchone()[0]: return self.send_json({"error":"未找到任务"},404)
                return self.send_json({"ok":True})
            return self.send_json({"error":"未找到接口"},404)
        except Exception as exc: return self.send_json({"error":str(exc)},400)


def scheduler_loop():
    """Run only explicitly enabled tasks on a bounded user-selected cadence."""
    while True:
        time.sleep(30)
        try:
            with connect() as db:
                tasks=db.execute("""SELECT t.id,t.cadence,t.last_run FROM tasks t
                  JOIN sources s ON s.id=t.source_id JOIN platforms p ON p.id=s.platform_id
                  WHERE t.enabled=1 AND s.enabled=1 AND p.enabled=1""").fetchall()
            stamp=datetime.now(timezone.utc).astimezone()
            for task in tasks:
                cadence=task["cadence"] or ""
                if "30" in cadence and "分" in cadence: interval=1800
                elif "小时" in cadence: interval=3600
                elif "每日" in cadence or "天" in cadence: interval=86400
                else: continue
                try: last=datetime.fromisoformat(task["last_run"]) if task["last_run"] else None
                except ValueError: last=None
                if last and (stamp-last).total_seconds()<interval: continue
                req=urllib.request.Request(f"http://127.0.0.1:{PORT}/api/tasks/{task['id']}/run",data=b"{}",headers={"Content-Type":"application/json"},method="POST")
                try:
                    with urllib.request.urlopen(req,timeout=30): pass
                except Exception as exc:
                    print(f"定时采集任务 {task['id']} 失败：{exc}")
        except Exception as exc:
            print(f"采集调度器暂不可用：{exc}")


if __name__ == "__main__":
    init_db()
    print(f"标讯通本机平台：http://127.0.0.1:{PORT}")
    print(f"同一局域网内的手机可使用本机 IPv4 地址访问，端口：{PORT}（管理接口仅限部署电脑）")
    print(f"SQLite 数据库：{DB}")
    threading.Thread(target=scheduler_loop,daemon=True,name="bid-collector-scheduler").start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
