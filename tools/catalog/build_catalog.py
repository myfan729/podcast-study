"""probe_catalog.json + curated metadata → catalog.json (the verified list seeded into the app)."""
import json
from pathlib import Path

HERE = Path(__file__).parent
probe = json.loads((HERE / "probe_catalog.json").read_text())
EXCLUDE_QUERIES = {"Body Electric NPR", "How To Do Everything", "Rough Translation NPR", "Bloomberg Deals", "Food 360 with Marc Murphy",
                   "Foundering Bloomberg", "Movie Crush", "Risky Business Maria Konnikova", "Solvable Pushkin", "Motley Fool Money",
                   "Invest Like the Best", "Making Sense of Cents", "Sport and Society", "Trump's Terms NPR"}
# category (Korean), level, extra settings by show title
META = {
    "Big Take": ("경제·시사", "중상"), "Big Take Asia": ("경제·시사", "중상"), "Bloomberg Daybreak: US Edition": ("뉴스", "상"),
    "Bloomberg Daybreak: Asia Edition": ("뉴스", "상"), "Bloomberg Surveillance": ("경제·시사", "상"), "Bloomberg Talks": ("경제·시사", "상"),
    "Bloomberg Businessweek": ("경제·시사", "상"), "Bloomberg Intelligence": ("경제·시사", "상"), "Bloomberg Tech": ("테크", "상"),
    "Everybody's Business": ("경제·시사", "중상"), "Leaders with Francine Lacqua": ("인터뷰", "상"), "Masters in Business": ("경제·시사", "상"),
    "Merryn Talks Money": ("경제·시사", "중상"), "Money Stuff: The Podcast": ("경제·시사", "상"), "Odd Lots": ("경제·시사", "상"),
    "Trumponomics": ("경제·시사", "상"), "Zero: The Climate Race": ("과학·환경", "중상"), "The Mishal Husain Show": ("인터뷰", "중상"),
    "Up First from NPR": ("뉴스", "중상"), "Consider This from NPR": ("뉴스", "중상"), "The NPR Politics Podcast": ("뉴스", "중상"),
    "The Indicator from Planet Money": ("경제·시사", "중"), "Planet Money": ("경제·시사", "중"), "Short Wave": ("과학·환경", "중"),
    "Life Kit": ("생활·자기계발", "중"), "Code Switch": ("문화·사회", "중상"), "It's Been a Minute": ("문화·사회", "중상"),
    "Pop Culture Happy Hour": ("문화·사회", "중상"), "Throughline": ("역사", "중상"), "Embedded": ("문화·사회", "중상"),
    "Wild Card with Rachel Martin": ("인터뷰", "중"),
    "Think Fast Talk Smart: Communication Techniques": ("말하기·커리어", "중"), "Stuff You Should Know": ("잡학·교양", "중"),
    "Stuff You Missed in History Class": ("역사", "중"), "Stuff Mom Never Told You": ("문화·사회", "중"), "BrainStuff": ("잡학·교양", "중"),
    "TechStuff": ("테크", "중"), "Part-Time Genius": ("잡학·교양", "중"), "Ridiculous History": ("역사", "중"),
    "Stuff They Don't Want You To Know": ("잡학·교양", "중상"), "Behind the Bastards": ("역사", "상"), "The Daily Zeitgeist": ("문화·사회", "상"),
    "Unexplained": ("잡학·교양", "중상"), "Cautionary Tales with Tim Harford": ("이야기", "중"), "Revisionist History": ("이야기", "중상"),
    "The Happiness Lab with Dr. Laurie Santos": ("생활·자기계발", "중"), "What's Your Problem?": ("테크", "중상"),
    "Against the Rules with Michael Lewis": ("이야기", "중상"), "The Last Archive": ("역사", "중상"), "Lost Hills": ("이야기", "중상"),
    "Heavyweight": ("이야기", "중상"), "Shell Game": ("이야기", "중상"), "Here's The Thing with Alec Baldwin": ("인터뷰", "중상"),
    "The Diary Of A CEO with Steven Bartlett": ("말하기·커리어", "중"),
}
seen, shows = set(), []
for q, v in probe.items():
    if not v.get("path") or q in EXCLUDE_QUERIES or v["feed"] in seen:
        continue
    seen.add(v["feed"])
    cat, level = META.get(v["title"], ("기타", "중상"))
    row = {"feed_url": v["feed"], "title": v["title"], "author": v.get("artist"), "image_url": v.get("image"),
           "description": None, "language": "en", "path": v["path"], "parser": "npr" if v["path"] == "npr" else None,
           "speaker_labels": "named" if v["path"] == "npr" else "auto", "max_minutes": 120,
           "title_include": None, "title_exclude": None, "category": cat, "level": level,
           "probe": {k: v.get(k) for k in ("median_min", "per_week", "days_since")}}
    if v["title"].startswith("Bloomberg Daybreak"):
        row["title_exclude"] = "^bonus"
    shows.append(row)
shows.sort(key=lambda r: (r["category"], r["title"]))
(HERE / "catalog.json").write_text(json.dumps({"shows": shows}, ensure_ascii=False, indent=1))
print(len(shows), "shows")
from collections import Counter
print(Counter(r["category"] for r in shows))
