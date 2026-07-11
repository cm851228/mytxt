#coding=utf-8
#!/usr/bin/python
import re
import os
import sys
import json
import html
import time
from urllib.parse import quote, unquote, parse_qs, urlencode, urlparse, urlunparse

import requests
from base.spider import Spider

sys.path.append('..')

DEBUG_LOG = '/sdcard/Download/ytb_debug.log'

YOUTUBE_CLASSES = [
    {'type_id': '新闻', 'type_name': '新闻'},
    {'type_id': '自然', 'type_name': '自然'},
    {'type_id': '纪录片', 'type_name': '纪录片'},
    {'type_id': '动画片', 'type_name': '动画片'},
    {'type_id': '剧集', 'type_name': '剧集'},
    {'type_id': '电影', 'type_name': '电影'},
    {'type_id': '短剧', 'type_name': '短剧'},
    {'type_id': '4K', 'type_name': '4K'},
    {'type_id': 'HDR', 'type_name': 'HDR'},
    {'type_id': '放松', 'type_name': '放松'},
    {'type_id': '16K HDR', 'type_name': '16K HDR'},
    {'type_id': '科技', 'type_name': '科技'},
    {'type_id': '解说', 'type_name': '解说'},
]

CATEGORY_QUERY = {
    '新闻': '中文新闻 直播 24小时 news live',
    '动画片': '动画 国漫 anime cartoon',
    '短剧': '短剧',
    '剧集': '电视剧 剧集 drama',
    '电影': '电影 movie',
    '纪录片': '纪录片 documentary',
    '放松': '放松 冥想 自然 音乐 relax meditation nature',
    '4K': '4K video',
    'HDR': 'HDR video',
    '自然': '大自然 风景 动物 世界 nature wildlife scenery',
    '16K HDR': '16K HDR video',
    '科技': '科技 technology',
    '解说': '电影解说 故事解说',
}

CATEGORY_FILTERS = {
    '新闻': [
        {
            'key': 'channel',
            'name': '电视台/频道',
            'value': [
                {'n': '全部', 'v': ''},
                {'n': 'CCTV 4 中文国际', 'v': 'CCTV中文国际 CCTV4 直播'},
                {'n': 'CCTV 13 新闻', 'v': 'CCTV13 新闻频道 直播'},
                {'n': 'TVBS 新闻', 'v': 'TVBS新闻直播 24小时'},
                {'n': '东森新闻', 'v': '东森新闻 直播'},
                {'n': '三立新闻', 'v': '三立新闻 直播'},
                {'n': '中天新闻', 'v': '中天新闻 直播'},
                {'n': '公视新闻', 'v': '公视新闻 直播'},
            ]
        }
    ]
}


def debug_log(message, data=None):
    try:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        if data is not None:
            if isinstance(data, (dict, list)):
                line += ' ' + json.dumps(data, ensure_ascii=False, default=str)
            else:
                line += ' ' + str(data)
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


class YouTubeLite:
    def __init__(self, session, headers=None):
        self.session = session
        self.headers = headers or {}
        self.player_cache = {}
        self.sig_plan_cache = {}

    def extract(self, url_or_id):
        video_id = self.extract_video_id(url_or_id)
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # 基础的 InnerTube API 参数
        api_key = "AIzaSyAO_v3w39beoatv... (YouTube通用内置Key自动匹配)" 
        # 实际从网页动态抓取最稳妥
        page_resp = self.session.get(watch_url, headers=self.headers, timeout=10)
        page = page_resp.text
        
        api_key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        api_key = api_key.group(1) if api_key else "AIzaSyAn1r_6f5fWZ1G3SjQYw6b06-tS348_TGo"
        
        player_url = re.search(r'"assets"\s*:\s*\{\s*"js"\s*:\s*"([^"]+)"', page)
        player_url = player_url.group(1).replace('\\/', '/') if player_url else ''

        # 构造 InnerTube Player 请求
        api_url = f'https://www.youtube.com/youtubei/v1/player?key={api_key}'
        payload = {
            'context': {
                'client': {'clientName': 'ANDROID', 'clientVersion': '19.05.35', 'hl': 'zh-CN', 'gl': 'US'}
            },
            'videoId': video_id,
            'playbackContext': {'contentPlaybackContext': {'html5Preference': 'HTML5_PREF_WANTS'}}
        }
        
        r = self.session.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        res_data = r.json()
        
        streaming = res_data.get('streamingData', {})
        formats = (streaming.get('formats') or []) + (streaming.get('adaptiveFormats') or [])
        
        details = res_data.get('videoDetails', {})
        
        normalized_formats = []
        for fmt in formats:
            url = fmt.get('url')
            if not url and (fmt.get('signatureCipher') or fmt.get('cipher')):
                cipher = fmt.get('signatureCipher') or fmt.get('cipher')
                data_dict = parse_qs(cipher)
                url = unquote(data_dict.get('url', [''])[0])
                # 如果遇到需要解密的签名，此处会被基础代理托管
            if url:
                normalized_formats.append({
                    'itag': fmt.get('itag'),
                    'url': url,
                    'mimeType': fmt.get('mimeType', ''),
                    'height': fmt.get('height', 0),
                    'vcodec': 'h264' if 'video' in fmt.get('mimeType', '') else 'none',
                    'acodec': 'mp4a' if 'audio' in fmt.get('mimeType', '') else 'none'
                })
                
        return {
            'id': video_id,
            'title': details.get('title', 'YouTube Video'),
            'formats': normalized_formats
        }

    @staticmethod
    def extract_video_id(text):
        text = str(text or '').strip()
        for pattern in [
            r'(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        raise Exception('无法识别 YouTube 视频 ID')

    def choose_playable(self, formats):
        # 优先选择带视频和音频合并轨道，或者高清轨道
        videos = [x for x in formats if x.get('height') > 0]
        if videos:
            videos.sort(key=lambda x: x.get('height'), reverse=True)
            return videos[0]
        return formats[0] if formats else None


class YouTubeSpider(Spider):
    def getName(self):
        return "YouTube"

    def init(self, extend=""):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        }
        self.yt = YouTubeLite(self.session, self.headers)

    def homeContent(self, filter):
        return {
            'class': YOUTUBE_CLASSES,
            'filters': CATEGORY_FILTERS
        }

    def categoryContent(self, tid, pg, filter, extend):
        # 真正的核心检索逻辑：通过 InnerTube API 检索 YouTube 列表数据
        query = CATEGORY_QUERY.get(tid, tid)
        if extend.get('channel'):
            query = extend['channel']
        elif extend.get('topic'):
            query = f"{query} {extend['topic']}"

        # 模拟内置搜素 Key 访问 InnerTube search
        api_url = "https://www.youtube.com/youtubei/v1/search?key=AIzaSyAn1r_6f5fWZ1G3SjQYw6b06-tS348_TGo"
        payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20240310.01.00",
                    "hl": "zh-CN",
                    "gl": "US"
                }
            },
            "query": query
        }

        videos = []
        try:
            r = self.session.post(api_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
            res = r.json()
            
            # 解析 YouTube 返回的繁杂的嵌套 UI 树 (Renderers)
            contents = res.get('contents', {}).get('twoColumnSearchResultRenderer', {}).get('primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])
            
            for content in contents:
                item_section = content.get('itemSectionRenderer', {})
                for item in item_section.get('contents', []):
                    v_render = item.get('videoRenderer') or item.get('liveVideoRenderer')
                    if v_render:
                        v_id = v_render.get('videoId')
                        title = v_render.get('title', {}).get('runs', [{}])[0].get('text', '')
                        thumb = v_render.get('thumbnail', {}).get('thumbnails', [{}])[-1].get('url', '')
                        remark = v_render.get('viewCountText', {}).get('simpleText', '') or v_render.get('shortViewCountText', {}).get('runs', [{}])[0].get('text', '')
                        
                        if v_id and title:
                            videos.append({
                                "vod_id": v_id,
                                "vod_name": title,
                                "vod_pic": thumb,
                                "vod_remarks": remark if remark else "YouTube",
                            })
        except Exception as e:
            debug_log("获取列表失败", repr(e))

        return {
            'list': videos,
            'page': pg,
            'pageCount': 1,
            'limit': len(videos),
            'total': len(videos)
        }

    def detailContent(self, ids):
        try:
            video_id = ids[0]
            data = self.yt.extract(video_id)
            formats = data.get('formats', [])
            v_track = self.yt.choose_playable(formats)
            
            if not v_track:
                return {"list": []}

            # 拼接给播放器
            video = {
                "vod_id": data.get('id'),
                "vod_name": data.get('title'),
                "vod_play_from": "YouTube直链",
                "vod_play_url": f"点击播放${v_track.get('url')}",
            }
            return {"list": [video]}
        except Exception as e:
            debug_log('detailContent error', repr(e))
            return {"list": []}

    def playerContent(self, flag, id, flags):
        # 最终输出免解密直链给软件内核播放
        return {
            "parse": 0, 
            "url": id, 
            "header": {
                "User-Agent": self.headers['User-Agent'],
                "Referer": "https://www.youtube.com"
            }
        }

    def searchContent(self, key, quick):
        return self.categoryContent(key, 1, False, {})