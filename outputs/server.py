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
import json
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / "work" / "bid_suite.sqlite3"
DB.parent.mkdir(parents=True, exist_ok=True)
PORT = 8765
SESSIONS = {}
SESSION_TTL = 60 * 60 * 24 * 7
LAST_FETCH_BY_HOST = {}
FETCH_GUARD = threading.Lock()

# Candidate URLs are taken from official public-resource platform link directories;
# every platform remains disabled until an operator checks its current terms.
PROVINCIAL_PLATFORMS = [
    ("北京市公共资源交易服务平台", "https://ggzyfw.beijing.gov.cn/", "北京市"),
    ("天津市公共资源交易网", "https://ggzy.zwfwb.tj.gov.cn/", "天津市"),
    ("上海市公共资源交易平台", "https://www.shggzy.com/", "上海市"),
    ("重庆市公共资源交易网", "https://www.cqggzy.com/", "重庆市"),
    ("河北省公共资源交易平台", "https://szj.hebei.gov.cn/", "河北省"),
    ("山西省公共资源交易平台", "https://prec.sxzwfw.gov.cn/", "山西省"),
    ("内蒙古公共资源交易网", "https://ggzyjy.nmg.gov.cn/", "内蒙古自治区"),
    ("辽宁省公共资源交易网", "https://www.lnggzy.gov.cn/", "辽宁省"),
    ("吉林省公共资源交易信息网", "https://ggzyjy.jl.gov.cn/", "吉林省"),
    ("黑龙江省公共资源交易网", "https://ggzyjyw.hlj.gov.cn/", "黑龙江省"),
    ("江苏省公共资源交易网", "https://jsggzy.jszwfw.gov.cn/", "江苏省"),
    ("浙江省公共资源交易服务平台", "https://ggzy.zj.gov.cn/", "浙江省"),
    ("安徽省公共资源交易平台", "https://ggzy.ah.gov.cn/", "安徽省"),
    ("福建省公共资源交易电子公共服务平台", "https://ggzyfw.fujian.gov.cn/", "福建省"),
    ("江西省公共资源交易平台", "https://www.jxsggzy.cn/", "江西省"),
    ("山东省公共资源交易网", "https://ggzyjy.shandong.gov.cn/", "山东省"),
    ("河南省公共资源交易公共服务平台", "https://ggzy.fgw.henan.gov.cn/", "河南省"),
    ("湖北省公共资源交易电子服务系统", "https://www.hbggzyfwpt.cn/", "湖北省"),
    ("湖南省公共资源交易服务平台", "https://ggzy.hunan.gov.cn/", "湖南省"),
    ("广东省公共资源交易平台", "https://www.gdzwfw.gov.cn/ggzy-portal/index.html", "广东省"),
    ("广西壮族自治区公共资源交易中心", "https://gxggzy.gxzf.gov.cn/", "广西壮族自治区"),
    ("海南省公共资源交易平台", "https://ggzy.hainan.gov.cn/ggzy/", "海南省"),
    ("四川省公共资源交易信息网", "https://ggzyjy.sc.gov.cn/", "四川省"),
    ("贵州省公共资源交易公共服务平台", "https://ggzy.guizhou.gov.cn/", "贵州省"),
    ("云南省公共资源交易信息网", "https://ggzy.yn.gov.cn/", "云南省"),
    ("西藏自治区公共资源交易信息网", "https://ggzy.xizang.gov.cn/", "西藏自治区"),
    ("陕西省公共资源交易中心", "https://www.sxggzyjy.cn/", "陕西省"),
    ("甘肃省公共资源交易中心", "https://ggzyjy.gansu.gov.cn/", "甘肃省"),
    ("青海省公共资源交易平台", "https://www.qhggzyjy.gov.cn/", "青海省"),
    ("宁夏回族自治区公共资源交易网", "https://ggzyjy.fzggw.nx.gov.cn/", "宁夏回族自治区"),
    ("新疆维吾尔自治区公共资源交易平台", "https://ggzy.xinjiang.gov.cn/", "新疆维吾尔自治区"),
]
ADAPTER_BASED_PLATFORMS = {
    "浙江省公共资源交易服务平台": ("浙江省公共资源交易服务平台-工程建设招标公告", "https://ggzy.zj.gov.cn/", "ggzy.zj.gov.cn", "招标公告", "zhejiang_ggzy", {"category_code": "002001001", "page_size": 16}, "浙江省公共资源交易工程建设招标公告", "每 30 分钟"),
    "海南省公共资源交易平台": ("海南省公共资源交易平台-建设工程招标公告", "https://ggzy.hainan.gov.cn/ggzy/", "ggzy.hainan.gov.cn", "招标公告", "hainan_ggzy", {"category_path": "jgzbgg", "page_size": 10}, "海南省公共资源交易建设工程招标公告", "每 30 分钟"),
    "江西省公共资源交易平台": ("江西省公共资源交易平台-交易公告", "https://www.jxsggzy.cn/", "www.jxsggzy.cn", "招标公告", "jiangxi_ggzy", {"page_size": 10}, "江西省公共资源交易公告", "每 30 分钟"),
}


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
          connector_type TEXT NOT NULL DEFAULT 'rss', adapter_config TEXT NOT NULL DEFAULT '{}',
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
        if "connector_type" not in source_cols:
            db.execute("ALTER TABLE sources ADD COLUMN connector_type TEXT NOT NULL DEFAULT 'rss'")
        if "adapter_config" not in source_cols:
            db.execute("ALTER TABLE sources ADD COLUMN adapter_config TEXT NOT NULL DEFAULT '{}'")
        if "next_offset" not in source_cols:
            db.execute("ALTER TABLE sources ADD COLUMN next_offset INTEGER NOT NULL DEFAULT 0")
        if "sync_window_start" not in source_cols:
            db.execute("ALTER TABLE sources ADD COLUMN sync_window_start TEXT NOT NULL DEFAULT ''")
        if "sync_window_end" not in source_cols:
            db.execute("ALTER TABLE sources ADD COLUMN sync_window_end TEXT NOT NULL DEFAULT ''")
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
        stamp = now()
        for name, homepage, region in PROVINCIAL_PLATFORMS:
            db.execute("INSERT OR IGNORE INTO platforms(name,homepage_url,region,categories,access_method,policy_note,review_status,enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (name,homepage,region,"工程建设、政府采购、公共资源交易","官方省级平台入口 / 连接器待核验","来源候选由官方公共资源交易平台导航目录汇集；具体采集范围、访问条款与方式须逐站核验后再启用","候选待核验",0,stamp))
        if db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0:
            db.executemany("INSERT INTO sources(name,feed_url,allowed_host,category) VALUES(?,?,?,?)", [
              ("示例 RSS 来源（请替换为获准使用的公开 feed）","https://example.org/notices.xml","example.org","招标公告")])
            sid = db.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
            db.execute("INSERT INTO tasks(name,source_id,cadence) VALUES(?,?,?)", ("示例 RSS 采集任务",sid,"手动运行"))
        for platform_name, connector in ADAPTER_BASED_PLATFORMS.items():
            source_name, feed_url, host, category, connector_type, config, task_name, cadence = connector
            platform = db.execute("SELECT id FROM platforms WHERE name=?",(platform_name,)).fetchone()
            if not platform:
                continue
            db.execute("INSERT OR IGNORE INTO sources(name,feed_url,allowed_host,category,enabled,platform_id,connector_type,adapter_config) VALUES(?,?,?,?,?,?,?,?)",
                       (source_name,feed_url,host,category,1,platform[0],connector_type,json.dumps(config,ensure_ascii=False)))
            source = db.execute("SELECT id FROM sources WHERE name=?",(source_name,)).fetchone()
            if source:
                task = db.execute("SELECT id FROM tasks WHERE name=?",(task_name,)).fetchone()
                if not task:
                    db.execute("INSERT INTO tasks(name,source_id,cadence,enabled) VALUES(?,?,?,?)",(task_name,source[0],cadence,1))
                else:
                    db.execute("UPDATE tasks SET cadence=? WHERE id=? AND cadence='手动运行'",(cadence,task[0]))


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


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_host):
        super().__init__()
        self.allowed_host = allowed_host.lower()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if safe_host(newurl) != self.allowed_host:
            raise ValueError("来源重定向到未登记的域名或非 HTTPS 地址，已阻止")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_payload(source):
    url = source["feed_url"]
    host = safe_host(url)
    if host != source["allowed_host"].lower():
        raise ValueError("接口域名与已登记来源域名不一致")
    with FETCH_GUARD:
        wait = 10 - (time.monotonic() - LAST_FETCH_BY_HOST.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        LAST_FETCH_BY_HOST[host] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "BidSuiteDemo/1.0 (public tender data connector)", "Accept": "application/rss+xml, application/atom+xml, application/json, application/xml, text/xml"})
    opener = urllib.request.build_opener(SameHostRedirect(host))
    with opener.open(req, timeout=20) as response:
        final_url = response.geturl()
        if safe_host(final_url) != host:
            raise ValueError("来源跳转到了未登记域名，已阻止")
        payload = response.read(5_000_001)
        if len(payload) > 5_000_000:
            raise ValueError("来源响应超过 5MB 限制")
    return payload, url, host


def json_value(item, path):
    value = item
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return ""
    return value if isinstance(value, (str, int, float)) else ""


def fetch_json(source):
    payload, url, host = fetch_payload(source)
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON 接口返回格式无效：{exc}") from exc
    try:
        config = json.loads(source["adapter_config"] or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("字段映射配置不是有效 JSON") from exc
    rows = json_value(data, config.get("items_path", "")) if config.get("items_path") else data
    if not isinstance(rows, list):
        raise ValueError("JSON 列表路径未指向数组，请检查 items_path")
    out = []
    for row in rows[:100]:
        title = str(json_value(row, config.get("title_path", "title")) or "").strip()
        link = str(json_value(row, config.get("link_path", "url")) or "").strip()
        if not link:
            continue
        link = urllib.parse.urljoin(url, link)
        try:
            if safe_host(link) != host:
                continue
        except ValueError:
            continue
        ident = str(json_value(row, config.get("id_path", "id")) or link)
        published = normalize_published_date(str(json_value(row, config.get("published_path", "published_at")) or ""))
        description = str(json_value(row, config.get("description_path", "description")) or "")
        out.append({"title": title or "（无标题）", "source_url": link, "source_notice_id": ident,
                    "published_at": published, "description": description[:1200]})
    return out


def fetch_zhejiang_ggzy(source):
    host = source["allowed_host"].lower()
    if host != "ggzy.zj.gov.cn":
        raise ValueError("浙江连接器仅允许浙江省公共资源交易服务平台官方域名")
    try:
        config = json.loads(source["adapter_config"] or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("浙江平台连接器配置不是有效 JSON") from exc
    category_code = str(config.get("category_code") or "002001001")
    page_size = min(16, max(1, int(config.get("page_size", 16))))
    end = datetime.now().astimezone()
    window_start = source["sync_window_start"] or (end - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")
    window_end = source["sync_window_end"] or end.strftime("%Y-%m-%d %H:%M:%S")
    start_text = window_start
    end_text = window_end
    offset = int(source["next_offset"] or 0)
    endpoint = "https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
    items, total_count, records_seen = [], 0, 0
    # The official public page requests 16 records per page; keep that limit and
    # collect at most three pages per run to bound request volume and runtime.
    for page in range(3):
        payload = {
            "token": "", "pn": offset + page * page_size, "rn": page_size,
            "sdt": "", "edt": "", "wd": "", "inc_wd": "", "exc_wd": "",
            "fields": "title", "cnum": "001", "sort": '{"webdate":"0"}',
            "ssort": "title", "cl": 1200, "terminal": "",
            "condition": [{"fieldName": "categorynum", "isLike": True, "likeType": 2, "equal": category_code}],
            "time": [{"fieldName": "webdate", "startTime": start_text, "endTime": end_text}],
            "highlights": "", "statistics": None, "unionCondition": None,
            "accuracy": "", "noParticiple": "1", "searchRange": None,
            "isBusiness": "1",
        }
        with FETCH_GUARD:
            wait = 10 - (time.monotonic() - LAST_FETCH_BY_HOST.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            LAST_FETCH_BY_HOST[host] = time.monotonic()
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"User-Agent": "BidSuiteDemo/1.0 (public tender data connector)", "Accept": "application/json", "Content-Type": "application/json;charset=utf-8"})
        opener = urllib.request.build_opener(SameHostRedirect(host))
        with opener.open(req, timeout=20) as response:
            if safe_host(response.geturl()) != host:
                raise ValueError("浙江平台接口跳转到未登记域名，已阻止")
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise ValueError("浙江平台接口响应超过 5 MB 限制")
        try:
            result = json.loads(raw.decode("utf-8-sig")).get("result") or {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("浙江平台检索接口返回格式无效") from exc
        records = result.get("records") or []
        if not isinstance(records, list):
            raise ValueError("浙江平台返回的 records 不是数组")
        records_seen += len(records)
        total_count = int(result.get("totalcount") or 0)
        for row in records:
            title = str(row.get("titlenew") or row.get("title") or "").strip()
            link = urllib.parse.urljoin("https://ggzy.zj.gov.cn/", str(row.get("linkurl") or ""))
            if not title or not row.get("linkurl"):
                continue
            if safe_host(link) != host:
                continue
            description = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", str(row.get("content") or ""), flags=re.I|re.S)
            description = html.unescape(re.sub(r"<[^>]+>", " ", description))
            description = re.sub(r"\s+", " ", description).strip()
            items.append({"title": title, "source_url": link,
                "source_notice_id": str(row.get("infoid") or row.get("id") or link),
                "published_at": normalize_published_date(str(row.get("webdate") or row.get("infodate") or "")),
                "description": description[:1200], "region": "浙江省" + str(row.get("infod") or ""),
                "type": "工程建设", "kind": str(row.get("categoryname") or "招标公告"), "total_count": total_count})
        if not records or len(records) < page_size or offset + (page + 1) * page_size >= total_count:
            break
    next_offset = offset + records_seen
    complete = next_offset >= total_count or records_seen == 0
    cursor = {"next_offset": 0 if complete else next_offset,
              "sync_window_start": "" if complete else start_text,
              "sync_window_end": "" if complete else end_text,
              "backfill_complete": complete}
    return items, total_count, cursor


def fetch_hainan_ggzy(source):
    host = source["allowed_host"].lower()
    if host != "ggzy.hainan.gov.cn":
        raise ValueError("海南连接器仅允许海南省公共资源交易平台官方域名")
    try:
        config = json.loads(source["adapter_config"] or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("海南平台连接器配置不是有效 JSON") from exc
    category_path = str(config.get("category_path") or "jgzbgg")
    if category_path not in ("jgzbgg",):
        raise ValueError("海南连接器当前只支持建设工程招标公告类别")
    page_size = min(10, max(1, int(config.get("page_size", 10))))
    now_local = datetime.now().astimezone()
    window_start = source["sync_window_start"] or (now_local - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")
    window_end = source["sync_window_end"] or now_local.strftime("%Y-%m-%d %H:%M:%S")
    start_date = window_start[:10]
    page_start = max(1, int(source["next_offset"] or 1))
    items, pages_seen = [], 0
    older_seen = False
    for page in range(page_start, page_start + 3):
        filename = "index.jhtml" if page == 1 else f"index_{page}.jhtml"
        url = f"https://ggzy.hainan.gov.cn/ggzy/ggzy/{category_path}/{filename}"
        with FETCH_GUARD:
            wait = 10 - (time.monotonic() - LAST_FETCH_BY_HOST.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            LAST_FETCH_BY_HOST[host] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": "BidSuiteDemo/1.0 (public tender data connector)", "Accept": "text/html"})
        opener = urllib.request.build_opener(SameHostRedirect(host))
        with opener.open(req, timeout=20) as response:
            if safe_host(response.geturl()) != host:
                raise ValueError("海南平台列表跳转到未登记域名，已阻止")
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise ValueError("海南平台列表响应超过 5 MB 限制")
        content = raw.decode("utf-8", errors="replace")
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", content, flags=re.I|re.S)
        pages_seen += 1
        row_count = 0
        for row in rows:
            link_match = re.search(r"<a\b[^>]*href=[\"'](?:https?://ggzy\.hainan\.gov\.cn(?::80)?/)?ggzy/ggzy/" + re.escape(category_path) + r"/(\d+)\.jhtml[\"'][^>]*>", row, flags=re.I|re.S)
            if not link_match:
                continue
            row_count += 1
            href = f"https://ggzy.hainan.gov.cn/ggzy/ggzy/{category_path}/{link_match.group(1)}.jhtml"
            title_match = re.search(r"<a\b[^>]*href=[\"'][^\"']+\.jhtml[\"'][^>]*title=[\"']([^\"']+)", row, flags=re.I|re.S)
            if not title_match:
                title_match = re.search(r"<a\b[^>]*title=[\"']([^\"']+)[\"'][^>]*href=[\"'][^\"']+\.jhtml", row, flags=re.I|re.S)
            title = html.unescape(title_match.group(1)).strip() if title_match else ""
            date_match = re.search(r"20\d{2}-\d{2}-\d{2}", row)
            published = date_match.group(0) if date_match else ""
            if published and published < start_date:
                older_seen = True
                continue
            if not title:
                continue
            items.append({"title": title, "source_url": href,
                "source_notice_id": link_match.group(1), "published_at": normalize_published_date(published),
                "description": "海南省公共资源交易平台建设工程招标公告", "region": "海南省",
                "type": "工程建设", "kind": "招标公告"})
        if older_seen or row_count < page_size:
            break
    complete = older_seen or not items
    next_page = page_start + pages_seen
    cursor = {"next_offset": 0 if complete else next_page,
              "sync_window_start": "" if complete else window_start,
              "sync_window_end": "" if complete else window_end,
              "backfill_complete": complete,
              "progress_label": f"已扫至第 {next_page - 1} 页，本轮采集 {len(items)} 条"}
    return items, len(items), cursor


def fetch_jiangxi_ggzy(source):
    host = source["allowed_host"].lower()
    if host not in ("www.jxsggzy.cn", "ggzy.jiangxi.gov.cn"):
        raise ValueError("江西连接器仅允许江西省公共资源交易平台官方域名")
    try:
        config = json.loads(source["adapter_config"] or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("江西平台连接器配置不是有效 JSON") from exc
    page_size = min(10, max(1, int(config.get("page_size", 10))))
    end = datetime.now().astimezone()
    window_start = source["sync_window_start"] or (end - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")
    window_end = source["sync_window_end"] or end.strftime("%Y-%m-%d %H:%M:%S")
    offset = int(source["next_offset"] or 0)
    categories = ["002001001", "002002002", "002003001", "002004001", "002005001", "002006001",
        "002007001", "002008001", "002009001", "002010001", "002011001", "002013001",
        "002015001", "002016001", "002017001", "002021001", "002019001", "002018001",
        "002020001", "002022002", "002023002", "002024002", "002025002", "002026002"]
    category_types = {"002001":"房建及市政工程", "002002":"交通工程", "002003":"水利工程",
        "002004":"重点工程", "002005":"外贷工程", "002006":"政府采购", "002007":"国土资源交易",
        "002008":"产权交易", "002009":"林权交易", "002010":"医药采购", "002011":"环境能源交易",
        "002013":"其他工程", "002015":"疫苗采购", "002016":"农田工程", "002017":"矿业权交易",
        "002018":"林业工程", "002019":"自然资源工程", "002020":"铁路工程", "002021":"其他交易"}
    items, total_count, records_seen = [], 0, 0
    endpoint = f"https://{host}/XZinterface/rest/esinteligentsearch/getFullTextDataNew"
    for page in range(3):
        payload = {"token":"", "pn":offset+page*page_size, "rn":page_size, "sdt":"", "edt":"",
            "wd":"", "inc_wd":"", "exc_wd":"", "fields":"", "cnum":"", "sort":'{"webdate":"0","id":"0"}',
            "ssort":"title", "cl":1200, "terminal":"", "condition":[],
            "time":[{"fieldName":"webdate", "startTime":window_start, "endTime":window_end}],
            "highlights":"", "statistics":None,
            "unionCondition":[{"fieldName":"categorynum", "equal":None, "notEqual":None,
                "equalList":categories, "notEqualList":None}],
            "accuracy":"", "noParticiple":"1", "searchRange":None, "noWd":True}
        with FETCH_GUARD:
            wait = 10 - (time.monotonic() - LAST_FETCH_BY_HOST.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            LAST_FETCH_BY_HOST[host] = time.monotonic()
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"User-Agent":"BidSuiteDemo/1.0 (public tender data connector)", "Accept":"application/json",
                     "Content-Type":"application/json;charset=utf-8"})
        opener = urllib.request.build_opener(SameHostRedirect(host))
        with opener.open(req, timeout=20) as response:
            if safe_host(response.geturl()) != host:
                raise ValueError("江西平台接口跳转到未登记域名，已阻止")
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise ValueError("江西平台接口响应超过 5 MB 限制")
        try:
            result = json.loads(raw.decode("utf-8-sig")).get("result") or {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("江西平台检索接口返回格式无效") from exc
        records = result.get("records") or []
        if not isinstance(records, list):
            raise ValueError("江西平台返回的 records 不是数组")
        records_seen += len(records)
        total_count = int(result.get("totalcount") or 0)
        for row in records:
            title = str(row.get("titlenew") or row.get("title") or "").strip()
            link_path = str(row.get("linkurl") or "").strip()
            if not title or not link_path:
                continue
            link = urllib.parse.urljoin(f"https://{host}/", link_path)
            if safe_host(link) != host:
                continue
            raw_description = html.unescape(str(row.get("content") or ""))
            description = re.sub(r"<[^>]+>", " ", raw_description)
            description = re.sub(r"\s+", " ", description).strip()
            category_num = str(row.get("categorynum") or "")
            category_type = next((label for prefix,label in category_types.items() if category_num.startswith(prefix)), "公共资源交易")
            region = str(row.get("infod") or "")
            items.append({"title":title, "source_url":link,
                "source_notice_id":str(row.get("infoid") or row.get("id") or link),
                "published_at":normalize_published_date(str(row.get("webdate") or row.get("infodate") or "")),
                "description":description[:1200], "region":("江西省"+region) if region else "江西省",
                "type":category_type, "kind":str(row.get("categoryname") or "交易公告")})
        if not records or len(records) < page_size or offset+(page+1)*page_size >= total_count:
            break
    next_offset = offset + records_seen
    complete = next_offset >= total_count or records_seen == 0
    cursor = {"next_offset":0 if complete else next_offset,
        "sync_window_start":"" if complete else window_start,
        "sync_window_end":"" if complete else window_end,
        "backfill_complete":complete}
    return items, total_count, cursor


def fetch_feed(source):
    payload, url, host = fetch_payload(source)
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
        try:
            if safe_host(link) != host:
                continue
        except ValueError:
            continue
        pub = normalize_published_date(child_text(["pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"]))
        ident = child_text(["guid", "id", "{http://www.w3.org/2005/Atom}id"]) or link
        desc = child_text(["description", "summary", "{http://www.w3.org/2005/Atom}summary"])
        out.append({"title": title or "（无标题）", "source_url": link, "source_notice_id": ident,
                    "published_at": pub, "description": re.sub(r"<[^>]+>", " ", desc)[:1200]})
    return out


def fetch_source(source):
    connector = source["connector_type"] or "rss"
    if connector == "rss":
        items = fetch_feed(source)
        return items, len(items), None
    if connector == "json":
        items = fetch_json(source)
        return items, len(items), None
    if connector == "zhejiang_ggzy":
        return fetch_zhejiang_ggzy(source)
    if connector == "hainan_ggzy":
        return fetch_hainan_ggzy(source)
    if connector == "jiangxi_ggzy":
        return fetch_jiangxi_ggzy(source)
    raise ValueError("该来源连接器类型暂不支持")


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
                rows = db.execute("""SELECT t.*,s.name source_name,s.connector_type FROM tasks t LEFT JOIN sources s ON s.id=t.source_id ORDER BY t.id DESC""").fetchall()
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
                    connector=(data.get("connector_type") or "rss").strip().lower()
                    if connector not in ("rss","json","zhejiang_ggzy","hainan_ggzy","jiangxi_ggzy"): return self.send_json({"error":"连接器类型仅支持 RSS / Atom、公开 JSON API，以及浙江、海南、江西省官方公开平台适配器"},400)
                    config=data.get("adapter_config") or {}
                    if not isinstance(config,dict): return self.send_json({"error":"字段映射配置必须是对象"},400)
                    if connector=="json" and not config.get("title_path"):
                        return self.send_json({"error":"JSON API 至少需要配置 title_path"},400)
                    if connector=="zhejiang_ggzy" and host!="ggzy.zj.gov.cn":
                        return self.send_json({"error":"浙江省适配器只能绑定 ggzy.zj.gov.cn"},400)
                    if connector=="hainan_ggzy" and host!="ggzy.hainan.gov.cn":
                        return self.send_json({"error":"海南省适配器只能绑定 ggzy.hainan.gov.cn"},400)
                    if connector=="jiangxi_ggzy" and host not in ("www.jxsggzy.cn","ggzy.jiangxi.gov.cn"):
                        return self.send_json({"error":"江西省适配器只能绑定江西省公共资源交易平台官方域名"},400)
                    db.execute("INSERT INTO sources(name,feed_url,allowed_host,category,platform_id,connector_type,adapter_config) VALUES(?,?,?,?,?,?,?)",(name,url,host,data.get("category","招标公告"),data.get("platform_id") or None,connector,json.dumps(config,ensure_ascii=False)))
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
                    task=db.execute("SELECT t.*,s.name AS feed_source_name,s.feed_url,s.allowed_host,s.category,s.enabled AS source_enabled,s.platform_id,s.connector_type,s.adapter_config,s.next_offset,s.sync_window_start,s.sync_window_end,p.enabled AS platform_enabled,p.review_status AS platform_review_status FROM tasks t JOIN sources s ON s.id=t.source_id LEFT JOIN platforms p ON p.id=s.platform_id WHERE t.id=?",(task_id,)).fetchone()
                    if not task: return self.send_json({"error":"未找到任务"},404)
                    if not task["enabled"] or not task["source_enabled"]: return self.send_json({"error":"来源或任务已停用"},400)
                    if not task["platform_id"] or not task["platform_enabled"]: return self.send_json({"error":"该平台尚未完成来源规则核验和启用，暂不能采集"},400)
                    try:
                        fetched,total_count,cursor=fetch_source(task)
                        added=0; stamp=now()
                        for item in fetched:
                            title=item["title"]
                            db.execute("""INSERT INTO notices(title,unit,region,type,budget,deadline,source,kind,status,published_at,source_url,source_url_status,source_notice_id,description,collected_at,updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,source_notice_id) DO UPDATE SET title=excluded.title,unit=excluded.unit,region=excluded.region,type=excluded.type,budget=excluded.budget,deadline=excluded.deadline,kind=excluded.kind,status=excluded.status,published_at=excluded.published_at,source_url=excluded.source_url,source_url_status='valid',description=excluded.description,updated_at=excluded.updated_at""",
                              (title,item.get("unit",""),item.get("region",""),item.get("type",""),item.get("budget",""),item.get("deadline",""),task["feed_source_name"],item.get("kind") or task["category"],"报名中",item["published_at"],item["source_url"],"valid",item["source_notice_id"],item["description"],stamp,stamp))
                            if db.execute("SELECT changes()").fetchone()[0]: added+=1
                        status=f"完成 · 读取 {len(fetched)} 条"
                        if cursor and cursor.get("progress_label"):
                            status+=f" / {cursor['progress_label']}"
                        elif cursor and not cursor["backfill_complete"]:
                            status+=f" / 回填进度 {cursor['next_offset']} / {total_count}"
                        elif cursor and total_count:
                            status+=f" / 两天窗口回填完成 {total_count} 条"
                        elif total_count>len(fetched):
                            status+=f" / 匹配总量 {total_count}"
                        db.execute("UPDATE tasks SET last_run=?,last_status=?,added_count=? WHERE id=?",(stamp,status,added,task_id))
                        if cursor:
                            db.execute("UPDATE sources SET next_offset=?,sync_window_start=?,sync_window_end=? WHERE id=?",
                                (cursor["next_offset"],cursor["sync_window_start"],cursor["sync_window_end"],task["source_id"]))
                        db.execute("UPDATE sources SET last_checked=?,last_status=?,last_error='' WHERE id=?",(stamp,"运行正常",task["source_id"]))
                        db.execute("INSERT INTO audit(action,detail,created_at) VALUES(?,?,?)",("运行采集任务",task["name"]+f" · {added} 条更新",stamp))
                        return self.send_json({"ok":True,"read":len(fetched),"total":total_count,"upserted":added,"cursor":cursor})
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
