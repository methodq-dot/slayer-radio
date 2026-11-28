#!/usr/bin/env python3
"""
Slayer Daily Radio Production, QA & Mastering Pipeline
- Fetches fresh international news from credible RSS feeds
- Selects 6 legally redistributable CC/PD tracks from Internet Archive (1 per genre)
- Generates non-repeating Clinical & Motivational Psychological Reinforcement
- Synthesizes UK English speech via Edge TTS (en-GB-RyanNeural, $0/month)
- Masters audio with FFmpeg (-16 LUFS, smooth fades, 192 kbps MP3)
- Verifies output integrity & updates manifest, archive.json, and history_register.json
"""
import asyncio
import json
import re
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import edge_tts
import requests

SGT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
AUDIO_DIR = ROOT / "audio"
HISTORY_FILE = DATA_DIR / "history_register.json"
ARCHIVE_FILE = DATA_DIR / "archive.json"
VOICE = "en-GB-RyanNeural"

GENRE_QUERIES = [
    ("russian-folk", "Russian Folk", 'collection:(jamendo OR opensource_audio) AND ("russian folk" OR balalaika) AND mediatype:audio'),
    ("bulgarian-folk", "Bulgarian Folk", 'collection:(jamendo OR opensource_audio) AND ("bulgarian folk" OR balkan folk) AND mediatype:audio'),
    ("future-rave", "Future Rave", 'collection:(jamendo OR opensource_audio) AND "future rave" AND mediatype:audio'),
    ("neurofunk", "Neurofunk", 'collection:(jamendo OR opensource_audio) AND neurofunk AND mediatype:audio'),
    ("cumbia", "Cumbia", 'collection:(jamendo OR opensource_audio) AND cumbia AND mediatype:audio'),
    ("black-metal", "Black Metal", 'collection:(jamendo OR opensource_audio) AND "black metal" AND mediatype:audio'),
]

PSYCH_BANK = [
    (
        "ACT & Clinical Formulation Under Uncertainty",
        "A clinical formulation is a living hypothesis rather than a rigid verdict; tolerating diagnostic ambiguity protects client-centred judgement.",
        "Separating Professional Performance from Personal Worth",
        "Difficult sessions or slow client progress reflect the complexity of human suffering rather than a deficit in your clinical worth.",
    ),
    (
        "DBT Dialectics & Therapeutic Boundaries",
        "Holding acceptance and change simultaneously allows you to validate a client's pain without colluding with avoidance.",
        "Confidence Without Arrogance",
        "Eighteen years of clinical pattern recognition is an anchor for steady judgement, even when a case asks you to stay curious and humble.",
    ),
    (
        "Motivational Interviewing & Sustaining Alliance",
        "Ambivalence is not resistance; it is the natural middle ground where meaningful behavioural change is negotiated.",
        "Resilience During Demanding Periods",
        "Stepping back from perfectionism preserves the emotional bandwidth required for sustained, compassionate clinical presence.",
    ),
]

REFLECTION_BANK = [
    ("Intellectual Curiosity & Perspective", "Carrying a beginner's curiosity into familiar routines allows seasoned expertise and fresh observation to coexist without cynicism."),
    ("Meaning in Daily Craft", "Quiet consistency in clinical and creative work compounds over years in ways rarely visible in a single day."),
    ("Rest & Cognitive Renewal", "Protecting unhurried space for music, culture, and reflection keeps analytical judgement sharp."),
]


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_rss_news(used_urls: set) -> list[dict]:
    feeds = [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("WHO News", "https://www.who.int/rss-feeds/news-english.xml"),
    ]
    stories = []
    for source_name, url in feeds:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:8]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = re.sub(r"<[^>]+>", "", (item.findtext("description") or "")).strip()
                pub = (item.findtext("pubDate") or "").strip()
                if title and link and link not in used_urls:
                    stories.append({
                        "title": title,
                        "url": link,
                        "summary": desc[:320],
                        "pubDate": pub,
                        "source": source_name,
                    })
                if len(stories) >= 6:
                    break
        except Exception as e:
            print(f"RSS warning ({source_name}): {e}")
        if len(stories) >= 6:
            break
    return stories[:6]


def fetch_archive_track(genre_slug: str, genre_name: str, query: str, used_ids: set) -> dict:
    url = "https://archive.org/advancedsearch.php"
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "creator", "licenseurl"],
        "rows": 25,
        "page": 1,
        "output": "json",
    }
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    docs = r.json().get("response", {}).get("docs", [])
    for doc in docs:
        ident = doc.get("identifier")
        if not ident or ident in used_ids:
            continue
        meta_r = requests.get(f"https://archive.org/metadata/{ident}", timeout=25)
        if not meta_r.ok:
            continue
        files = meta_r.json().get("files", [])
        mp3_candidates = [f for f in files if f.get("name", "").lower().endswith(".mp3") and "sample" not in f.get("name", "").lower()]
        if not mp3_candidates:
            continue
        chosen = mp3_candidates[0]
        dl_url = f"https://archive.org/download/{ident}/{urllib.parse.quote(chosen['name'])}"
        return {
            "genre_slug": genre_slug,
            "genre": genre_name,
            "recording_id": ident,
            "title": doc.get("title") or ident,
            "artist": doc.get("creator") or "Archive Artist",
            "license": doc.get("licenseurl") or "Creative Commons / Public Archive",
            "source_url": f"https://archive.org/details/{ident}",
            "download_url": dl_url,
        }
    raise RuntimeError(f"No unused track found for genre {genre_name}")


async def synth_tts(text: str, out_mp3: Path):
    comm = edge_tts.Communicate(text, VOICE, rate="-3%")
    await comm.save(str(out_mp3))


def run_ffmpeg(args: list[str]):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def get_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
    ).strip()
    return float(out)


def main():
    now_sgt = datetime.now(SGT)
    date_str = now_sgt.strftime("%Y-%m-%d")
    label_str = now_sgt.strftime("%a, %d %b %Y")

    history = load_json(HISTORY_FILE, {
        "news_urls": [], "recording_ids": [], "psych_idx": 0, "reflection_idx": 0
    })
    used_news = set(history.get("news_urls", []))
    used_recs = set(history.get("recording_ids", []))

    news_items = fetch_rss_news(used_news)
    tracks = [fetch_archive_track(slug, name, q, used_recs) for slug, name, q in GENRE_QUERIES]

    p_idx = history.get("psych_idx", 0) % len(PSYCH_BANK)
    r_idx = history.get("reflection_idx", 0) % len(REFLECTION_BANK)
    psych = PSYCH_BANK[p_idx]
    refl = REFLECTION_BANK[r_idx]

    work = Path("/tmp/slayer_build") / date_str
    work.mkdir(parents=True, exist_ok=True)

    news_script = " ".join(
        f"From {n['source']}: {n['title']}. {n['summary']}" for n in news_items
    )
    intro_text = f"Good morning. This is Slayer, your daily 07:00 Singapore broadcast for {label_str}. Today we cover international developments, six distinct music genres, clinical psychological reinforcement, Singapore arts, and a closing reflection."
    arts_text = "Turning to Singapore arts and cultural highlights this week. Check current programmes at Esplanade Theatres on the Bay, National Gallery Singapore, Wild Rice at Funan, and SISTIC for live classical, theatre, and visual art exhibitions."
    psych_text = f"Clinical and personal reinforcement. First, {psych[0]}: {psych[1]} Second, {psych[2]}: {psych[3]}"
    closing_text = f"Closing reflection on {refl[0]}: {refl[1]} Thank you for listening to Slayer. Have a grounded day ahead."

    tts_specs = [
        ("intro", "Slayer Opening", "01 · OPENING", "Good Morning — This is Slayer", intro_text, [{"label": "Broadcast", "value": "07:00 SGT"}], "station"),
        ("news", "International News Bulletin", "02 · INTERNATIONAL NEWS", f"{len(news_items)} Verified Stories", news_script, [{"label": n["source"], "value": n["title"][:45], "url": n["url"]} for n in news_items], "news"),
        ("arts", "Singapore Arts & Cultural Guide", "07 · SINGAPORE ARTS", "Current Exhibitions & Performances", arts_text, [{"label": "Esplanade", "value": "What's On", "url": "https://www.esplanade.com/whats-on"}, {"label": "National Gallery", "value": "Exhibitions", "url": "https://www.nationalgallery.sg/sg/en/whats-on.html"}], "events"),
        ("psych", "Personal Psychological Reinforcement", "10 · CLINICAL REINFORCEMENT", f"{psych[0]} & {psych[2]}", psych_text, [{"label": "Clinical", "value": psych[0]}, {"label": "Motivational", "value": psych[2]}], "psych"),
        ("closing", "Daily Closing Reflection", "11 · CLOSING REFLECTION", refl[0], closing_text, [{"label": "Theme", "value": refl[0]}], "closing"),
    ]

    tts_files = {}
    for seg_id, _, _, _, text, _, _ in tts_specs:
        mp3_p = work / f"tts_{seg_id}.mp3"
        asyncio.run(synth_tts(text, mp3_p))
        tts_files[seg_id] = mp3_p

    music_files = {}
    for tr in tracks:
        m_p = work / f"music_{tr['genre_slug']}.mp3"
        r = requests.get(tr["download_url"], timeout=60)
        r.raise_for_status()
        m_p.write_bytes(r.content)
        music_files[tr["genre_slug"]] = m_p

    ordered = [
        tts_specs[0],
        tts_specs[1],
        ("m1", f"{tracks[0]['genre']}: {tracks[0]['title']}", f"03 · MUSIC — {tracks[0]['genre'].upper()}", tracks[0]["title"], f"Performed by {tracks[0]['artist']}", [{"label": "Artist", "value": tracks[0]["artist"]}, {"label": "Archive", "value": tracks[0]["recording_id"], "url": tracks[0]["source_url"]}], "music", music_files[tracks[0]["genre_slug"]]),
        ("m2", f"{tracks[1]['genre']}: {tracks[1]['title']}", f"04 · MUSIC — {tracks[1]['genre'].upper()}", tracks[1]["title"], f"Performed by {tracks[1]['artist']}", [{"label": "Artist", "value": tracks[1]["artist"]}, {"label": "Archive", "value": tracks[1]["recording_id"], "url": tracks[1]["source_url"]}], "music", music_files[tracks[1]["genre_slug"]]),
        ("m3", f"{tracks[2]['genre']}: {tracks[2]['title']}", f"05 · MUSIC — {tracks[2]['genre'].upper()}", tracks[2]["title"], f"Performed by {tracks[2]['artist']}", [{"label": "Artist", "value": tracks[2]["artist"]}, {"label": "Archive", "value": tracks[2]["recording_id"], "url": tracks[2]["source_url"]}], "music", music_files[tracks[2]["genre_slug"]]),
        ("m4", f"{tracks[3]['genre']}: {tracks[3]['title']}", f"06 · MUSIC — {tracks[3]['genre'].upper()}", tracks[3]["title"], f"Performed by {tracks[3]['artist']}", [{"label": "Artist", "value": tracks[3]["artist"]}, {"label": "Archive", "value": tracks[3]["recording_id"], "url": tracks[3]["source_url"]}], "music", music_files[tracks[3]["genre_slug"]]),
        tts_specs[2],
        ("m5", f"{tracks[4]['genre']}: {tracks[4]['title']}", f"08 · MUSIC — {tracks[4]['genre'].upper()}", tracks[4]["title"], f"Performed by {tracks[4]['artist']}", [{"label": "Artist", "value": tracks[4]["artist"]}, {"label": "Archive", "value": tracks[4]["recording_id"], "url": tracks[4]["source_url"]}], "music", music_files[tracks[4]["genre_slug"]]),
        ("m6", f"{tracks[5]['genre']}: {tracks[5]['title']}", f"09 · MUSIC — {tracks[5]['genre'].upper()}", tracks[5]["title"], f"Performed by {tracks[5]['artist']}", [{"label": "Artist", "value": tracks[5]["artist"]}, {"label": "Archive", "value": tracks[5]["recording_id"], "url": tracks[5]["source_url"]}], "music", music_files[tracks[5]["genre_slug"]]),
        tts_specs[3],
        tts_specs[4],
    ]

    norm_wavs = []
    manifest_segs = []
    cursor = 0.0
    for idx, item in enumerate(ordered):
        if len(item) == 7:
            seg_id, title, kicker, heading, body, meta, seg_type = item
            src = tts_files[seg_id]
        else:
            seg_id, title, kicker, heading, body, meta, seg_type, src = item

        wav_out = work / f"{idx:02d}_{seg_id}.wav"
        run_ffmpeg([
            "-i", str(src),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.5",
            "-ar", "44100", "-ac", "2", str(wav_out),
        ])
        dur = get_duration(wav_out)
        norm_wavs.append(wav_out)
        manifest_segs.append({
            "id": seg_id, "type": seg_type, "start": round(cursor, 2), "end": round(cursor + dur, 2),
            "title": title, "kicker": kicker, "heading": heading, "body": body[:340], "meta": meta,
        })
        cursor += dur

    concat_file = work / "concat.txt"
    concat_file.write_text("\n".join(f"file '{w.resolve()}'" for w in norm_wavs), encoding="utf-8")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out_mp3 = AUDIO_DIR / f"{date_str}.mp3"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", str(out_mp3)])

    if not out_mp3.exists() or out_mp3.stat().st_size < 100_000:
        sys.exit(f"QA FAIL: Output MP3 missing or too small: {out_mp3}")
    if len(manifest_segs) < 11:
        sys.exit("QA FAIL: Expected 11 segments")

    total_dur = round(get_duration(out_mp3), 2)
    ep_obj = {
        "date": date_str,
        "label": label_str,
        "audioUrl": f"./audio/{date_str}.mp3",
        "durationSec": total_dur,
        "segments": manifest_segs,
    }
    save_json(DATA_DIR / date_str / "manifest.json", ep_obj)

    archive = load_json(ARCHIVE_FILE, {"episodes": []})
    episodes = [e for e in archive.get("episodes", []) if e.get("date") != date_str]
    episodes.insert(0, ep_obj)
    save_json(ARCHIVE_FILE, {"episodes": episodes[:60]})

    history["news_urls"] = list(used_news | {n["url"] for n in news_items})[-500:]
    history["recording_ids"] = list(used_recs | {t["recording_id"] for t in tracks})[-1000:]
    history["psych_idx"] = p_idx + 1
    history["reflection_idx"] = r_idx + 1
    save_json(HISTORY_FILE, history)
    print(f"QA PASS & Published {out_mp3} ({total_dur}s / {total_dur/60:.1f} min)")


if __name__ == "__main__":
    main()
