import re
import time
from datetime import datetime, timezone

import feedparser
import folium
import pandas as pd
from folium.plugins import HeatMap, MarkerCluster
from geopy.geocoders import Nominatim

RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/worldNews",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://www.theguardian.com/world/middleeast/rss",
    "https://www.bbc.com/news/world/middle_east/rss.xml",
]

MAP_CENTER = [26.0, 50.0]
MAP_ZOOM = 5
MAP_FILE = "conflict_map.html"
INDEX_FILE = "index.html"

PRIMARY_TERMS = [
    "iran","israel","gaza","lebanon","tehran","tel aviv","jerusalem",
    "saudi arabia","riyadh","uae","dubai","abu dhabi","qatar","doha",
    "kuwait","oman","hormuz","persian gulf","red sea","basra","beirut"
]

ACTION_TERMS = [
    "strike","missile","attack","drone","bomb","rocket","raid",
    "explosion","blast","refinery","pipeline","airport","port",
    "power plant","substation","military base","naval base","airspace",
    "terminal","grid","telecom tower","dam"
]

PLACE_HINTS = {
    "Tehran": "Tehran, Iran",
    "Tel Aviv": "Tel Aviv, Israel",
    "Jerusalem": "Jerusalem, Israel",
    "Dubai": "Dubai, United Arab Emirates",
    "Abu Dhabi": "Abu Dhabi, United Arab Emirates",
    "Riyadh": "Riyadh, Saudi Arabia",
    "Doha": "Doha, Qatar",
    "Basra": "Basra, Iraq",
    "Beirut": "Beirut, Lebanon",
    "Hormuz": "Strait of Hormuz",
    "Jeddah": "Jeddah, Saudi Arabia",
    "Dammam": "Dammam, Saudi Arabia",
    "Muscat": "Muscat, Oman",
    "Baghdad": "Baghdad, Iraq",
    "Damascus": "Damascus, Syria",
    "Gaza": "Gaza",
    "Fujairah": "Fujairah, United Arab Emirates",
    "Ras Tanura": "Ras Tanura, Saudi Arabia",
    "Abqaiq": "Abqaiq, Saudi Arabia",
}

HIGH_SEVERITY = ["missile","strike","attack","explosion","bomb","drone","rocket","blast"]
INFRA_TERMS = ["refinery","pipeline","airport","port","power plant","substation","military base","naval base","dam","telecom tower"]

geolocator = Nominatim(user_agent="entropymap_auto_update")
geo_cache = {}

def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()

def geocode_location(loc: str):
    if loc in geo_cache:
        return geo_cache[loc]
    try:
        point = geolocator.geocode(loc, timeout=10)
        if point:
            geo_cache[loc] = {"lat": point.latitude, "lon": point.longitude}
            return geo_cache[loc]
    except Exception:
        pass
    return None

def extract_location(text: str):
    t = text.lower()
    matches = []
    for hint, canon in PLACE_HINTS.items():
        if hint.lower() in t:
            matches.append((hint, canon))
    matches.sort(key=lambda x: len(x[0]), reverse=True)
    return matches[0][1] if matches else None

def severity_score(text: str) -> int:
    score = 3
    t = text.lower()
    for w in HIGH_SEVERITY:
        if w in t:
            score += 4
    for w in INFRA_TERMS:
        if w in t:
            score += 3
    score += min(len(t.split()) // 12, 3)
    return min(score, 15)

def alert_level(s: int) -> str:
    if s >= 13:
        return "Critical"
    if s >= 10:
        return "High"
    if s >= 6:
        return "Medium"
    return "Low"

def alert_fill_color(level: str) -> str:
    return {
        "Critical": "#8B0000",
        "High": "#FF4500",
        "Medium": "#FFD700",
        "Low": "#90EE90",
    }.get(level, "#D3D3D3")

def detect_side(text: str) -> str:
    t = text.lower()
    if "iran" in t and ("israel" in t or "u.s." in t or "us " in t or "american" in t):
        return "Mixed"
    if "iran" in t:
        return "Iran"
    if "israel" in t:
        return "Israel"
    if "u.s." in t or "us " in t or "american" in t or "pentagon" in t or "washington" in t:
        return "US"
    return "Other"

def border_color_for_side(side: str) -> str:
    return {
        "Iran": "red",
        "Israel": "blue",
        "US": "green",
        "Mixed": "purple",
        "Other": "gray"
    }.get(side, "gray")

def detect_infrastructure(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["refinery","pipeline","oil","gas","terminal","port"]):
        return "Energy / Maritime"
    if any(k in t for k in ["power plant","grid","substation","blackout"]):
        return "Electric Grid"
    if any(k in t for k in ["airport","airspace","runway","flight"]):
        return "Aviation"
    if any(k in t for k in ["telecom","tower","satellite","data center"]):
        return "Communication"
    if any(k in t for k in ["dam","reservoir","desalination","water"]):
        return "Water"
    if any(k in t for k in ["military base","naval base","bunker","missile base"]):
        return "Military"
    if any(k in t for k in ["government","ministry","embassy","parliament"]):
        return "Government"
    return "Other"

def is_relevant(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in PRIMARY_TERMS) or any(a in t for a in ACTION_TERMS)

def deduplicate_items(items):
    seen = set()
    out = []
    for item in items:
        key = (item["title"].strip().lower(), round(item["lat"], 2), round(item["lon"], 2))
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out

def parse_rss():
    incidents = []
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        source_title = clean_text(feed.get("feed", {}).get("title", url))
        entries = getattr(feed, "entries", [])[:20]
        for entry in entries:
            title = clean_text(getattr(entry, "title", ""))
            summary = clean_text(getattr(entry, "summary", ""))
            text = f"{title} {summary}"
            if not is_relevant(text):
                continue
            loc = extract_location(text)
            if not loc:
                continue
            geo = geocode_location(loc)
            time.sleep(1)
            if not geo:
                continue
            sev = severity_score(text)
            incidents.append({
                "published": now_utc,
                "title": title,
                "location": loc,
                "lat": geo["lat"],
                "lon": geo["lon"],
                "severity": sev,
                "alert_level": alert_level(sev),
                "side": detect_side(text),
                "infrastructure": detect_infrastructure(text),
                "source": source_title,
                "link": getattr(entry, "link", ""),
            })
    return deduplicate_items(incidents)

def build_map(incidents):
    m = folium.Map(location=MAP_CENTER, zoom_start=MAP_ZOOM, tiles="CartoDB positron")
    cluster = MarkerCluster().add_to(m)
    for i in incidents:
        folium.CircleMarker(
            location=[i["lat"], i["lon"]],
            radius=max(6, i["severity"]),
            color=border_color_for_side(i["side"]),
            weight=2,
            fill=True,
            fill_color=alert_fill_color(i["alert_level"]),
            fill_opacity=0.75,
            popup=(
                f"<b>{i['title']}</b><br>"
                f"<b>Location:</b> {i['location']}<br>"
                f"<b>Side:</b> {i['side']}<br>"
                f"<b>Infrastructure:</b> {i['infrastructure']}<br>"
                f"<b>Alert:</b> {i['alert_level']}<br>"
                f"<b>Severity:</b> {i['severity']}<br>"
                f"<b>Source:</b> {i['source']}<br>"
                f"<a href='{i['link']}' target='_blank'>Open article</a>"
            ),
            tooltip=f"{i['location']} | {i['alert_level']}"
        ).add_to(cluster)
    if incidents:
        HeatMap([[x["lat"], x["lon"], x["severity"]] for x in incidents], radius=35, blur=20).add_to(m)
    return m

def make_dashboard(df: pd.DataFrame):
    table_html = df.to_html(index=False, escape=False)
    html = f"""<html>
<head>
<meta charset="utf-8">
<title>EntropyMap Dashboard</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
h1 {{ margin-bottom: 8px; }}
.note {{ color: #555; margin-bottom: 18px; }}
iframe {{ width: 100%; height: 700px; border: 1px solid #ccc; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
th {{ background: #f2f2f2; }}
</style>
</head>
<body>
<h1>EntropyMap Dashboard</h1>
<div class="note">Border color = side. Fill color = alert level. Updated automatically by GitHub Actions.</div>
<iframe src="{MAP_FILE}"></iframe>
<h2>Detected incidents</h2>
{table_html}
</body>
</html>
"""
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(html)

def main():
    incidents = parse_rss()
    df = pd.DataFrame(incidents, columns=[
        "published","location","side","infrastructure","alert_level",
        "severity","source","title","link"
    ])
    build_map(incidents).save(MAP_FILE)
    make_dashboard(df)
    print(f"Incidents detected: {len(incidents)}")
    print(f"Wrote {MAP_FILE} and {INDEX_FILE}")

if __name__ == "__main__":
    main()
