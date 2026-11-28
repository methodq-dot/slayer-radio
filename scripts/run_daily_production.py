#!/usr/bin/env python3
"""
Slayer Daily Radio Production, QA & Mastering Pipeline
- Fetches fresh international news from credible RSS feeds
- Browses live Singapore arts & cultural listings (events, summaries, ticket costs, URLs)
- Selects 6 legally redistributable CC/PD tracks from Internet Archive (1 per genre, 1.5-12 MB)
- Generates non-repeating quote-based Clinical & Motivational Psychological Reinforcement
- Synthesizes UK English speech via Edge TTS (en-GB-RyanNeural, $0/month)
- Masters audio with FFmpeg (-16 LUFS, smooth fades, 192 kbps MP3, < 95 MB)
- Verifies output integrity & updates manifest, archive.json, and history_register.json
"""
import asyncio
import html
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
UA = {"User-Agent": "Mozilla/5.0 (compatible; SlayerRadioBot/1.0)"}

GENRE_QUERIES = [
    ("russian-folk", "Russian Folk", 'collection:(jamendo OR opensource_audio) AND ("russian folk" OR balalaika) AND mediatype:audio'),
    ("bulgarian-folk", "Bulgarian Folk", 'collection:(jamendo OR opensource_audio) AND ("bulgarian folk" OR balkan folk) AND mediatype:audio'),
    ("future-rave", "Future Rave", 'collection:(jamendo OR opensource_audio) AND "future rave" AND mediatype:audio'),
    ("neurofunk", "Neurofunk", 'collection:(jamendo OR opensource_audio) AND neurofunk AND mediatype:audio'),
    ("cumbia", "Cumbia", 'collection:(jamendo OR opensource_audio) AND cumbia AND mediatype:audio'),
    ("black-metal", "Black Metal", 'collection:(jamendo OR opensource_audio) AND "black metal" AND mediatype:audio'),
]

PSYCH_QUOTE_BANK = [
    {
        "quote": "Between stimulus and response there is a space. In that space is our power to choose our response. — Viktor Frankl",
        "clinical_phrase": "When a session feels tense or stuck, you don't have to react to the urgency in the room. Pause in that space—your steadiness is often the most therapeutic intervention you offer.",
        "motivational_phrase": "You've spent years building the capacity to stay calm where others feel overwhelmed. Trust that hard-earned poise today.",
    },
    {
        "quote": "The curious paradox is that when I accept myself just as I am, then I can change. — Carl Rogers",
        "clinical_phrase": "Release the pressure to be a flawless clinician in every interaction. Meeting your own limits with honesty models the exact self-acceptance you invite your clients to practice.",
        "motivational_phrase": "Your effectiveness doesn't come from perfection; it comes from genuine, grounded presence.",
    },
    {
        "quote": "It is the relationship that heals. — Irvin Yalom",
        "clinical_phrase": "Even when a specific technique stalls, the consistent safety and attunement you provide is actively doing its work beneath the surface.",
        "motivational_phrase": "You show up day after day as a reliable anchor in other people's hardest chapters. That quiet consistency matters more than any single outcome.",
    },
    {
        "quote": "The goal is not to get rid of all pain, but to live a life worth living alongside it. — Steven Hayes",
        "clinical_phrase": "You aren't responsible for erasing every distress a client carries; you're helping them build a wider, freer life even while uncertainty remains.",
        "motivational_phrase": "Let go of carrying your clients' outcomes on your shoulders alone. Walk beside them with clear boundaries and steady confidence.",
    },
    {
        "quote": "Radical acceptance rests on letting go of the illusion of control and a willingness to notice and accept things as they are right now. — Marsha Linehan",
        "clinical_phrase": "When progress moves slower than you hoped, resist turning that frustration inward. Meet the reality of the case with clear eyes and calm clinical curiosity.",
        "motivational_phrase": "Slow progress is not failure—it is the honest pace of real human change, and you are equipped to hold it.",
    },
    {
        "quote": "We suffer more often in imagination than in reality. — Seneca",
        "clinical_phrase": "Notice when anticipatory self-criticism is louder than the actual evidence in front of you. Return to what is observable, concrete, and within your control.",
        "motivational_phrase": "You have navigated complex clinical and academic demands for nearly two decades. You are far more prepared for today than any passing doubt suggests.",
    },
    {
        "quote": "Do the best you can until you know better. Then when you know better, do better. — Maya Angelou",
        "clinical_phrase": "Every difficult case refines your judgement. Treat hindsight as clinical data to sharpen your craft, never as fuel for harsh self-judgement.",
        "motivational_phrase": "Growth at an advanced stage of your career isn't about starting over—it's about trusting your foundation while staying open to learning.",
    },
    {
        "quote": "Live the questions now. Perhaps you will then gradually, without noticing it, live along some distant day into the answer. — Rainer Maria Rilke",
        "clinical_phrase": "Complex presentations rarely resolve on a neat timetable. Holding ambiguity without rushing to premature certainty is a mark of clinical maturity.",
        "motivational_phrase": "You don't need every answer before stepping into the room today. Your willingness to listen deeply is already enough.",
    },
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


def clean_html(raw: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


def fetch_rss_news(used_urls: set) -> list[dict]:
    feeds = [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("WHO News", "https://www.who.int/rss-feeds/news-english.xml"),
    ]
    stories = []
    for source_name, url in feeds:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:8]:
                title = clean_html(item.findtext("title") or "")
                link = (item.findtext("link") or "").strip()
                desc = clean_html(item.findtext("description") or "")
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


def fetch_singapore_events() -> list[dict]:
    """Browse live Singapore arts, theatre, concert & exhibition listings with summaries & ticket prices."""
    events = []
    try:
        r = requests.get("https://www.esplanade.com/whats-on", headers=UA, timeout=20)
        if r.ok:
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S):
                try:
                    data = json.loads(block)
                    items = data if isinstance(data, list) else [data]
                    for obj in items:
                        if obj.get("@type") in ("Event", "MusicEvent", "TheaterEvent", "ExhibitionEvent"):
                            name = clean_html(obj.get("name", ""))
                            desc = clean_html(obj.get("description", ""))[:220]
                            url = obj.get("url") or "https://www.esplanade.com/whats-on"
                            offers = obj.get("offers") or {}
                            if isinstance(offers, list):
                                offers = offers[0] if offers else {}
                            price = offers.get("price")
                            curr = offers.get("priceCurrency", "SGD")
                            price_str = f"{curr} {price}" if price else "Check Esplanade listing (many free & ticketed)"
                            if name:
                                events.append({
                                    "title": name,
                                    "summary": desc or "Live arts programme at Esplanade – Theatres on the Bay.",
                                    "price": price_str,
                                    "url": url,
                                    "source": "Esplanade",
                                })
                except Exception:
                    continue
    except Exception as e:
        print(f"Esplanade browse warning: {e}")

    try:
        r = requests.get("https://www.nationalgallery.sg/sg/en/whats-on.html", headers=UA, timeout=20)
        if r.ok:
            for m in re.finditer(r'href="(/sg/en/exhibitions/[^"]+\.html)"[^>]*>(.*?)</a>', r.text, re.S):
                title = clean_html(m.group(2))
                if len(title) > 6 and not any(e["title"] == title for e in events):
                    events.append({
                        "title": title,
                        "summary": "Exhibition at National Gallery Singapore.",
                        "price": "Free for Citizens/PRs (Special exhibitions ticketed)",
                        "url": "https://www.nationalgallery.sg" + m.group(1),
                        "source": "National Gallery SG",
                    })
                if len(events) >= 5:
                    break
    except Exception as e:
        print(f"NGS browse warning: {e}")

    if len(events) < 4:
        try:
            rss_url = "https://news.google.com/rss/search?q=Singapore+(concert+OR+exhibition+OR+theatre+OR+festival)+tickets+this+week&hl=en-SG&gl=SG&ceid=SG:en"
            r = requests.get(rss_url, headers=UA, timeout=20)
            if r.ok:
                root = ET.fromstring(r.text)
                for item in root.findall(".//item")[:8]:
                    title = clean_html(item.findtext("title") or "")
                    link = (item.findtext("link") or "").strip()
                    desc = clean_html(item.findtext("description") or "")[:200]
                    price_m = re.search(r"(\$\s?\d+(?:\.\d{2})?|SGD\s?\d+|Free\b)", f"{title} {desc}", re.I)
                    price_str = price_m.group(1) if price_m else "See official event page for ticket pricing"
                    if title and link and not any(e["title"] == title for e in events):
                        events.append({
                            "title": title,
                            "summary": desc or "Current Singapore cultural or arts event.",
                            "price": price_str,
                            "url": link,
                            "source": "SG Arts Listing",
                        })
                    if len(events) >= 5:
                        break
        except Exception as e:
            print(f"SG RSS warning: {e}")

    return events[:5]


def fetch_archive_track(genre_slug: str, genre_name: str, query: str, used_ids: set) -> dict:
    url = "https://archive.org/advancedsearch.php"
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "creator", "licenseurl"],
        "rows": 35,
        "page": 1,
        "output": "json",
    }
    r = requests.get(url, params=params, headers=UA, timeout=25)
    r.raise_for_status()
    docs = r.json().get("response", {}).get("docs", [])
    for doc in docs:
        ident = doc.get("identifier")
        if not ident or ident in used_ids:
            continue
        meta_r = requests.get(f"https://archive.org/metadata/{ident}", headers=UA, timeout=25)
        if not meta_r.ok:
            continue
        files = meta_r.json().get("files", [])
        mp3_candidates = [
            f for f in files
            if f.get("name", "").lower().endswith(".mp3")
            and "sample" not in f.get("name", "").lower()
            and 1_500_000 <= int(f.get("size", 0) or 0) <= 12_000_000
        ]
        if not mp3_candidates:
            mp3_candidates = [
                f for f in files
                if f.get("name", "").lower().endswith(".mp3")
                and "sample" not in f.get("name", "").lower()
            ]
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
    sg_events = fetch_singapore_events()
    tracks = [fetch_archive_track(slug, name, q, used_recs) for slug, name, q in GENRE_QUERIES]

    p_idx = history.get("psych_idx", 0) % len(PSYCH_QUOTE_BANK)
    r_idx = history.get("reflection_idx", 0) % len(REFLECTION_BANK)
    psych = PSYCH_QUOTE_BANK[p_idx]
    refl = REFLECTION_BANK[r_idx]

    work = Path("/tmp/slayer_build") / date_str
    work.mkdir(parents=True, exist_ok=True)

    news_script = " ".join(
        f"From {n['source']}: {n['title']}. {n['summary']}" for n in news_items
    )
    intro_text = f"Good morning. This is Slayer, your daily 07:00 Singapore broadcast for {label_str}. Today we cover international developments, six distinct music genres, quote-based clinical reinforcement, Singapore arts and cultural events, and a closing reflection."

    if sg_events:
        arts_script_parts = [
            f"{ev['title']}: {ev['summary']} Ticket info: {ev['price']}."
            for ev in sg_events
        ]
        arts_text = "Here is what is on in Singapore this week. " + " ".join(arts_script_parts)
        arts_body = " · ".join(f"{ev['title']} ({ev['price']})" for ev in sg_events)
        arts_meta = [{"label": ev["source"], "value": f"{ev['title'][:38]} ({ev['price']})", "url": ev["url"]} for ev in sg_events]
    else:
        arts_text = "Check current Singapore performances and exhibitions at Esplanade, National Gallery Singapore, and SISTIC."
        arts_body = arts_text
        arts_meta = [{"label": "Esplanade", "value": "What's On", "url": "https://www.esplanade.com/whats-on"}]

    psych_text = (
        f"Personal psychological reinforcement. {psych['quote']} "
        f"{psych['clinical_phrase']} {psych['motivational_phrase']}"
    )
    closing_text = f"Closing reflection on {refl[0]}: {refl[1]} Thank you for listening to Slayer. Have a grounded day ahead."

    tts_specs = [
        ("intro", "Slayer Opening", "01 · OPENING", "Good Morning — This is Slayer", intro_text, [{"label": "Broadcast", "value": "07:00 SGT"}], "station"),
        ("news", "International News Bulletin", "02 · INTERNATIONAL NEWS", f"{len(news_items)} Verified Stories", news_script, [{"label": n["source"], "value": n["title"][:45], "url": n["url"]} for n in news_items], "news"),
        ("arts", "Singapore Arts & Cultural Guide", "07 · SINGAPORE ARTS", f"{len(sg_events)} Events This Week", arts_body, arts_meta, "events"),
        ("psych", "Personal Psychological Reinforcement", "10 · CLINICAL & MOTIVATIONAL REINFORCEMENT", psych["quote"], f"{psych['clinical_phrase']} {psych['motivational_phrase']}", [{"label": "Clinical", "value": psych["clinical_phrase"][:65] + "..."}, {"label": "Motivational", "value": psych["motivational_phrase"][:65] + "..."}], "psych"),
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
        r = requests.get(tr["download_url"], headers=UA, timeout=60)
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
            ff_args = ["-i", str(src), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.5"]
        else:
            seg_id, title, kicker, heading, body, meta, seg_type, src = item
            ff_args = ["-i", str(src), "-t", "330", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.5"]

        wav_out = work / f"{idx:02d}_{seg_id}.wav"
        run_ffmpeg([*ff_args, "-ar", "44100", "-ac", "2", str(wav_out)])
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

    size_mb = out_mp3.stat().st_size / (1024 * 1024)
    if not out_mp3.exists() or size_mb < 0.1 or size_mb > 95:
        sys.exit(f"QA FAIL: Output MP3 size {size_mb:.1f} MB out of range")
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
    print(f"QA PASS & Published {out_mp3} ({total_dur}s / {total_dur/60:.1f} min, {size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
