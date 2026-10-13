# coding=utf-8
"""
多聚漫画后台的 ys Type 3 单文件爬虫。
对接本机 duoju-manhua-android（默认 127.0.0.1:8992）。
播放图片使用 pics:// 前缀 + && 分隔符，兼容绝大多数壳的漫画阅读器。
@author duoju
"""

import base64
import hashlib
import json
import os
import re
import time
from copy import deepcopy

import requests
from requests import Session
from requests.exceptions import RequestException

from base.spider import Spider as BaseSpider


# ============ 平台定义 ============
PLATFORMS = [
    ("mh007", "漫画大全"),
    ("2cy", "次元漫画"),
    ("bzmh", "包子漫画"),
    ("dhmh", "顶漫画"),
    ("1kkk", "极速漫画"),
    ("gmanhua", "G漫画"),
    ("dmtmh", "大魔兔"),
    ("duya", "毒牙漫画"),
    ("gzmh", "瓜子漫画"),
    ("mangacopy", "拷贝漫画"),
    ("mangadex", "MangaDex"),
    ("mhkami", "漫神"),
    ("mkz", "漫客栈"),
    ("songzi", "松子漫画"),
    ("xinmanhua", "新漫画"),
    ("zaimanhua", "再漫画"),
]

PLATFORM_NAMES = dict(PLATFORMS)


DEFAULT_CONFIG = {
    "base_url": "http://127.0.0.1:8992",
    "default_plat": "mh007",
    "timeout": 20,
    "home_ttl": 180,
}


class DuojuClientError(Exception):
    """多聚漫画后端请求失败。"""


# ============ HTTP 客户端 ============
class DuojuHttpClient:
    def __init__(self, config):
        self.config = config
        self.base_url = str(config.get("base_url") or DEFAULT_CONFIG["base_url"]).rstrip("/")
        self.timeout = self._positive_int(config.get("timeout"), 20, 5, 60)
        self.session = Session()
        self.session.headers.update({
            "User-Agent": "MOBILE_UA",
            "Accept": "application/json, text/plain, */*",
        })

    @staticmethod
    def _positive_int(value, fallback, minimum, maximum):
        try:
            return min(max(int(value), minimum), maximum)
        except (TypeError, ValueError):
            return fallback

    def _url(self, path):
        return self.base_url + "/" + str(path or "").lstrip("/")

    def _request(self, method, path, params=None, json_body=None):
        try:
            response = self.session.request(
                method, self._url(path),
                params=params, json=json_body, timeout=self.timeout,
            )
        except RequestException as error:
            raise DuojuClientError("无法连接多聚漫画服务: %s" % error)

        if response.status_code >= 400:
            message = response.text.strip()[:200]
            raise DuojuClientError("多聚漫画返回 %s: %s" % (response.status_code, message or "请求失败"))

        if not response.content:
            return None
        try:
            data = response.json()
        except ValueError:
            return response.text

        if isinstance(data, dict) and data.get("code") == 200 and "data" in data:
            return data["data"]
        return data

    def platform_list(self):
        data = self._request("GET", "/api/platform")
        if isinstance(data, dict) and isinstance(data.get("platforms"), list):
            return data["platforms"]
        return [{"key": k, "name": n} for k, n in PLATFORMS]

    def cats(self, plat):
        data = self._request("GET", "/api/cats", params={"plat": plat})
        cats = []
        if isinstance(data, dict) and isinstance(data.get("cats"), list):
            cats = data["cats"]
        elif isinstance(data, list):
            cats = data
        return cats

    def category(self, plat, cat="", page=1):
        return self._request("GET", "/api/category", params={
            "plat": plat, "cat": cat, "page": page,
        })

    def detail(self, plat, book_id):
        return self._request("GET", "/api/detail", params={"plat": plat, "id": book_id})

    def play(self, plat, ref):
        return self._request("GET", "/api/play", params={"plat": plat, "url": ref})


# ============ 统一转换 ============
class DuojuMapper:
    ID_PREFIX = "duoju"

    @classmethod
    def pack(cls, kind, payload=None):
        raw = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return "%s:%s:%s" % (cls.ID_PREFIX, kind, body)

    @classmethod
    def unpack(cls, value):
        text = str(value or "")
        parts = text.split(":", 2)
        if len(parts) != 3 or parts[0] != cls.ID_PREFIX:
            return None
        try:
            body = parts[2] + "=" * (-len(parts[2]) % 4)
            data = json.loads(base64.urlsafe_b64decode(body.encode("ascii")).decode("utf-8"))
            return {"kind": parts[1], "data": data if isinstance(data, dict) else {}}
        except (ValueError, TypeError, UnicodeError):
            return None

    @staticmethod
    def text(value, fallback=""):
        if value is None or value == "":
            return fallback
        if isinstance(value, list):
            return "、".join(DuojuMapper.text(i) for i in value if i) or fallback
        return str(value)

    @classmethod
    def clean_title(cls, value):
        text = re.sub(r"[$#]", " ", cls.text(value)).strip()
        return text or "未知"

    @classmethod
    def clean_episode_name(cls, value):
        return re.sub(r"[$#]", " ", cls.text(value)).strip()

    @classmethod
    def _pick(cls, item, keys, fallback=""):
        if not isinstance(item, dict):
            return fallback
        for key in keys:
            if key in item and item[key] not in (None, ""):
                return item[key]
        return fallback

    @classmethod
    def book_vod(cls, raw, plat_fallback=""):
        item = dict(raw or {})
        plat = cls.text(cls._pick(item, ["plat", "vod_plat"], plat_fallback))

        book_id = ""
        for key in ("vod_id", "id", "book_id", "bookId", "bid", "comic_id", "sourceId"):
            v = item.get(key)
            if v not in (None, ""):
                book_id = str(v).strip()
                break

        name = cls.clean_title(cls._pick(item, ["vod_name", "name", "title"]))
        pic = cls.text(cls._pick(item, ["vod_pic", "pic", "cover", "thumb"]))
        remarks = cls.text(cls._pick(item, ["vod_remarks", "remarks", "status", "last_chapter"]))
        author = cls.text(cls._pick(item, ["vod_director", "author", "artist", "writer"]))

        plat_name = PLATFORM_NAMES.get(plat, plat) if plat else ""
        if plat_name:
            remarks = "[%s] %s" % (plat_name, remarks) if remarks else "[%s]" % plat_name

        desc = " · ".join(x for x in (remarks, author) if x)

        if not book_id:
            return {
                "vod_id": "duoju:noid:0",
                "vod_name": (name or "❌ 无ID漫画") + " (无ID)",
                "vod_pic": pic,
                "vod_remarks": "（后端未返回 id）",
            }

        payload = {"plat": plat, "id": book_id, "name": name, "pic": pic}
        return {
            "vod_id": cls.pack("book", payload),
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": desc,
            "vod_actor": author,
            "vod_content": desc,
            "style": {"type": "rect", "ratio": 0.75},
        }

    @classmethod
    def folder_vod(cls, kind, payload, name, pic="", remarks="", circle=False):
        return {
            "vod_id": cls.pack(kind, payload),
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remarks,
            "vod_tag": "folder",
            "cate": {"land": 0 if circle else 1, "circle": 1 if circle else 0,
                     "ratio": 1.0 if circle else 1.78},
        }

    @classmethod
    def extract_chapter(cls, raw, index):
        ch = dict(raw or {})
        name = cls._pick(ch, [
            "name", "title", "chapter_name", "chapterName",
            "chapter_title", "chapterTitle", "chapter",
        ], "")
        ref = cls._pick(ch, [
            "url", "play_url", "playUrl", "src", "link",
            "chapter_url", "chapterUrl",
        ], "")
        if not name:
            no = cls._pick(ch, ["no", "index", "order"])
            if no not in (None, ""):
                name = "第%s话" % no
            else:
                name = "第%d话" % (index + 1)
        name = cls.clean_episode_name(name)
        return name, cls.text(ref)


# ============ HomeUI ============
class DuojuHomeLayoutBuilder:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/") + "/"

    @staticmethod
    def _node(node_id, node_type, classes=None, source="", title="", subtitle="",
              items=None, attributes=None, slot="", action="", children=None,
              icon=None, states=None):
        node = {"id": node_id, "type": node_type}
        if classes: node["classes"] = classes
        if source: node["source"] = source
        if title: node["title"] = title
        if subtitle: node["subtitle"] = subtitle
        if items is not None: node["list"] = list(items)[:60]
        if attributes: node["attributes"] = {str(k): str(v) for k, v in attributes.items()}
        if slot: node["slot"] = slot
        if action: node["action"] = action
        if children is not None: node["children"] = children
        if icon is not None: node["icon"] = icon
        if states: node["states"] = states
        return node

    @staticmethod
    def _css():
        return """
:root{--accent:#FF10B981;--accent-strong:#FF047857;--page:#FFFCFDFC;--panel:#FFFFFFFF;--soft:#FFF1F9F6;--hover:#FFF5FAF8;--text:#FF173129;--muted:#FF64766E;--line:#FFE5EFEB}
page{display:flex;color:var(--text);background:transparent;font-family:sans;font-size:13sp}
.lx-header{color:var(--text);font-size:17sp;font-weight:700;background:transparent}
.lx-nav,.lx-player{background:#EFFFFFFF;background-blur:18dp;border-color:var(--line)}
.lx-feed{display:flex;flex-direction:column;padding:10dp 14dp 154dp}
.lx-status{margin-top:4dp;margin-bottom:6dp;padding-inline:18dp;padding-block:15dp;section-radius:22dp;section-background:linear-gradient(135deg,#FF10B981,#FF047857);section-border:0dp solid transparent;color:#FFFFFFFF;heading-color:#FFFFFFFF;heading-size:22sp;heading-weight:700;meta-color:#E6FFFFFF;meta-font-size:13sp;box-shadow:0dp 12dp 30dp #2410B981}
.lx-section{margin-top:4dp;margin-bottom:4dp;heading-color:var(--text);heading-size:18sp;heading-weight:700;color:var(--text);font-size:13sp;meta-color:var(--muted);meta-font-size:11sp}
.lx-books{orientation:horizontal;viewport-count:2.75;gap:12dp;item-ratio:0.75;card-padding:0dp;card-radius:14dp;card-background:transparent;font-size:12sp;meta-font-size:10sp}
.lx-plat{orientation:horizontal;viewport-count:3.05;gap:8dp;item-height:42dp;item-ratio:3.6;card-padding:9dp;card-radius:999dp;card-background:var(--soft);card-border:1dp solid #FFD5EEE5;color:#FF176B55;font-size:12sp;show-image:false}
.lx-tab{color:#FF6B7280;font-size:11sp;border-radius:18dp}
.lx-tab:selected{color:var(--accent-strong);background:#1910B981}
.lx-player{position:fixed;left:14dp;right:14dp;bottom:84dp;height:60dp;border-radius:18dp;box-shadow:0dp 10dp 26dp #1F10B981;z-index:24}
.card:pressed{scale:.97;opacity:.88}
""".strip()

    def build(self, data):
        platforms = data.get("platforms") or []
        books = (data.get("books") or [])[:24]
        server_ok = data.get("server_ok")

        plat_items = [
            DuojuMapper.folder_vod("plat", {"plat": p.get("key") or p.get("plat")},
                                    p.get("name") or p.get("key"), "", "进入")
            for p in platforms
        ]

        server_text = "已连接多聚漫画 · 聚合全网漫画源" if server_ok else "未连接 127.0.0.1:8992 · 请启动后台服务"

        content = [
            self._node("dj-status", "headline", ["lx-status"],
                       title="多聚漫画", subtitle=server_text),
            self._node("dj-platforms", "chip_cloud", ["lx-section", "lx-plat"], source="inline",
                       title="平台", items=plat_items, attributes={"limit": 20}),
            self._node("dj-books", "album_shelf", ["lx-section", "lx-books"], source="inline",
                       title="热门漫画", items=books, attributes={"limit": 24}),
        ]

        return {
            "version": 4,
            "document": {
                "id": "duoju-manhua",
                "default_profile": "mobile",
                "variables": {
                    "--accent": "#FF10B981", "--accent-strong": "#FF059669",
                    "--page": "#FFFCFDFC", "--panel": "#FFFFFFFF",
                    "--text": "#FF173129", "--muted": "#FF64766E", "--line": "#FFE5EFEB",
                },
                "theme": {"name": "duoju-emerald", "mode": "light",
                          "backgrounds": [{"type": "solid", "color": "#FFFCFDFC", "media": "light"}]},
                "styles": {"css": self._css()},
                "actions": [
                    {"id": "dj-settings", "command": "system.settings"},
                    {"id": "dj-vod", "command": "system.vod"},
                ],
                "profiles": {
                    "mobile": {
                        "enabled": True,
                        "canvas": {"edge_to_edge": True, "safe_area": "system"},
                        "chrome": {
                            "top": {
                                "enabled": True, "height": 58, "position": "sticky",
                                "logo": {"name": "book", "tint": "#FF10B981"},
                                "title": "多聚漫画",
                                "items": [
                                    {"id": "dj-settings-item", "title": "设置",
                                     "icon": {"name": "settings"}, "action": "dj-settings"},
                                ],
                                "backgrounds": [{"type": "solid", "color": "#EFFFFFFF", "opacity": 0.94}],
                            },
                            "bottom": {"enabled": True, "height": 72, "position": "fixed"},
                            "floating": {"enabled": True, "height": 70, "position": "fixed"},
                        },
                        "nodes": [
                            self._node("dj-page", "page", children=[
                                self._node("dj-header", "top_bar", ["lx-header"], slot="top"),
                                self._node("dj-feed", "container", ["lx-feed"], slot="content", children=content),
                                self._node("dj-player", "mini_player", ["lx-player"], slot="floating",
                                           attributes={"empty-text": "选择一本漫画开始阅读"}),
                            ])
                        ],
                    },
                },
            },
        }


# ============ 主 Spider ============
class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.config = deepcopy(DEFAULT_CONFIG)
        self.client = DuojuHttpClient(self.config)
        self.settings_path = ""
        self.home_cache = None
        self.home_cache_at = 0

    def getName(self):
        return "多聚漫画"

    def init(self, extend=""):
        self.settings_path = self._settings_path()
        options = self._parse_options(extend)
        options.update(self._load_settings())
        self._apply_options(options)

    def _settings_path(self):
        site_key = str(getattr(self, "siteKey", "") or self.getName() or "duoju")
        digest = hashlib.sha256(site_key.encode("utf-8")).hexdigest()[:20]
        root = os.environ.get("YS_DUOJU_CONFIG_DIR", "").strip()
        if not root:
            try:
                from com.chaquo.python import Python
                root = str(Python.getPlatform().getApplication().getFilesDir().getAbsolutePath())
            except Exception:
                root = os.path.join(os.path.expanduser("~"), ".ys")
        return os.path.join(root, "duoju-manhua", "config-%s.json" % digest)

    def _load_settings(self):
        if not self.settings_path or not os.path.isfile(self.settings_path):
            return {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_settings(self):
        if not self.settings_path:
            return False
        directory = os.path.dirname(self.settings_path)
        temporary = self.settings_path + ".tmp"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary, self.settings_path)
            return True
        except (OSError, TypeError, ValueError):
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
            return False

    @staticmethod
    def _parse_options(value):
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            data = json.loads(str(value))
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {"base_url": str(value)} if str(value).startswith("http") else {}

    def _apply_options(self, options):
        aliases = {"server": "base_url", "url": "base_url", "plat": "default_plat"}
        normalized = dict(options or {})
        for k, v in aliases.items():
            if k in normalized and v not in normalized:
                normalized[v] = normalized[k]
        for key in DEFAULT_CONFIG:
            if key in normalized:
                self.config[key] = normalized[key]
        self.config["base_url"] = str(self.config.get("base_url") or DEFAULT_CONFIG["base_url"]).rstrip("/")
        self.client = DuojuHttpClient(self.config)
        self.home_cache = None
        self.home_cache_at = 0

    # ---- 分类 ----
    def _classes(self):
        try:
            plats = self.client.platform_list()
        except DuojuClientError:
            plats = [{"key": k, "name": n} for k, n in PLATFORMS]
        classes = []
        for p in plats:
            key = p.get("key") or p.get("plat")
            name = p.get("name") or key
            if not key:
                continue
            classes.append({"type_id": "plat__%s" % key, "type_name": name, "land": 1, "ratio": 1.78})
        return classes

    def _filters(self):
        filters = {}
        try:
            plats = self.client.platform_list()
        except DuojuClientError:
            plats = [{"key": k, "name": n} for k, n in PLATFORMS]
        for p in plats:
            key = p.get("key") or p.get("plat")
            if not key:
                continue
            try:
                cats = self.client.cats(key)
            except DuojuClientError:
                cats = []
            if cats:
                filters["plat__%s" % key] = [{
                    "key": "cat", "name": "分类", "init": "0",
                    "value": [{"n": c.get("name"), "v": c.get("id")} for c in cats],
                }]
        return filters

    def homeContent(self, filter):
        return {"class": self._classes(), "filters": self._filters(), "list": []}

    def homeLayout(self):
        data = self._load_home()
        return DuojuHomeLayoutBuilder(self.config["base_url"]).build(data)

    def homeVideoContent(self):
        return {"list": []}

    def _load_home(self, force=False):
        ttl = DuojuHttpClient._positive_int(self.config.get("home_ttl"), 180, 30, 3600)
        if not force and self.home_cache and time.time() - self.home_cache_at < ttl:
            return self.home_cache
        data = {"server_ok": False, "platforms": [], "books": [], "error": ""}
        try:
            data["platforms"] = self.client.platform_list()
            data["server_ok"] = True
        except DuojuClientError as error:
            data["error"] = str(error)
            self.home_cache = data
            self.home_cache_at = time.time()
            return data
        default_plat = str(self.config.get("default_plat") or "mh007")
        try:
            page = self.client.category(default_plat, "0", 1)
            raw = []
            if isinstance(page, dict):
                raw = page.get("list") or []
            elif isinstance(page, list):
                raw = page
            data["books"] = [DuojuMapper.book_vod(item, default_plat) for item in raw[:24]]
        except DuojuClientError as error:
            data["error"] = (data["error"] + "；" if data["error"] else "") + str(error)
        self.home_cache = data
        self.home_cache_at = time.time()
        return data

    # ---- 分类内容 ----
    def _page_number(self, value):
        try:
            return max(int(value or 1), 1)
        except (TypeError, ValueError):
            return 1

    def _page_result(self, items, page, limit=30, total=None):
        total = len(items) if total is None else max(int(total), 0)
        limit = max(int(limit), 1)
        pagecount = max(page, (total + limit - 1) // limit) if total else page
        return {"list": items, "page": page, "pagecount": pagecount, "limit": limit, "total": total}

    def categoryContent(self, tid, pg, filter, extend):
        page = self._page_number(pg)
        options = self._parse_options(extend)

        if tid.startswith("plat__"):
            plat = tid[6:]
            cat = str(options.get("cat") or "0")
            return self._plat_content(plat, cat, page)
        ref = DuojuMapper.unpack(tid)
        if ref and ref["kind"] == "plat":
            return self._plat_content(ref["data"].get("plat"), "0", page)
        if ref and ref["kind"] == "book":
            return self.detailContent([tid])
        return self._page_result([], page)

    def _plat_content(self, plat, cat, page):
        try:
            result = self.client.category(plat, cat, page)
        except DuojuClientError as e:
            return self._page_result(
                [{"vod_id": "dj_err", "vod_name": "❌ %s" % e, "vod_tag": "action"}], page)
        raw = []
        has_more = False
        if isinstance(result, dict):
            raw = result.get("list") or []
            has_more = bool(result.get("hasMore"))
        elif isinstance(result, list):
            raw = result
        items = [DuojuMapper.book_vod(item, plat) for item in raw]
        limit = len(items) if items else 30
        pagecount = page + 1 if has_more else page
        return {"list": items, "page": page, "pagecount": pagecount,
                "limit": limit, "total": limit * pagecount}

    # ---- 详情 ----
    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            ids = ids[0] if ids else ""
        item_id = str(ids or "").split(",", 1)[0]

        ref = DuojuMapper.unpack(item_id)
        if not ref or ref["kind"] != "book":
            return {"list": []}

        data = ref["data"]
        plat = data.get("plat")
        book_id = data.get("id")
        if not plat or not book_id:
            return {"list": [{
                "vod_id": item_id,
                "vod_name": data.get("name") or "❌ 参数错误",
                "vod_remarks": "plat 或 id 为空（%r / %r）" % (plat, book_id),
            }]}

        try:
            detail = self.client.detail(plat, book_id)
        except DuojuClientError as e:
            return {"list": [{
                "vod_id": item_id,
                "vod_name": "❌ %s" % e,
                "vod_remarks": "服务未响应",
            }]}

        if not isinstance(detail, dict):
            return {"list": []}

        chapters = detail.get("chapters") or []
        entries = []
        for idx, ch in enumerate(chapters):
            name, ref_url = DuojuMapper.extract_chapter(ch, idx)
            if not ref_url:
                continue
            token = DuojuMapper.pack("play", {
                "plat": plat, "ref": ref_url, "name": name,
            })
            entries.append("%s$%s" % (name, token))

        book_name = DuojuMapper.clean_title(detail.get("vod_name") or data.get("name"))
        book_pic = detail.get("vod_pic") or data.get("pic") or ""
        book_desc = detail.get("vod_content") or detail.get("vod_remarks") or ""

        return {"list": [{
            "vod_id": item_id,
            "vod_name": book_name,
            "vod_pic": book_pic,
            "vod_remarks": "%d 话" % len(entries) if entries else "暂无章节",
            "vod_content": book_desc,
            "vod_play_from": "多聚漫画",
            "vod_play_url": "#".join(entries),
        }]}

    # ---- 播放（漫画：返回图片列表） ----
    def playerContent(self, flag, id, vipFlags):
        if isinstance(id, (list, tuple)):
            id = id[0] if id else ""
        ref = DuojuMapper.unpack(id)
        if not ref or ref["kind"] != "play":
            return {"parse": 0, "url": "", "msg": "无效的播放参数"}
        data = ref["data"]
        try:
            result = self.client.play(data.get("plat"), data.get("ref"))
        except DuojuClientError as e:
            return {"parse": 0, "url": "", "msg": str(e)}

        pics = []
        referer = "http://android.007ting.com/"
        ua = "Dalvik/2.1.0 (Linux; U; Android 9;MIX 2S Build/PKQ1.180729.001)"
        if isinstance(result, dict):
            pics = result.get("pics") or result.get("images") or []
            referer = str(result.get("referer") or referer)
            ua = str(result.get("ua") or ua)
        if not pics:
            return {"parse": 0, "url": "", "msg": "未获取到图片"}

        clean = [str(p).strip() for p in pics if p]
        url = "pics://" + "&&".join(clean)

        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": json.dumps({
                "User-Agent": ua,
                "Referer": referer,
            }, ensure_ascii=False),
            "msg": "多聚漫画",
            "flag": "🖼 漫画",
        }

    # ---- Action ----
    def action(self, action_str):
        try:
            payload = json.loads(action_str) if isinstance(action_str, str) else action_str
            action_id = (payload.get("action") or payload.get("actionId") or "") \
                if isinstance(payload, dict) else str(action_str)
            value = payload.get("value", {}) if isinstance(payload, dict) else {}
        except (ValueError, TypeError):
            action_id = str(action_str or "")
            value = {}
        try:
            if action_id == "dj_settings":
                return self._action_settings(value)
            if action_id == "dj_refresh":
                self.home_cache = None
                return {"action": {"actionId": "__refresh_list__"}, "toast": "已刷新"}
            return "未知操作: %s" % action_id
        except (DuojuClientError, OSError, ValueError) as error:
            return {"action": {
                "actionId": "dj_error",
                "type": "msgbox",
                "title": "操作失败",
                "htmlMsg": str(error),
            }}

    def _action_settings(self, value):
        values = value if isinstance(value, dict) else {}
        options = {}
        for key in ("base_url", "default_plat"):
            if key in values:
                options[key] = str(values[key]).strip()
        self._apply_options(options)
        saved = self._save_settings()
        message = "设置已保存" if saved else "设置仅当前有效"
        try:
            self.client.platform_list()
        except DuojuClientError as e:
            message += "；连接失败: %s" % e
        return {"action": {"actionId": "__refresh_list__"}, "toast": message}

    def destroy(self):
        try:
            self.client.session.close()
        except Exception:
            pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None