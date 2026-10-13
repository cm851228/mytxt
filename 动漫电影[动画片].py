# -*- coding: utf-8 -*-
# 动漫电影[动画片]  少儿动画·国产动漫·日韩动漫·欧美动漫·动画电影  v7 (2026-10)
# 9 个 m3u8 直链资源站，每个分类按速度排主备；识别“机房被拉黑”等假数据，自动换源
import sys, json, re
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
sys.path.append('..')
from base.spider import Spider

try:
    import requests
    _S = requests.Session()
    _S.mount('https://', requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0))
except Exception:
    _S = None

UA = 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
APIS = {  # 源：api 地址 / 是否支持 year 参数（全部为 m3u8 直链资源站）
    'lz': {'api': 'https://cj.lziapi.com/api.php/provide/vod/', 'year': True},    # 量子
    'bf': {'api': 'https://bfzyapi.com/api.php/provide/vod/', 'year': True},      # 暴风
    'sn': {'api': 'https://suoniapi.com/api.php/provide/vod/', 'year': True},     # 索尼
    'wj': {'api': 'https://api.wujinapi.me/api.php/provide/vod/', 'year': True},  # 无尽
    'zd': {'api': 'https://api.zuidapi.com/api.php/provide/vod/', 'year': True},  # 最大
    'ik': {'api': 'https://ikunzyapi.com/api.php/provide/vod/', 'year': True},    # iKun
    'ff': {'api': 'https://cj.ffzyapi.com/api.php/provide/vod/', 'year': True},   # 非凡
    'js': {'api': 'https://jszyapi.com/api.php/provide/vod/', 'year': True},      # 极速
    'ry': {'api': 'https://cj.rycjapi.com/api.php/provide/vod/', 'year': True},   # 如意
}
# 分类：本地id, 名称, [(源, 源分类id), ...]  前面的优先；被拉黑/失败自动换下一个
CLASSES = [
    ('se', '少儿动画', []),  # 按国产少儿频道动画系列聚合搜索
    # 海报走国内可达 CDN 的源排前面（索尼/无尽/最大 的图床在 Cloudflare，国内常加载不出来，放最后兜底）
    ('gm', '国产动漫', [('lz', '29'), ('bf', '40'), ('ik', '35'), ('ff', '29'), ('ry', '29'),
                      ('sn', '29'), ('wj', '29'), ('zd', '29')]),
    ('rb', '日韩动漫', [('lz', '30'), ('bf', '41'), ('js', '25'), ('ik', '37'), ('ff', '30'), ('ry', '30')]),
    ('om', '欧美动漫', [('lz', '31'), ('bf', '42'), ('js', '26'), ('ik', '36'), ('ff', '31'), ('ry', '31')]),
    ('dhdy', '动画电影', [('bf', '50'), ('js', '23'), ('ik', '22'), ('lz', '49'),
                      ('ry', '47'), ('sn', '39'), ('wj', '33'), ('zd', '39')]),
]
CMAP = {c[0]: c[2] for c in CLASSES}
# 国产少儿频道动画系列（CCTV少儿、金鹰卡通、卡酷等常播）
KIDS = ['熊出没', '喜羊羊与灰太狼', '猪猪侠', '大头儿子和小头爸爸', '大耳朵图图', '超级飞侠',
        '巴啦啦小魔仙', '开心超人', '果宝特攻', '萌鸡小队', '小鲤鱼历险记', '葫芦娃',
        '黑猫警长', '舒克贝塔', '虹猫蓝兔', '蓝猫淘气三千问', '百变校巡', '迷你特工队',
        '神兵小将', '魔幻陀螺', '京剧猫', '阿U', '洛宝贝', '小虎墩', '海尔兄弟',
        '三毛流浪记', '阿凡提', '哪吒传奇', '宝宝巴士', '贝瓦儿歌', '赛尔号', '小猪班纳']
PER_PAGE = 3                          # 少儿动画“全部”每页聚合几个系列
# 搜索/少儿系列：先并发查最快的一组，全组被拉黑或无结果才查备用组
SEARCH_SRC = [['lz', 'bf'], ['ik', 'js', 'ff'], ['wj', 'zd']]
KIDS_SRC = [['lz', 'bf'], ['ik', 'js'], ['wj', 'zd']]
ANIME = re.compile(r'动漫|动画|漫剧|儿童|少儿|卡通')
BAN_TYPE = re.compile(r'里番|伦理|理论|倫理|福利|擦边|解说|预告|资讯|新闻|体育|足球|篮球|网球|斯诺克|演员')
BAN_NAME = re.compile(r'实机|赏析|游戏解说|解说|预告片|花絮|采访|短剧')
BLOCKED = re.compile(r'拉黑|机房|封禁|禁止|屏蔽|更换IP|请勿|非法访问|访问受限')
_POOL = ThreadPoolExecutor(16)


class Spider(Spider):
    cache = {}
    bad = {}   # 被拉黑/失败的源 -> 连续失败次数

    def getName(self):
        return '动漫电影'

    def init(self, extend=''):
        pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    # ---------- 网络 ----------
    def _get(self, src, params, force=False):
        url = APIS[src]['api'] + '?' + params
        d = self.cache.get(url)
        if d is not None:
            return d
        if not force and self.bad.get(src, 0) >= 2:      # 连续两次被拉黑/失败，本次会话跳过
            return None
        try:
            if _S is not None:
                txt = _S.get(url, headers={'User-Agent': UA}, timeout=(3, 5)).text
            else:
                txt = self.fetch(url, headers={'User-Agent': UA}, timeout=5).text
            d = json.loads(txt)
            lst = d.get('list')
            if not isinstance(lst, list):
                raise ValueError
            # 资源站对机房/VPN IP 会返回“机房被拉黑”之类的假数据，识别后视为失败
            if BLOCKED.search(str(d.get('msg', ''))) or any(BLOCKED.search(v.get('vod_name') or '') for v in lst[:3]):
                raise ValueError('blocked')
            self.bad.pop(src, None)
            if len(self.cache) > 100:
                self.cache.clear()
            self.cache[url] = d
            return d
        except Exception:
            self.bad[src] = self.bad.get(src, 0) + 1
        return None

    def _ok(self, v):
        return not BAN_TYPE.search(v.get('type_name') or '') and not BAN_NAME.search(v.get('vod_name') or '')

    def _cards(self, src, lst):
        return [{'vod_id': '%s_%s' % (src, v['vod_id']), 'vod_name': v.get('vod_name', ''),
                 'vod_pic': (v.get('vod_pic') or '').strip(), 'vod_remarks': v.get('vod_remarks', '')}
                for v in lst if self._ok(v)]

    def _multi_search(self, keys, tiers, pg=1, anime_only=True, strict=False):
        for srcs in tiers:
            out, pc = self._search_once(keys, srcs, pg, anime_only, strict)
            if out:
                return out, pc
        return [], pg

    def _search_once(self, keys, srcs, pg=1, anime_only=True, strict=False):
        """多关键词×多源 并发搜索，按片名去重，保持关键词顺序"""
        jobs = [(k, s) for k in keys for s in srcs]
        q = lambda k: 'ac=videolist&wd=%s&pg=%d' % (quote(k), pg)
        res = list(_POOL.map(lambda js: (js[0], js[1], self._get(js[1], q(js[0]))), jobs))
        out, seen, pc = [], set(), pg
        for key, src, d in res:
            if not d:
                continue
            pc = max(pc, int(d.get('pagecount') or pg))
            lst = [v for v in d['list'] if ANIME.search(v.get('type_name') or '')] if anime_only else d['list']
            if strict:  # 片名必须含系列名前两个字，去掉搜索带出的无关片
                lst = [v for v in lst if key[:2] in (v.get('vod_name') or '')]
            for c in self._cards(src, lst):
                n = re.sub(r'[\s·:：]', '', c['vod_name'])
                if n not in seen:
                    seen.add(n)
                    out.append(c)
        return out, pc

    # ---------- 接口 ----------
    def homeContent(self, filter):
        years = {'key': 'year', 'name': '年份',
                 'value': [{'n': '全部', 'v': ''}] + [{'n': str(y), 'v': str(y)} for y in range(2026, 2009, -1)]}
        series = {'key': 'ip', 'name': '系列', 'value': [{'n': '全部', 'v': ''}] + [{'n': k, 'v': k} for k in KIDS]}
        filters = {c[0]: [years] for c in CLASSES}
        filters['se'] = [series]
        return {'class': [{'type_id': c[0], 'type_name': c[1]} for c in CLASSES], 'filters': filters}

    def homeVideoContent(self):
        vods, _ = self._multi_search(KIDS[:3], KIDS_SRC, strict=True)
        return {'list': vods[:30]}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        ext = extend or {}
        if tid == 'se':
            ip = ext.get('ip', '')
            if ip:  # 单个系列：翻页走接口分页
                vods, pc = self._multi_search([ip], KIDS_SRC, pg, strict=True)
            else:   # 全部：每页聚合 PER_PAGE 个系列
                pc = (len(KIDS) + PER_PAGE - 1) // PER_PAGE
                keys = KIDS[(pg - 1) * PER_PAGE: pg * PER_PAGE]
                vods = self._multi_search(keys, KIDS_SRC, strict=True)[0] if keys else []
            return {'list': vods, 'page': pg, 'pagecount': pc, 'limit': len(vods), 'total': 9999}
        year = ext.get('year', '')
        for src, stid in CMAP.get(tid, []):
            if year and not APIS[src]['year']:
                continue
            q = 'ac=videolist&t=%s&pg=%d' % (stid, pg)
            if year:
                q += '&year=' + year
            d = self._get(src, q)
            if d and d['list']:
                vods = self._cards(src, d['list'])
                return {'list': vods, 'page': pg, 'pagecount': int(d.get('pagecount') or pg),
                        'limit': len(vods), 'total': int(d.get('total') or 0)}
        return {'list': [], 'page': pg, 'pagecount': pg, 'limit': 0, 'total': 0}

    def detailContent(self, ids):
        src, vid = ids[0].split('_', 1)
        if src not in APIS:
            return {'list': []}
        d = self._get(src, 'ac=videolist&ids=' + vid, True)
        if not d or not d['list']:
            return {'list': []}
        v = d['list'][0]
        froms = (v.get('vod_play_from') or '').split('$$$')
        urls = (v.get('vod_play_url') or '').split('$$$')
        pf, pu = [], []
        for f, u in zip(froms, urls):  # 只留 m3u8 直链（秒开，不走解析）
            if '.m3u8' in u:
                pf.append('直链' if not pf else '直链%d' % (len(pf) + 1))
                pu.append(u.strip('#'))
        if not pf:
            pf, pu = froms, urls
        return {'list': [{
            'vod_id': ids[0], 'vod_name': v.get('vod_name', ''), 'vod_pic': (v.get('vod_pic') or '').strip(),
            'type_name': v.get('type_name', ''), 'vod_year': v.get('vod_year', ''), 'vod_area': v.get('vod_area', ''),
            'vod_remarks': v.get('vod_remarks', ''), 'vod_actor': v.get('vod_actor', ''),
            'vod_director': v.get('vod_director', ''),
            'vod_content': re.sub(r'<[^>]+>|&nbsp;', '', v.get('vod_content') or '').strip(),
            'vod_play_from': '$$$'.join(pf), 'vod_play_url': '$$$'.join(pu)}]}

    def searchContent(self, key, quick, pg='1'):
        pg = int(pg or 1)
        vods, pc = self._multi_search([key], SEARCH_SRC, pg)
        return {'list': vods, 'page': pg, 'pagecount': pc}

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, id, vipFlags):
        if '.m3u8' in id or '.mp4' in id:
            return {'parse': 0, 'jx': 0, 'url': id, 'header': {'User-Agent': UA}}
        return {'parse': 1, 'jx': 1, 'url': id, 'header': {'User-Agent': UA}}
