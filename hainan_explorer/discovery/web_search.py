"""Pluggable web search + permitted page fetch + place-mention extraction.

The search adapter only calls documented search APIs with a key supplied via environment
variables; it is disabled by default. Page fetching honours robots.txt, a per-domain
disable list and size/time limits. Nothing here bypasses logins, CAPTCHAs or anti-bot
systems. Pages that cannot be fetched are kept as link-only leads for manual review.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
import urllib.robotparser
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..http import ProviderDisabledError
from ..normalize import contains_name, normalize_name
from ..regions import REGIONS, region_from_text
from ..services.context import AppContext
from ..services.ingest import Candidate, SourceSpec
from ..taxonomy import category_from_text

log = logging.getLogger(__name__)

QUERY_TEMPLATES = [
    "海南 {region} 小众景点",
    "海南 {region} 海湾 岬角 礁石 灯塔",
    "海南 {region} 渔村 老码头 古村 遗迹",
    "海南环岛骑行 {region} 沿途 观景点",
    "{region} 海岸线 自然景观 地质景观",
    "海南 {region} 日出 日落 海岸 湿地",
    "{place} 游记",
    "{place} 骑行",
    "{place} 摄影 航拍",
]

# Candidate place phrases: 2-8 CJK chars ending in a geographic suffix.
PLACE_PHRASE_RE = re.compile(
    r"([一-鿿]{1,7}(?:湾|角|岛|滩|礁|渔村|古村|村|港|码头|岭|山|湖|瀑布|灯塔|公园|寺|庙|塔|洞|泉|溪|水库|岬|海滩|沙滩|古镇|老街|观景台|炮台|书院|祠|古城|盐田|湿地|红树林|海岸|半岛|峡谷|天池))"
)
STOP_PHRASES = {"海南岛", "环岛", "骑行", "海南", "中国", "全岛", "本岛", "东海岸", "西海岸", "南海岸", "北海岸", "海岸线", "小海滩", "大海", "海边村", "山顶"}
# Characters that typically end the word before a place name (particles, common verbs, punctuation).
_CUT_CHARS = set("的了是在到去从和与及看见沿着往经过前抵达说有个为把被让叫到达站第来回走骑拍摄住宿吃喝玩进出离开找到")
_LEADING_STRIP = ("海南岛", "海南省", "海南", "整个", "这个", "那个", "一个", "附近", "旁边", "整条")


def _trim_phrase(phrase: str) -> str | None:
    """Cut a regex match like 顶可以看到月亮湾 down to 月亮湾 using particle/verb boundaries."""
    for idx in range(len(phrase) - 1, -1, -1):
        if phrase[idx] in _CUT_CHARS:
            phrase = phrase[idx + 1:]
            break
    changed = True
    while changed:
        changed = False
        for lead in _LEADING_STRIP:
            if phrase.startswith(lead) and len(phrase) > len(lead):
                phrase = phrase[len(lead):]
                changed = True
    for region in REGIONS:
        short = region.name[:2]
        if phrase.startswith(short) and len(phrase) > len(short) + 1:
            phrase = phrase[len(short):]
    return phrase if 2 <= len(phrase) <= 8 else None


@dataclass
class SearchResult:
    query: str
    provider: str
    rank: int
    title: str
    url: str
    snippet: str | None


class WebSearchAdapter:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.config.provider("web_search")
        if not self.cfg.enabled:
            raise ProviderDisabledError("web_search disabled (no API configured)")
        self.kind = (self.cfg.options.get("kind") or "brave").lower()
        self.api_key = self.cfg.options.get("api_key") or ""
        if not self.api_key or self.api_key.startswith("${"):
            raise ProviderDisabledError("web_search API key missing")

    def search(self, query: str, count: int = 20) -> list[SearchResult]:
        if self.kind == "brave":
            resp = self.ctx.http.get(self.cfg.endpoint or "https://api.search.brave.com/res/v1/web/search",
                                     params={"q": query, "count": min(count, 20), "country": "CN", "search_lang": "zh-hans"},
                                     headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                                     timeout=self.cfg.timeout_seconds)
            resp.raise_for_status()
            items = (resp.json().get("web") or {}).get("results") or []
            return [SearchResult(query, "brave", i + 1, it.get("title", ""), it.get("url", ""), it.get("description")) for i, it in enumerate(items)]
        if self.kind == "serper":
            resp = self.ctx.http.post(self.cfg.endpoint or "https://google.serper.dev/search", json={"q": query, "gl": "cn", "hl": "zh-cn", "num": min(count, 20)},
                                      headers={"X-API-KEY": self.api_key}, timeout=self.cfg.timeout_seconds)
            resp.raise_for_status()
            items = resp.json().get("organic") or []
            return [SearchResult(query, "serper", i + 1, it.get("title", ""), it.get("link", ""), it.get("snippet")) for i, it in enumerate(items)]
        raise ProviderDisabledError(f"unknown web_search kind {self.kind}")


class PageFetcher:
    MAX_BYTES = 2 * 1024 * 1024

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.config.provider("web_pages")
        self.disabled_domains = set(self.cfg.options.get("disabled_domains") or [])
        self.respect_robots = bool(self.cfg.options.get("respect_robots", True))
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def is_allowed(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False, "unsupported scheme"
        host = (parts.hostname or "").lower()
        if not host:
            return False, "no host"
        if any(host == d or host.endswith("." + d) for d in self.disabled_domains):
            return False, f"domain {host} disabled by policy"
        if not self.cfg.enabled:
            return False, "page fetching disabled"
        if _is_private_host(host):
            return False, "private/loopback target blocked (SSRF guard)"
        if self.respect_robots:
            rp = self._robots_for(parts.scheme, host)
            if rp is None:
                return False, "robots.txt unreachable; fetch skipped by policy"
            if not rp.can_fetch(self.ctx.config.user_agent, url):
                return False, "disallowed by robots.txt"
        return True, "ok"

    def _robots_for(self, scheme: str, host: str):
        if host in self._robots:
            return self._robots[host]
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = self.ctx.http.get(f"{scheme}://{host}/robots.txt", timeout=15, max_attempts=1)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif resp.status_code >= 500:
                rp = None  # be conservative: unknown -> treat as disallowed later
            else:
                rp.parse([])
        except Exception:
            rp = None
        self._robots[host] = rp
        return rp

    def fetch_text(self, url: str) -> tuple[str | None, str, str | None]:
        """Return (text, access_status, title)."""
        allowed, reason = self.is_allowed(url)
        if not allowed:
            return None, "blocked" if ("policy" in reason or "robots" in reason or "SSRF" in reason) else "failed", reason
        try:
            resp = self.ctx.http.get(url, stream=True, timeout=self.cfg.timeout_seconds, max_attempts=2)
            try:
                if resp.status_code != 200:
                    return None, "failed", f"HTTP {resp.status_code}"
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype and "text" not in ctype:
                    return None, "failed", f"content-type {ctype}"
                chunks, total = [], 0
                for chunk in resp.iter_bytes(65536):
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks)
                encoding = resp.encoding or "utf-8"
            finally:
                resp.close()
        except Exception as exc:
            return None, "failed", str(exc)[:200]
        html_text = raw.decode(encoding, errors="replace")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None
        text = html_to_text(html_text)
        if _looks_like_login_wall(text):
            return None, "blocked", "login or verification wall detected; not bypassed"
        return text, "fetched", title


def html_to_text(html_text: str) -> str:
    html_text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    html_text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html_text)
    import html as _html

    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _looks_like_login_wall(text: str) -> bool:
    head = text[:1500]
    markers = ("请登录", "登录后查看", "扫码登录", "验证码", "访问过于频繁", "安全验证", "请完成验证")
    return len(text) < 2500 and any(m in head for m in markers)


def _is_private_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def extract_mentions(text: str, known_names: dict[str, int]) -> tuple[dict[int, str], list[tuple[str, str]]]:
    """Return (matched place_id -> evidence sentence, [(new phrase, evidence sentence)])."""
    sentences = re.split(r"(?<=[。！？!?\n])", text)
    matched: dict[int, str] = {}
    new_phrases: dict[str, str] = {}
    norm_known = {normalize_name(k): v for k, v in known_names.items()}
    for sentence in sentences:
        s = sentence.strip()
        if len(s) < 4:
            continue
        ns = normalize_name(s)
        for nname, pid in norm_known.items():
            if len(nname) >= 2 and nname in ns and pid not in matched:
                matched[pid] = s[:300]
        for raw_phrase in PLACE_PHRASE_RE.findall(s):
            phrase = _trim_phrase(raw_phrase)
            if not phrase or phrase in STOP_PHRASES or len(phrase) < 3:
                continue
            suffix_only = PLACE_PHRASE_RE.fullmatch(phrase) is None or re.fullmatch(r"(?:湾|角|岛|滩|礁|村|港|码头|岭|山|湖|瀑布|灯塔|公园|寺|庙|塔|洞|泉|溪|水库|岬|海滩|沙滩|古镇|老街|观景台|炮台|书院|祠|古城|盐田|湿地|红树林|海岸|半岛|峡谷|天池|渔村|古村)", phrase)
            if suffix_only:
                continue
            if normalize_name(phrase) in norm_known or phrase in new_phrases:
                continue
            if any(phrase.endswith(r.name) or phrase == r.name for r in REGIONS):
                continue
            new_phrases[phrase] = s[:300]
    return matched, list(new_phrases.items())


def mention_candidate(phrase: str, evidence: str, source_url: str, source_title: str | None, provider: str = "web_mention") -> Candidate:
    return Candidate(
        provider=provider,
        external_id=hashlib.sha1(f"{source_url}|{phrase}".encode("utf-8")).hexdigest()[:16],
        external_url=source_url,
        name=phrase,
        category=category_from_text(phrase),
        discovery_reason="travelogue_mention",
        sources=[SourceSpec(url=source_url, provider=provider, source_type="web_page", title=source_title, access_status="fetched",
                            excerpt=evidence, relationship_type="mentions", confidence=0.4)],
        region_hint=(region_from_text(evidence).name if region_from_text(evidence) else None),
        needs_geographic_verification=True,
        confidence=0.3,
    )
