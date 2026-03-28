from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from dataclasses import dataclass
from html import unescape
from typing import Any
from xml.etree import ElementTree

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

from flask import Flask, Response, jsonify, render_template, request
import requests
from youtube_transcript_api import (
    IpBlocked,
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    RequestBlocked,
    Transcript,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

YOUTUBE_WATCH_URL = "https://www.youtube.com/watch"
ANALYSIS_CACHE_TTL = 60 * 15
SEGMENT_CACHE_TTL = 60 * 30
FETCH_RETRIES = 3
RATE_LIMIT_MESSAGE = (
    "YouTube is rate-limiting this server right now. Please try again in a minute, "
    "try a different video, or use the app from a different network."
)
WATCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class SubtitleError(Exception):
    pass


@dataclass
class CaptionSegment:
    start: float
    duration: float
    text: str

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class CacheEntry:
    expires_at: float
    value: Any


ANALYSIS_CACHE: dict[str, CacheEntry] = {}
SEGMENT_CACHE: dict[tuple[str, str, str], CacheEntry] = {}
TRACK_URL_CACHE: dict[tuple[str, str], CacheEntry] = {}


def transcript_api() -> YouTubeTranscriptApi:
    return YouTubeTranscriptApi()


def cache_get(store: dict[Any, CacheEntry], key: Any) -> Any | None:
    entry = store.get(key)
    if not entry:
        return None
    if entry.expires_at <= time.time():
        store.pop(key, None)
        return None
    return entry.value


def cache_set(store: dict[Any, CacheEntry], key: Any, value: Any, ttl_seconds: int) -> Any:
    store[key] = CacheEntry(expires_at=time.time() + ttl_seconds, value=value)
    return value


def extract_video_id(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise SubtitleError("A YouTube link is required.")

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme and parsed.netloc:
        host = parsed.netloc.lower()
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = parsed.path.strip("/")
        elif "youtube.com" in host:
            if parsed.path == "/watch":
                video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
            elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
                video_id = parsed.path.strip("/").split("/", 1)[1]
            else:
                video_id = ""
        else:
            raise SubtitleError("The URL must point to YouTube.")
    else:
        video_id = raw

    if not re.fullmatch(r"[\w-]{11}", video_id):
        raise SubtitleError("Unable to extract a valid YouTube video ID.")
    return video_id


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers=headers or WATCH_HEADERS)
    last_error: Exception | None = None
    for attempt in range(FETCH_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                if attempt < FETCH_RETRIES - 1:
                    time.sleep(1.25 * (attempt + 1))
                    continue
                raise SubtitleError(RATE_LIMIT_MESSAGE) from exc
            raise SubtitleError(f"YouTube returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < FETCH_RETRIES - 1:
                time.sleep(0.75 * (attempt + 1))
                continue
            raise SubtitleError("Could not reach YouTube.") from exc
    raise SubtitleError("Could not reach YouTube.") from last_error


def extract_player_response(html: str) -> dict[str, Any]:
    patterns = [
        r"ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;",
        r"var\s+ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise SubtitleError("Could not read the video metadata from YouTube.")


def fallback_video_details(video_id: str) -> dict[str, Any]:
    return {
        "title": f"YouTube Video ({video_id})",
        "author": "Unknown channel",
        "lengthSeconds": "0",
    }


def build_track_id(language_code: str, is_generated: bool) -> str:
    return f"{language_code}::{'generated' if is_generated else 'manual'}"


def parse_track_id(track_id: str) -> tuple[str, bool]:
    language_code, separator, variant = track_id.partition("::")
    if not separator or not language_code or variant not in {"manual", "generated"}:
        raise SubtitleError("Invalid subtitle track selection.")
    return language_code, variant == "generated"


def normalize_caption_text(text: str) -> str:
    cleaned = unescape(text.replace("\n", " ").replace("\r", " "))
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def format_timestamp(seconds: float, for_srt: bool = False) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    separator = "," if for_srt else "."
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{ms:03}"


def to_preview_rows(segments: list[CaptionSegment]) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "start": format_timestamp(segment.start),
            "end": format_timestamp(segment.end),
            "duration": round(segment.duration, 3),
            "text": segment.text,
        }
        for index, segment in enumerate(segments, start=1)
    ]


def build_document(segments: list[CaptionSegment], file_format: str) -> tuple[str, str]:
    fmt = file_format.lower()
    if fmt == "srt":
        content = "\n\n".join(
            "\n".join(
                [
                    str(index),
                    f"{format_timestamp(segment.start, True)} --> {format_timestamp(segment.end, True)}",
                    segment.text,
                ]
            )
            for index, segment in enumerate(segments, start=1)
        )
        return content + "\n", "text/srt; charset=utf-8"

    if fmt == "txt":
        content = "\n".join(
            f"[{format_timestamp(segment.start)}] {segment.text}" for segment in segments
        )
        return content + "\n", "text/plain; charset=utf-8"

    if fmt == "csv":
        rows = ['"index","start","end","duration","text"']
        for index, segment in enumerate(segments, start=1):
            escaped = segment.text.replace('"', '""')
            rows.append(
                f'"{index}","{format_timestamp(segment.start)}","{format_timestamp(segment.end)}",'
                f'"{segment.duration:.3f}","{escaped}"'
            )
        return "\n".join(rows) + "\n", "text/csv; charset=utf-8"

    if fmt == "vtt":
        body = "\n\n".join(
            "\n".join(
                [
                    f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}",
                    segment.text,
                ]
            )
            for segment in segments
        )
        return f"WEBVTT\n\n{body}\n", "text/vtt; charset=utf-8"

    if fmt == "json":
        content = json.dumps(to_preview_rows(segments), indent=2)
        return content, "application/json; charset=utf-8"

    raise SubtitleError("Unsupported output format.")


def store_track_url(video_id: str, track_id: str, transcript_url: str) -> None:
    cache_set(TRACK_URL_CACHE, (video_id, track_id), transcript_url, SEGMENT_CACHE_TTL)


def fetch_segments_from_cached_url(transcript_url: str, target_language: str | None) -> list[CaptionSegment]:
    url = transcript_url if not target_language else f"{transcript_url}&tlang={urllib.parse.quote(target_language)}"
    response = requests.get(url, timeout=20)
    if response.status_code == 429:
        raise SubtitleError(RATE_LIMIT_MESSAGE)
    if response.status_code >= 400:
        raise SubtitleError(f"YouTube returned HTTP {response.status_code}.")

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as exc:
        raise SubtitleError("Could not parse subtitle data returned by YouTube.") from exc

    segments = []
    for node in root:
        raw_text = node.text or ""
        text = normalize_caption_text(raw_text)
        if not text:
            continue
        segments.append(
            CaptionSegment(
                start=float(node.attrib.get("start", "0") or 0),
                duration=float(node.attrib.get("dur", "0") or 0),
                text=text,
            )
        )

    if not segments:
        raise SubtitleError("The selected subtitle track is empty.")
    return segments


def resolve_transcript(video_id: str, track_id: str) -> Transcript:
    language_code, is_generated = parse_track_id(track_id)
    transcript_list = transcript_api().list(video_id)
    for transcript in transcript_list:
        if transcript.language_code == language_code and transcript.is_generated == is_generated:
            store_track_url(video_id, track_id, transcript._url)
            return transcript
    raise SubtitleError("The selected subtitle track is no longer available.")


def fetch_caption_segments(
    video_id: str, track_id: str, target_language: str | None = None
) -> list[CaptionSegment]:
    cache_key = (video_id, track_id, target_language or "")
    cached_segments = cache_get(SEGMENT_CACHE, cache_key)
    if cached_segments is not None:
        return cached_segments

    try:
        transcript = resolve_transcript(video_id, track_id)
        if target_language and target_language != transcript.language_code:
            transcript = transcript.translate(target_language)
        fetched = transcript.fetch()
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        raise SubtitleError("This video does not expose that subtitle track.")
    except NotTranslatable:
        raise SubtitleError("The selected subtitle track cannot be translated.")
    except TranslationLanguageNotAvailable:
        raise SubtitleError("That target language is not available for this subtitle track.")
    except (IpBlocked, RequestBlocked):
        cached_url = cache_get(TRACK_URL_CACHE, (video_id, track_id))
        if cached_url:
            segments = fetch_segments_from_cached_url(cached_url, target_language)
            return cache_set(SEGMENT_CACHE, cache_key, segments, SEGMENT_CACHE_TTL)
        raise SubtitleError(RATE_LIMIT_MESSAGE)
    except PoTokenRequired:
        raise SubtitleError("YouTube requires an additional access token for this transcript right now.")

    segments = [
        CaptionSegment(
            start=float(snippet.start),
            duration=float(snippet.duration),
            text=normalize_caption_text(snippet.text),
        )
        for snippet in fetched
        if normalize_caption_text(snippet.text)
    ]
    if not segments:
        raise SubtitleError("The selected subtitle track is empty.")
    return cache_set(SEGMENT_CACHE, cache_key, segments, SEGMENT_CACHE_TTL)


def analyze_video(video_url: str) -> dict[str, Any]:
    video_id = extract_video_id(video_url)
    cached_analysis = cache_get(ANALYSIS_CACHE, video_id)
    if cached_analysis is not None:
        return cached_analysis

    try:
        transcript_list = transcript_api().list(video_id)
    except (IpBlocked, RequestBlocked):
        raise SubtitleError(RATE_LIMIT_MESSAGE)
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        raise SubtitleError("This video does not expose accessible subtitle tracks.")

    try:
        html = fetch_text(f"{YOUTUBE_WATCH_URL}?v={video_id}&hl=en")
        player_response = extract_player_response(html)
        video_details = player_response.get("videoDetails", {})
        metadata_notice = None
    except SubtitleError:
        video_details = fallback_video_details(video_id)
        metadata_notice = "Loaded subtitles without full video metadata because YouTube limited the page request."

    tracks = []
    translation_index: dict[str, str] = {}
    found_track = False

    for transcript in transcript_list:
        found_track = True
        translation_languages = [
            {
                "language_code": language.language_code,
                "language_name": language.language,
            }
            for language in transcript.translation_languages
        ]
        track_id = build_track_id(transcript.language_code, transcript.is_generated)
        store_track_url(video_id, track_id, transcript._url)
        for language in translation_languages:
            translation_index[language["language_code"]] = language["language_name"]
        tracks.append(
            {
                "track_id": track_id,
                "language_code": transcript.language_code,
                "language_name": transcript.language,
                "kind": "asr" if transcript.is_generated else "standard",
                "is_asr": transcript.is_generated,
                "can_translate": transcript.is_translatable,
                "translation_languages": translation_languages,
            }
        )

    if not found_track:
        raise SubtitleError("No subtitle tracks were found for this video.")

    analysis = {
        "video_id": video_id,
        "title": video_details.get("title", "Untitled video"),
        "author": video_details.get("author", "Unknown channel"),
        "length_seconds": int(video_details.get("lengthSeconds", "0") or 0),
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "tracks": tracks,
        "translation_languages": [
            {"language_code": code, "language_name": name}
            for code, name in sorted(translation_index.items(), key=lambda item: item[1].lower())
        ],
        "metadata_notice": metadata_notice,
    }
    return cache_set(ANALYSIS_CACHE, video_id, analysis, ANALYSIS_CACHE_TTL)


def safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value) or "subtitles"


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.post("/api/analyze")
    def api_analyze() -> Response:
        try:
            payload = request.get_json(silent=True) or {}
            result = analyze_video(payload.get("url", ""))
            return jsonify({"ok": True, "data": result})
        except SubtitleError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"ok": False, "error": "Unexpected server error while analyzing the video."}), 500

    @app.get("/api/captions")
    def api_captions() -> Response:
        video_id = request.args.get("video_id", "")
        track_id = request.args.get("track_id", "")
        target_language = request.args.get("tlang") or None
        file_format = request.args.get("format", "srt")
        title = request.args.get("title", "subtitles")
        download = request.args.get("download", "0") == "1"

        try:
            segments = fetch_caption_segments(video_id, track_id, target_language)
            content, mimetype = build_document(segments, file_format)
        except SubtitleError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"ok": False, "error": "Unexpected server error while fetching subtitles."}), 500

        filename = safe_filename(title)
        if target_language:
            filename = f"{filename}-{target_language}"
        filename = f"{filename}.{file_format.lower()}"

        response = Response(content, mimetype=mimetype)
        if download:
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @app.get("/api/preview")
    def api_preview() -> Response:
        video_id = request.args.get("video_id", "")
        track_id = request.args.get("track_id", "")
        target_language = request.args.get("tlang") or None

        try:
            segments = fetch_caption_segments(video_id, track_id, target_language)
        except SubtitleError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"ok": False, "error": "Unexpected server error while previewing subtitles."}), 500

        rows = to_preview_rows(segments)
        return jsonify({"ok": True, "data": {"rows": rows, "plain_text": "\n".join(row["text"] for row in rows)}})

    return app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug)
