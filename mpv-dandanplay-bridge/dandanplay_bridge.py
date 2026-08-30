#!/usr/bin/env python3
"""Private, cache-first bridge between MPV and the Dandanplay Open API.

The program deliberately has no third-party dependencies.  It is called by
``dandanplay_bridge.lua`` and prints one JSON object on stdout for each run.
Do not put a credential in this file; use the ignored configuration file.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


API_BASE = "https://api.dandanplay.net"
HASH_BYTES = 16 * 1024 * 1024


class BridgeError(RuntimeError):
    """An expected error that can be shown directly in MPV's OSD."""


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def emit(value: dict[str, Any], status: int = 0) -> int:
    print(compact_json(value))
    return status


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class Settings:
    app_id: str
    app_secret: str
    api_base: str
    cache_dir: Path
    comment_cache_ttl_hours: float
    font_name: str
    font_size: int
    scroll_duration: float
    play_res_x: int
    play_res_y: int
    max_comments: int

    @classmethod
    def load(cls, config_path: Path) -> "Settings":
        data = read_json(config_path, {})
        if not isinstance(data, dict):
            raise BridgeError("配置文件必须是 JSON 对象")
        app_id = str(data.get("app_id", "")).strip()
        app_secret = str(data.get("app_secret", "")).strip()
        if not app_id or not app_secret or app_id == "YOUR_APP_ID":
            raise BridgeError("请先在 dandanplay_bridge.json 中填写 app_id 和 app_secret")
        cache_value = str(data.get("cache_dir", "cache")).strip() or "cache"
        cache_dir = Path(cache_value)
        if not cache_dir.is_absolute():
            cache_dir = config_path.parent / cache_dir
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            api_base=str(data.get("api_base", API_BASE)).rstrip("/"),
            cache_dir=cache_dir,
            comment_cache_ttl_hours=max(0.0, float(data.get("comment_cache_ttl_hours", 24))),
            font_name=str(data.get("font_name", "Microsoft YaHei")),
            font_size=max(12, int(data.get("font_size", 38))),
            scroll_duration=max(3.0, float(data.get("scroll_duration", 8.0))),
            play_res_x=max(320, int(data.get("play_res_x", 1920))),
            play_res_y=max(240, int(data.get("play_res_y", 1080))),
            max_comments=max(1, int(data.get("max_comments", 12000))),
        )


class DandanplayClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call the API using the documented signature authentication scheme."""
        split = urllib.parse.urlsplit(path)
        api_path = split.path
        timestamp = str(int(time.time()))
        material = f"{self.settings.app_id}{timestamp}{api_path}{self.settings.app_secret}".encode("utf-8")
        signature = base64.b64encode(hashlib.sha256(material).digest()).decode("ascii")
        payload = None if body is None else compact_json(body).encode("utf-8")
        request = urllib.request.Request(
            self.settings.api_base + path,
            data=payload,
            method=method,
            headers={
                "Accept": "application/json",
                "User-Agent": "mpv-dandanplay-bridge/1.0",
                "X-AppId": self.settings.app_id,
                "X-Timestamp": timestamp,
                "X-Signature": signature,
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            message = error.headers.get("X-Error-Message") or error.reason
            raise BridgeError(f"API 请求被拒绝（HTTP {error.code}）：{message}") from error
        except urllib.error.URLError as error:
            raise BridgeError(f"无法连接弹弹play API：{error.reason}") from error
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BridgeError("API 返回了无法解析的数据") from error
        if not isinstance(result, dict):
            raise BridgeError("API 返回格式异常")
        if result.get("success") is False:
            raise BridgeError(str(result.get("errorMessage") or "API 返回失败"))
        return result

    def match(self, filename: str, file_hash: str) -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/v2/match",
            body={"fileName": filename, "fileHash": file_hash, "matchMode": "hashAndFileName"},
        )

    def comments(self, episode_id: int) -> dict[str, Any]:
        return self.request("GET", f"/api/v2/comment/{episode_id}?withRelated=true&chConvert=0")

    def anime_search(self, keyword: str) -> dict[str, Any]:
        return self.request("GET", "/api/v2/search/anime?keyword=" + urllib.parse.quote(keyword))

    def bangumi(self, anime_id: int) -> dict[str, Any]:
        return self.request("GET", f"/api/v2/bangumi/{anime_id}")


def file_md5_prefix(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        digest.update(source.read(HASH_BYTES))
    return digest.hexdigest()


def video_fingerprint(path: Path) -> tuple[str, str]:
    stat = path.stat()
    digest = file_md5_prefix(path)
    # Path is not used: copying a file should reuse its correct association.
    return f"{stat.st_size}:{digest}", digest


def cache_paths(settings: Settings) -> tuple[Path, Path]:
    return settings.cache_dir / "matches.json", settings.cache_dir / "comments"


def choose_match(data: dict[str, Any]) -> dict[str, Any] | None:
    matches = data.get("matches")
    if not data.get("isMatched") or not isinstance(matches, list) or not matches:
        return None
    first = matches[0]
    if not isinstance(first, dict) or not first.get("episodeId"):
        return None
    return first


def ass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\r", "").replace("\n", "\\N")


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours)}:{int(minutes):02d}:{seconds:05.2f}"


def ass_colour(rgb_decimal: int) -> str:
    rgb = int(rgb_decimal) & 0xFFFFFF
    red = (rgb >> 16) & 0xFF
    green = (rgb >> 8) & 0xFF
    blue = rgb & 0xFF
    return f"&H{blue:02X}{green:02X}{red:02X}&"


def parse_comments(payload: dict[str, Any], maximum: int) -> list[tuple[float, int, int, str]]:
    raw_comments = payload.get("comments")
    if not isinstance(raw_comments, list):
        return []
    result: list[tuple[float, int, int, str]] = []
    for item in raw_comments:
        if not isinstance(item, dict):
            continue
        fields = str(item.get("p", "")).split(",")
        text = item.get("m")
        if len(fields) < 3 or not isinstance(text, str) or not text.strip():
            continue
        try:
            timestamp = float(fields[0])
            mode = int(float(fields[1]))
            colour = int(float(fields[2]))
        except ValueError:
            continue
        if timestamp < 0 or mode not in {1, 4, 5}:
            continue
        result.append((timestamp, mode, colour, text))
        if len(result) >= maximum:
            break
    return sorted(result, key=lambda entry: entry[0])


def ass_from_comments(comments: Iterable[tuple[float, int, int, str]], settings: Settings) -> str:
    header = f"""[Script Info]
Title: Dandanplay comments
ScriptType: v4.00+
PlayResX: {settings.play_res_x}
PlayResY: {settings.play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Danmaku,{settings.font_name},{settings.font_size},&H00FFFFFF,&H00FFFFFF,&H60000000,&H60000000,0,0,0,0,100,100,0,0,1,1.6,0.7,7,15,15,15,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    rows = [header]
    line_height = max(settings.font_size + 9, 32)
    scroll_lanes = max(1, (settings.play_res_y - line_height * 2) // line_height)
    still_lanes = max(1, min(8, scroll_lanes // 2))
    scroll_available = [0.0] * scroll_lanes
    top_available = [0.0] * still_lanes
    bottom_available = [0.0] * still_lanes
    still_duration = 4.5

    for timestamp, mode, colour, text in comments:
        colour_tag = f"\\c{ass_colour(colour)}"
        escaped = ass_escape(text)
        if mode == 1:
            lane = min(range(scroll_lanes), key=scroll_available.__getitem__)
            y = line_height + lane * line_height
            # A lane becomes available before the old comment fully leaves the
            # screen, keeping the screen populated without uncontrolled overlap.
            scroll_available[lane] = timestamp + settings.scroll_duration * 0.72
            tags = f"{{{colour_tag}\\an7\\move({settings.play_res_x + 30},{y},-900,{y})}}"
            end = timestamp + settings.scroll_duration
        else:
            available = top_available if mode == 5 else bottom_available
            lane = min(range(still_lanes), key=available.__getitem__)
            available[lane] = timestamp + still_duration
            if mode == 5:
                y = line_height + lane * line_height
                alignment = "\\an8"
            else:
                y = settings.play_res_y - line_height - lane * line_height
                alignment = "\\an2"
            tags = f"{{{colour_tag}{alignment}\\pos({settings.play_res_x // 2},{y})}}"
            end = timestamp + still_duration
        rows.append(f"Dialogue: 0,{ass_time(timestamp)},{ass_time(end)},Danmaku,,0,0,0,,{tags}{escaped}\n")
    return "".join(rows)


def load_cached_comments(settings: Settings, episode_id: int) -> tuple[dict[str, Any] | None, bool]:
    _, comment_dir = cache_paths(settings)
    path = comment_dir / f"{episode_id}.json"
    stored = read_json(path, None)
    if not isinstance(stored, dict) or not isinstance(stored.get("payload"), dict):
        return None, False
    ttl = settings.comment_cache_ttl_hours * 3600
    fresh = ttl > 0 and time.time() - float(stored.get("saved_at", 0)) < ttl
    return stored["payload"], fresh


def fetch_comments(client: DandanplayClient, settings: Settings, episode_id: int, force: bool) -> tuple[dict[str, Any], bool]:
    cached, fresh = load_cached_comments(settings, episode_id)
    if cached is not None and fresh and not force:
        return cached, True
    payload = client.comments(episode_id)
    _, comment_dir = cache_paths(settings)
    write_json(comment_dir / f"{episode_id}.json", {"saved_at": time.time(), "payload": payload})
    return payload, False


def write_ass(settings: Settings, episode_id: int, payload: dict[str, Any]) -> tuple[Path, int]:
    comments = parse_comments(payload, settings.max_comments)
    output_dir = settings.cache_dir / "ass"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{episode_id}.ass"
    output.write_text(ass_from_comments(comments, settings), encoding="utf-8-sig")
    return output, len(comments)


def match_for_file(client: DandanplayClient, settings: Settings, video: Path, force: bool) -> tuple[dict[str, Any] | None, bool]:
    fingerprint, prefix_hash = video_fingerprint(video)
    matches_path, _ = cache_paths(settings)
    cached = read_json(matches_path, {})
    cached_entry = cached.get(fingerprint) if isinstance(cached, dict) else None
    if isinstance(cached_entry, dict) and cached_entry.get("episodeId") and not force:
        return cached_entry, True
    response = client.match(video.name, prefix_hash)
    selected = choose_match(response)
    if selected:
        cached = cached if isinstance(cached, dict) else {}
        cached[fingerprint] = selected
        write_json(matches_path, cached)
    return selected, False


def fetch_command(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings.load(Path(args.config))
    client = DandanplayClient(settings)
    if args.episode_id:
        episode = {"episodeId": int(args.episode_id), "animeTitle": "手动选择", "episodeTitle": ""}
        match_cache_hit = False
    else:
        video = Path(args.file)
        if not video.is_file():
            raise BridgeError("当前媒体不是可读取的本地文件")
        episode, match_cache_hit = match_for_file(client, settings, video, args.force)
        if episode is None:
            return {"ok": False, "reason": "not_matched", "message": "未自动识别；按 Ctrl+d 用文件名搜索候选集"}
    episode_id = int(episode["episodeId"])
    payload, comment_cache_hit = fetch_comments(client, settings, episode_id, args.force)
    ass_path, count = write_ass(settings, episode_id, payload)
    return {
        "ok": True,
        "episode_id": episode_id,
        "anime_title": str(episode.get("animeTitle", "")),
        "episode_title": str(episode.get("episodeTitle", "")),
        "ass_path": str(ass_path),
        "count": count,
        "match_cache_hit": match_cache_hit,
        "comment_cache_hit": comment_cache_hit,
    }


def episode_number_from_text(value: str) -> int | None:
    patterns = [r"[. _\-]S\d{1,2}E(\d{1,3})\b", r"[. _\-]E(\d{1,3})\b", r"第\s*(\d{1,3})\s*[话集]", r"\b(\d{1,3})\b"]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def search_command(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings.load(Path(args.config))
    client = DandanplayClient(settings)
    query = args.query.strip()
    if not query:
        raise BridgeError("搜索关键词为空")
    expected_episode = episode_number_from_text(query)
    animes = client.anime_search(query).get("animes", [])
    if not isinstance(animes, list):
        animes = []
    candidates: list[dict[str, Any]] = []
    for anime in animes[:5]:
        if not isinstance(anime, dict) or not anime.get("animeId"):
            continue
        detail = client.bangumi(int(anime["animeId"])).get("bangumi", {})
        episodes = detail.get("episodes", []) if isinstance(detail, dict) else []
        if not isinstance(episodes, list):
            continue
        filtered = episodes
        if expected_episode is not None:
            exact = [item for item in episodes if isinstance(item, dict) and str(item.get("episodeNumber", "")) == str(expected_episode)]
            if exact:
                filtered = exact
        for episode in filtered[:4]:
            if not isinstance(episode, dict) or not episode.get("episodeId"):
                continue
            candidates.append(
                {
                    "episode_id": int(episode["episodeId"]),
                    "anime_title": str(anime.get("animeTitle", "")),
                    "episode_title": str(episode.get("episodeTitle", "")),
                    "episode_number": str(episode.get("episodeNumber", "")),
                }
            )
            if len(candidates) >= 9:
                return {"ok": True, "candidates": candidates}
    return {"ok": True, "candidates": candidates}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="private JSON configuration path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser("fetch", help="match/load a local video and write ASS")
    fetch.add_argument("--file", default="")
    fetch.add_argument("--episode-id", type=int)
    fetch.add_argument("--force", action="store_true", help="ignore local caches")
    subparsers.add_parser("search", help="search selectable episode candidates").add_argument("--query", required=True)
    args = parser.parse_args(argv)
    try:
        result = fetch_command(args) if args.command == "fetch" else search_command(args)
        return emit(result, 0)
    except BridgeError as error:
        return emit({"ok": False, "reason": "error", "message": str(error)}, 1)
    except Exception as error:  # keep MPV from receiving a Python traceback
        return emit({"ok": False, "reason": "internal_error", "message": f"内部错误：{error}"}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
