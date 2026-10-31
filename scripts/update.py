#!/usr/bin/env python3
"""Rebuild data/videos.json: Jon Stewart's Daily Show monologues, fetched via YouTube Data API v3."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://www.googleapis.com/youtube/v3/"
STEWART_PLAYLIST = "PLeskMkEaHJYfTMaKwmBWGq4NogX9FLF2J"  # "Jon Stewart Hosting The Daily Show"
UPLOADS_PLAYLIST = "UUwWhs_6x42TyRM4Wstoq8HA"  # @TheDailyShow uploads; catches videos not yet in the playlist
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "videos.json"
OVERRIDES = ROOT / "data" / "overrides.json"
CLEF_CACHE = ROOT / "data" / "clef.json"
# When the rendered list itself last moved; committed with the state so it survives runs.
LAST_CHANGED = ROOT / "data" / "last-changed.txt"
# Both timestamps for the page; written every run but never committed (it would churn the data branch hourly).
STATUS = ROOT / "data" / "status.json"

# Measured Oct 2026: 93 of 95 monologues went up in the evening slot; there marker-less monologues scored >= 0.81
# and the 89 rejects (interviews at 23:30) <= 0.13. Outside it archive re-uploads score up to 0.8, so a human decides.
CLEF_EVENING = 0.5  # P(monologue) at or above, released in the evening slot: publish without review
CLEF_REVIEW = 0.45  # P(monologue) at or above: show in "Needs review"
NEW_YORK = ZoneInfo("America/New_York")
CLEF_QUESTION = {
    "format": {
        "type": "choice",
        "instructions": "This is a YouTube video from The Daily Show channel. Jon Stewart hosts on Mondays; other hosts "
        "(Ronny Chieng, Josh Johnson, Jordan Klepper, Michael Kosta, Desi Lydic) host Tuesday to Thursday. "
        "Which format is this video?",
        "criteria": {
            "monologue": "Jon Stewart's opening news segment from a single new episode, as one standalone video. "
            "A short appearance by a correspondent or guest inside it still counts.",
            "interview": "A conversation between Jon Stewart (or another host) and a guest.",
            "compilation": "A weekly recap combining segments of several hosts, a best-of, an After the Cut roundup, "
            "or a look back at archive clips from earlier years.",
            "other": "A segment hosted by someone other than Jon Stewart, a sketch, a short clip, or anything else.",
        },
    }
}
# Monologue descriptions open with a "0:00" chapter like "Jon Stewart's TDS Welcome" (reliable since mid-2025).
MARKER = re.compile(
    r"^\s*0?0:00\s*-?\s*(?:Jon Stewart['’]s TDS (?:Welcome|Open)|TDS Welcome from Jon Stewart)",
    re.I | re.M,
)
# Weekly compilations start with "Jon Stewart ..." too, but name other hosts in the title.
OTHER_HOSTS = re.compile(r"Kosta|Klepper|Ronny|Chieng|Desi|Lydic|Josh|News Team|Iwata|Kuhlenschmidt", re.I)
MIN_DURATION = 360  # shortest marker monologue so far is 7 min; Shorts and clips run 1-4 min


def get(endpoint, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def playlist_ids(playlist_id, max_pages):
    ids, token = [], ""
    for _ in range(max_pages):
        page = get("playlistItems", part="contentDetails", playlistId=playlist_id, maxResults=50, pageToken=token)
        ids += [item["contentDetails"]["videoId"] for item in page["items"]]
        token = page.get("nextPageToken")
        if not token:
            break
    return ids


def fetch_videos(ids):
    for i in range(0, len(ids), 50):
        yield from get("videos", part="snippet,contentDetails", id=",".join(ids[i : i + 50]))["items"]


def seconds(iso):
    d, h, m, s = (int(x or 0) for x in re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso).groups())
    return ((d * 24 + h) * 60 + m) * 60 + s


def ask_clef(title, description, duration, published):
    """Return Clef's P(monologue), or None when Clef is not configured or the call failed."""
    account, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not account or not token:
        return None
    state = {
        "title": title,
        "published": published,
        "duration_minutes": round(duration / 60, 1),
        # Drop the channel boilerplate: it mentions Jon Stewart on every video.
        "description": description.split("Subscribe to The Daily Show")[0].strip(),
    }
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/clef",
        data=json.dumps({"model": "clef", "state": state, "questions": CLEF_QUESTION}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["result"]["answers"]["format"]["probabilities"]["monologue"]
    except (urllib.error.URLError, KeyError) as e:
        # Out of free quota or a hiccup: fall back to the heuristic now, retry next run.
        print(f"Clef failed: {e}")
        return None


def evening(published):
    """Monologues go up right after the episode airs: 22:30 to 01:00 New York time, any day (specials air off-Monday)."""
    t = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(NEW_YORK)
    return (t.hour * 60 + t.minute - (22 * 60 + 30)) % (24 * 60) < 150


def classify(video_id, title, description, duration, overrides, p_monologue=None, published=""):
    """Return "monologue", "candidate" (needs a human look) or None."""
    if video_id in overrides["exclude"]:
        return None
    if video_id in overrides["include"]:
        return "monologue"
    # Shorts and multi-host weekly recaps (which reuse the "TDS Welcome" chapter) are never monologues.
    if duration < MIN_DURATION or OTHER_HOSTS.search(title):
        return None
    if MARKER.search(description):
        return "monologue"
    if p_monologue is not None:
        if p_monologue >= CLEF_EVENING and published and evening(published):
            return "monologue"
        return "candidate" if p_monologue >= CLEF_REVIEW else None
    # Without Clef: 2024 and early-2025 monologues lack the marker; surface them for manual review.
    if description.lstrip().startswith("Jon Stewart") and duration >= 480:
        return "candidate"
    return None


def main():
    overrides = json.loads(OVERRIDES.read_text())
    # The generated files live on the `data` branch, so a fresh clone has neither.
    clef = json.loads(CLEF_CACHE.read_text()) if CLEF_CACHE.exists() else {}
    stored = [v["id"] for v in json.loads(DATA.read_text())] if DATA.exists() else []
    # Re-fetching stored ids keeps metadata fresh (YouTube ToS: refresh within 30 days) and drops deleted videos.
    ids = playlist_ids(STEWART_PLAYLIST, 40) + playlist_ids(UPLOADS_PLAYLIST, 1) + overrides["include"] + stored
    out = []
    for v in fetch_videos(list(dict.fromkeys(ids))):
        sn, duration = v["snippet"], seconds(v["contentDetails"]["duration"])
        decided = (
            v["id"] in overrides["include"] + overrides["exclude"]
            or duration < MIN_DURATION
            or OTHER_HOSTS.search(sn["title"])
            or MARKER.search(sn["description"])
        )
        # ponytail: cached per video id forever; a later description edit is not re-asked (the marker still wins).
        if not decided and v["id"] not in clef:
            p = ask_clef(sn["title"], sn["description"], duration, sn["publishedAt"])
            if p is not None:
                clef[v["id"]] = round(p, 4)
        status = classify(v["id"], sn["title"], sn["description"], duration, overrides, clef.get(v["id"]), sn["publishedAt"])
        if status:
            out.append({"id": v["id"], "title": sn["title"], "published": sn["publishedAt"], "duration": duration, "status": status})
    out.sort(key=lambda v: v["published"], reverse=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    # "List last changed" only moves when the list itself moves; a metadata refresh alone does not count.
    previous = json.loads(DATA.read_text()) if DATA.exists() else None
    if previous != out:
        LAST_CHANGED.write_text(now + "\n")
    changed = LAST_CHANGED.read_text().strip() if LAST_CHANGED.exists() else now
    DATA.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    CLEF_CACHE.write_text(json.dumps(clef, indent=1, sort_keys=True) + "\n")
    STATUS.write_text(json.dumps({"changed": changed, "updated": now}, indent=1) + "\n")
    print(f"{sum(v['status'] == 'monologue' for v in out)} monologues, {sum(v['status'] == 'candidate' for v in out)} candidates")


if __name__ == "__main__":
    main()
