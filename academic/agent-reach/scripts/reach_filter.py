#!/usr/bin/env python3
"""
reach_filter.py - Universal token shield and table projector for Agent Reach platform feeds.

Reduces 20KB-50KB JSON/YAML platform payloads (V2EX, Twitter, Reddit, Bilibili,
Xiaohongshu, GitHub) down to ~150-250 token high-density Markdown pipe tables
with deterministic field projection and disk buffering.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from typing import List, Dict, Any, Optional, Tuple


def render_table(rows: List[Dict[str, Any]], columns: Optional[List[str]] = None, headers: Optional[List[str]] = None) -> str:
    """Render a list of dictionaries as a Markdown pipe table."""
    if not rows:
        return "*(no records)*\n"
    if columns is None:
        columns = list(rows[0].keys())
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]

    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ").strip()
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").strip().ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"


def _clean_str(val: Any, max_len: int = 70) -> str:
    s = str(val or "").strip().replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


def filter_v2ex(data: Any) -> List[Dict[str, Any]]:
    """Parse V2EX topics JSON into high-density rows."""
    items = data if isinstance(data, list) else data.get("topics", data.get("data", []))
    rows = []
    for t in items:
        if not isinstance(t, dict):
            continue
        tid = t.get("id", "")
        node = t.get("node", {}).get("title") or t.get("node", {}).get("name") or ""
        member = t.get("member", {}).get("username") or ""
        rows.append({
            "id": str(tid),
            "node": node,
            "title": _clean_str(t.get("title", "")),
            "replies": t.get("replies", 0),
            "author": member,
            "url": f"https://www.v2ex.com/t/{tid}" if tid else ""
        })
    return rows


def filter_twitter(data: Any) -> List[Dict[str, Any]]:
    """Parse Twitter tweets / timeline JSON."""
    items = data if isinstance(data, list) else data.get("tweets", data.get("data", data.get("entries", [])))
    rows = []
    for t in items:
        if not isinstance(t, dict):
            continue
        author = t.get("author", {}).get("username") or t.get("username") or t.get("user", {}).get("screen_name") or ""
        text = _clean_str(t.get("text") or t.get("full_text") or t.get("content", ""))
        tid = str(t.get("id") or t.get("id_str") or "")
        url = t.get("url") or (f"https://x.com/{author}/status/{tid}" if author and tid else "")
        rows.append({
            "id": tid,
            "author": f"@{author}" if author and not author.startswith("@") else author,
            "text": text,
            "likes": t.get("likes") or t.get("favorite_count") or 0,
            "retweets": t.get("retweets") or t.get("retweet_count") or 0,
            "url": url
        })
    return rows


def filter_reddit(data: Any) -> List[Dict[str, Any]]:
    """Parse Reddit post listings."""
    raw_children = []
    if isinstance(data, dict):
        if "data" in data and "children" in data["data"]:
            raw_children = [c.get("data", {}) for c in data["data"]["children"]]
        elif "posts" in data:
            raw_children = data["posts"]
    elif isinstance(data, list):
        raw_children = data

    rows = []
    for p in raw_children:
        if not isinstance(p, dict):
            continue
        sub = p.get("subreddit_name_prefixed") or p.get("subreddit") or ""
        url = p.get("permalink") or p.get("url") or ""
        if url.startswith("/"):
            url = f"https://reddit.com{url}"
        rows.append({
            "sub": sub,
            "title": _clean_str(p.get("title", "")),
            "score": p.get("score") or p.get("ups") or 0,
            "comments": p.get("num_comments", 0),
            "author": p.get("author", ""),
            "url": url
        })
    return rows


def filter_bilibili(data: Any) -> List[Dict[str, Any]]:
    """Parse Bilibili search / video JSON."""
    items = []
    if isinstance(data, dict):
        res = data.get("data", {}).get("result", [])
        if isinstance(res, list):
            items = res
        elif isinstance(res, dict):
            items = res.get("video", [])
        else:
            items = data.get("videos", data.get("items", []))
    elif isinstance(data, list):
        items = data

    rows = []
    for v in items:
        if not isinstance(v, dict):
            continue
        bvid = v.get("bvid") or v.get("id") or ""
        raw_title = re.sub(r"<[^>]+>", "", v.get("title", ""))
        play = v.get("play") or v.get("view") or 0
        author = v.get("author") or v.get("owner", {}).get("name") or ""
        rows.append({
            "bvid": str(bvid),
            "title": _clean_str(raw_title),
            "author": author,
            "play": play,
            "danmaku": v.get("video_review") or v.get("danmaku") or 0,
            "url": f"https://www.bilibili.com/video/{bvid}" if bvid else ""
        })
    return rows


def filter_xhs(data: Any) -> List[Dict[str, Any]]:
    """Parse Xiaohongshu notes JSON/YAML."""
    items = []
    if isinstance(data, dict):
        items = data.get("notes") or data.get("feeds") or data.get("data", {}).get("items", [])
    elif isinstance(data, list):
        items = data

    rows = []
    for n in items:
        if not isinstance(n, dict):
            continue
        nid = n.get("note_id") or n.get("id") or n.get("feed_id") or ""
        title = n.get("title") or n.get("display_title") or n.get("desc") or ""
        user = n.get("user", {}).get("nickname") or n.get("author") or ""
        likes = n.get("interact_info", {}).get("liked_count") or n.get("likes") or 0
        xsec = n.get("xsec_token") or ""
        url = f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={xsec}" if nid and xsec else f"https://www.xiaohongshu.com/explore/{nid}" if nid else ""
        rows.append({
            "id": str(nid),
            "title": _clean_str(title),
            "author": user,
            "likes": likes,
            "url": url
        })
    return rows


def filter_github(data: Any) -> List[Dict[str, Any]]:
    """Parse GitHub gh search repos/issues JSON."""
    items = data if isinstance(data, list) else data.get("items", [])
    rows = []
    for g in items:
        if not isinstance(g, dict):
            continue
        name = g.get("name") or g.get("full_name") or g.get("title") or ""
        stars = g.get("stargazersCount") or g.get("stargazers_count") or g.get("stars") or g.get("state") or 0
        desc = _clean_str(g.get("description") or g.get("body") or "")
        url = g.get("url") or g.get("html_url") or ""
        rows.append({
            "name": name,
            "metric": stars,
            "desc": desc,
            "url": url
        })
    return rows


def filter_generic(data: Any) -> List[Dict[str, Any]]:
    """Auto-detect and extract tabular fields from arbitrary JSON collections."""
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for val in data.values():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                items = val
                break
        if not items:
            items = [data]

    rows = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        row = {}
        for k, v in entry.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                row[k] = _clean_str(v, max_len=60)
            elif isinstance(v, dict):
                # Flatten one level if simple
                for sub_k, sub_v in v.items():
                    if isinstance(sub_v, (str, int, float, bool)):
                        row[f"{k}_{sub_k}"] = _clean_str(sub_v, max_len=40)
        rows.append(row)
    return rows


PLATFORM_MAP = {
    "v2ex": filter_v2ex,
    "twitter": filter_twitter,
    "reddit": filter_reddit,
    "bilibili": filter_bilibili,
    "xhs": filter_xhs,
    "xiaohongshu": filter_xhs,
    "github": filter_github,
    "generic": filter_generic,
}


def auto_detect_platform(data: Any) -> str:
    """Detect platform from payload structure."""
    if isinstance(data, list) and data:
        sample = data[0]
        if isinstance(sample, dict):
            if "node" in sample and "replies" in sample:
                return "v2ex"
            if "bvid" in sample or "video_review" in sample:
                return "bilibili"
            if "stargazersCount" in sample or "html_url" in sample:
                return "github"
    elif isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict) and "children" in data["data"]:
            return "reddit"
        if "data" in data and isinstance(data["data"], dict) and "result" in data["data"]:
            return "bilibili"
    return "generic"


def fetch_v2ex(endpoint: str = "hot") -> Any:
    """Directly fetch public V2EX topics without requiring curl."""
    url = "https://www.v2ex.com/api/topics/hot.json" if endpoint == "hot" else f"https://www.v2ex.com/api/topics/show.json?node_name={endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "agent-reach/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Filter and format Agent Reach platform payloads into high-density Markdown tables.")
    parser.add_argument("platform", nargs="?", default="auto", choices=["auto", "v2ex", "twitter", "reddit", "bilibili", "xhs", "xiaohongshu", "github", "generic"], help="Target platform adapter (default: auto)")
    parser.add_argument("-i", "--input", default="-", help="Input JSON file or '-' for stdin")
    parser.add_argument("-o", "--out", help="Buffer full output to file and emit 1-line receipt")
    parser.add_argument("-t", "--table", action="store_true", default=True, help="Render as Markdown table (default: True)")
    parser.add_argument("-p", "--project", help="Comma-separated keys to project in table")
    parser.add_argument("-n", "--limit", type=int, default=0, help="Cap number of rows")
    parser.add_argument("--json", action="store_true", help="Output filtered data as JSON instead of table")
    parser.add_argument("--fetch", choices=["v2ex-hot", "v2ex-node"], help="Directly fetch public endpoint without stdin")
    parser.add_argument("--node", default="tech", help="Node name for --fetch v2ex-node")

    args = parser.parse_args()

    # Direct fetch mode
    if args.fetch:
        if args.fetch == "v2ex-hot":
            data = fetch_v2ex("hot")
            platform = "v2ex"
        else:
            data = fetch_v2ex(args.node)
            platform = "v2ex"
    else:
        # Read from input
        if args.input == "-":
            raw = sys.stdin.read().strip()
        else:
            with open(args.input, "r", encoding="utf-8") as f:
                raw = f.read().strip()

        if not raw:
            print("Error: empty input received.", file=sys.stderr)
            sys.exit(1)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON input: {e}", file=sys.stderr)
            sys.exit(1)

        platform = args.platform if args.platform != "auto" else auto_detect_platform(data)

    handler = PLATFORM_MAP.get(platform, filter_generic)
    rows = handler(data)

    if args.limit and args.limit > 0:
        rows = rows[:args.limit]

    # Optional disk buffering
    if args.out:
        out_path = os.path.expanduser(args.out)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)

    project_cols = [k.strip().lower() for k in args.project.split(",") if k.strip()] if args.project else None
    if project_cols and rows:
        available_cols = list(rows[0].keys())
        active_cols = [c for c in available_cols if c.lower() in project_cols] or available_cols
        rows = [{k: r[k] for k in active_cols if k in r} for r in rows]
    else:
        active_cols = list(rows[0].keys()) if rows else []

    if args.out:
        print(f"### Buffered {len(rows)} {platform} records to `{args.out}`\n")

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(render_table(rows, active_cols))


if __name__ == "__main__":
    main()
