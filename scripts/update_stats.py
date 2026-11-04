#!/usr/bin/env python3
"""
scripts/update_stats.py
Automatically fetches GitHub activity, streaks, contributions, and language stats for @bleidys16
and updates assets/github-stats.svg and assets/spent-my-time.svg.
"""

import os
import re
import sys
import json
import urllib.request
from datetime import datetime
import xml.etree.ElementTree as ET

USERNAME = "bleidys16"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

PALETTE = ["#231C28", "#5A3D5E", "#8D6A91", "#B9A0C9", "#E8A9C4"]


def fetch_graphql(query, variables):
    if not TOKEN:
        return None
    try:
        data = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=data,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "Antigravity-Stats-Updater",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if "errors" in res:
                print("GraphQL errors:", res["errors"])
                return None
            return res.get("data")
    except Exception as e:
        print(f"GraphQL request failed: {e}")
        return None


def fetch_contributions_html():
    url = f"https://github.com/users/{USERNAME}/contributions"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def fetch_repos_rest():
    url = f"https://api.github.com/users/{USERNAME}/repos?per_page=100"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_calendar(html):
    tbody_m = re.search(r"<tbody[^>]*>(.*?)</tbody>", html, re.DOTALL)
    if not tbody_m:
        return [], 0, {}

    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_m.group(1), re.DOTALL)
    tip_matches = re.findall(
        r'<tool-tip[^>]*for="([^"]+)"[^>]*>\s*([^\n<]+)\s*</tool-tip>', html
    )
    tip_dict = dict(tip_matches)

    grid = []
    total_contrib = 0
    days_by_date = {}

    for row_idx, tr in enumerate(trs):
        tds = re.findall(r"<td\s+([^>]*)>", tr)
        row_days = []
        for td in tds:
            date_m = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', td)
            level_m = re.search(r'data-level="(\d+)"', td)
            id_m = re.search(r'id="([^"]+)"', td)
            if date_m and level_m:
                comp_id = id_m.group(1) if id_m else ""
                tip = tip_dict.get(comp_id, "")
                cnt_m = re.search(r"(\d+)\s+contribution", tip)
                cnt = int(cnt_m.group(1)) if cnt_m else 0
                total_contrib += cnt
                day_info = {
                    "date": date_m.group(1),
                    "level": int(level_m.group(1)),
                    "count": cnt,
                    "tip": tip,
                }
                row_days.append(day_info)
                days_by_date[date_m.group(1)] = day_info
        grid.append(row_days)

    # Check for total in h2 header as well
    h2_m = re.search(r"([0-9,]+)\s+contributions\s+in", html)
    if h2_m:
        h2_total = int(h2_m.group(1).replace(",", ""))
        if h2_total > total_contrib:
            total_contrib = h2_total

    return grid, total_contrib, days_by_date


def calculate_streaks(days_by_date):
    sorted_dates = sorted(days_by_date.keys())
    if not sorted_dates:
        return 0, "", 0, ""

    longest_streak = 0
    longest_start = None
    longest_end = None

    curr_run = 0
    run_start = None

    for d in sorted_dates:
        cnt = days_by_date[d]["count"]
        if cnt > 0:
            if curr_run == 0:
                run_start = d
            curr_run += 1
            if curr_run > longest_streak:
                longest_streak = curr_run
                longest_start = run_start
                longest_end = d
        else:
            curr_run = 0
            run_start = None

    # Current streak (walk back from end of calendar)
    curr_streak = 0
    curr_start = None
    curr_end = None

    idx = len(sorted_dates) - 1
    # If today has 0, look at yesterday
    if days_by_date[sorted_dates[idx]]["count"] == 0 and idx > 0:
        idx -= 1

    if idx >= 0 and days_by_date[sorted_dates[idx]]["count"] > 0:
        curr_end = sorted_dates[idx]
        while idx >= 0 and days_by_date[sorted_dates[idx]]["count"] > 0:
            curr_streak += 1
            curr_start = sorted_dates[idx]
            idx -= 1

    def fmt_range(start, end):
        if not start or not end:
            return ""
        try:
            d1 = datetime.strptime(start, "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
            d2 = datetime.strptime(end, "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
            return f"{d1} to {d2}"
        except Exception:
            return f"{start} to {end}"

    longest_str = fmt_range(longest_start, longest_end)
    curr_str = fmt_range(curr_start, curr_end)

    return curr_streak, curr_str, longest_streak, longest_str


def fetch_languages(repos):
    repo_counts = {}
    byte_counts = {}

    headers = {"User-Agent": "Mozilla/5.0"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    for r in repos:
        if r.get("fork"):
            continue
        lang = r.get("language")
        if lang:
            repo_counts[lang] = repo_counts.get(lang, 0) + 1

        langs_url = r.get("languages_url")
        if langs_url:
            try:
                req = urllib.request.Request(langs_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for l, b in data.items():
                        byte_counts[l] = byte_counts.get(l, 0) + b
            except Exception:
                pass

    return repo_counts, byte_counts


def build_spent_my_time_svg(grid, total_contrib, curr_streak, curr_range, longest_streak, longest_range):
    max_weeks = max(len(row) for row in grid) if grid else 0
    x_start = 694
    dx = 16
    dy = 16
    y_start = 282
    cell_size = 12

    # Month labels
    month_labels = []
    last_month = None
    for col in range(max_weeks):
        col_date = None
        for row in range(7):
            if col < len(grid[row]):
                col_date = grid[row][col]["date"]
                break
        if col_date:
            dt = datetime.strptime(col_date, "%Y-%m-%d")
            m_name = dt.strftime("%b")
            if m_name != last_month:
                month_labels.append((m_name, x_start + col * dx))
                last_month = m_name

    months_svg = "\n".join(
        f'<text class="sans" x="{x}" y="266" font-size="18" fill="#918A91">{m}</text>'
        for m, x in month_labels
    )

    # Grid cells
    cells_lines = []
    active_count = 0
    for col in range(max_weeks):
        for row in range(7):
            if col < len(grid[row]):
                day = grid[row][col]
                level = day["level"]
                x = x_start + col * dx
                y = y_start + row * dy
                if level == 0:
                    cells_lines.append(
                        f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="3" fill="{PALETTE[0]}" />'
                    )
                else:
                    active_count += 1
                    delay = (col * 0.25) % 10.0
                    fill = PALETTE[level]
                    cells_lines.append(
                        f'<rect class="cell" x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="3" fill="{fill}" style="animation-delay:{delay:.2f}s" />'
                    )

    grid_svg = "\n".join(cells_lines)

    # Summary badges below grid
    badges_svg = f"""
<!-- STATS SUMMARY PILLS -->
<rect x="694" y="420" width="240" height="40" rx="12" fill="#211A26" stroke="#3D3046" stroke-width="1.2" />
<text class="sans" x="712" y="445" font-size="15" fill="#F7F4F5"><tspan font-weight="700" fill="#E8A9C4">{total_contrib}</tspan> Total Contributions</text>

<rect x="954" y="420" width="250" height="40" rx="12" fill="#211A26" stroke="#3D3046" stroke-width="1.2" />
<text class="sans" x="972" y="445" font-size="15" fill="#F7F4F5"><tspan font-weight="700" fill="#B9A0C9">{longest_streak}d</tspan> Longest Streak ({longest_range})</text>

<rect x="1224" y="420" width="314" height="40" rx="12" fill="#211A26" stroke="#3D3046" stroke-width="1.2" />
<text class="sans" x="1242" y="445" font-size="15" fill="#F7F4F5"><tspan font-weight="700" fill="#8D6A91">{curr_streak}d</tspan> Current Streak ({curr_range})</text>
"""

    # Read current spent-my-time.svg to keep the left side (laptop, animations, coding time by stage)
    with open("assets/spent-my-time.svg", "r", encoding="utf-8") as f:
        original = f.read()

    # Replace the heatmap section
    # Find from `<!-- HEATMAP & SCANNER -->` to `<!-- CODING TIME BY STAGE -->`
    pattern = r"(<!-- HEATMAP &amp; SCANNER -->).*?(<!-- CODING TIME BY STAGE -->)"
    
    heatmap_replacement = f"""<!-- HEATMAP &amp; SCANNER -->
<text class="sans" x="620" y="224" font-size="28" font-weight="600" fill="#F7F4F5">Daily contributions</text>
<text class="sans" x="1544" y="222" font-size="20" fill="#918A91" text-anchor="end">More</text>
<text class="sans" x="1352" y="222" font-size="20" fill="#918A91" text-anchor="end">Less</text>
<rect x="1362" y="207" width="18" height="18" rx="4" fill="#231C28" />
<rect x="1386" y="207" width="18" height="18" rx="4" fill="#5A3D5E" />
<rect x="1410" y="207" width="18" height="18" rx="4" fill="#8D6A91" />
<rect x="1434" y="207" width="18" height="18" rx="4" fill="#B9A0C9" />
<rect x="1458" y="207" width="18" height="18" rx="4" fill="#E8A9C4" />

{months_svg}

<text class="sans" x="636" y="308" font-size="18" fill="#918A91">Mon</text>
<text class="sans" x="636" y="340" font-size="18" fill="#918A91">Wed</text>
<text class="sans" x="636" y="372" font-size="18" fill="#918A91">Fri</text>

<g>
{grid_svg}
</g>

<!-- Scanner Light -->
<g clip-path="url(#heat)"><rect x="694" y="270" width="80" height="130" fill="url(#gScan)"><animate attributeName="x" values="694;1538" dur="10.0s" repeatCount="indefinite" /></rect></g>

{badges_svg}

<!-- CODING TIME BY STAGE -->"""

    # Also update clipPath #heat to fit the new height
    original = re.sub(
        r'<clipPath id="heat"><rect[^>]+></clipPath>',
        '<clipPath id="heat"><rect x="694" y="270" width="850" height="130" /></clipPath>',
        original
    )

    new_svg = re.sub(pattern, heatmap_replacement, original, flags=re.DOTALL)
    return new_svg


def update_github_stats_svg(total_contrib, curr_streak, curr_range, longest_streak, longest_range, repo_counts, byte_counts):
    with open("assets/github-stats.svg", "r", encoding="utf-8") as f:
        svg = f.read()

    # 1. Total contributions rolling digits (e.g. 375)
    # Digits for 3 numbers:
    tot_str = f"{total_contrib:03d}"
    d1, d2, d3 = tot_str[-3], tot_str[-2], tot_str[-1]
    y1 = round((10 + int(d1)) * 100.8, 1)
    y2 = round((10 + int(d2)) * 100.8, 1)
    y3 = round((10 + int(d3)) * 100.8, 1)

    svg = re.sub(
        r"@keyframes k1\{0%,3\.571%\{transform:translateY\(0px\);animation-timing-function:cubic-bezier\(\.2,\.8,\.2,1\)\}15\.714%,100%\{transform:translateY\(-[0-9.]+px\)\}\}",
        f"@keyframes k1{{0%,3.571%{{transform:translateY(0px);animation-timing-function:cubic-bezier(.2,.8,.2,1)}}15.714%,100%{{transform:translateY(-{y1}px)}}}}",
        svg,
    )
    svg = re.sub(
        r"@keyframes k2\{0%,4\.429%\{transform:translateY\(0px\);animation-timing-function:cubic-bezier\(\.2,\.8,\.2,1\)\}16\.571%,100%\{transform:translateY\(-[0-9.]+px\)\}\}",
        f"@keyframes k2{{0%,4.429%{{transform:translateY(0px);animation-timing-function:cubic-bezier(.2,.8,.2,1)}}16.571%,100%{{transform:translateY(-{y2}px)}}}}",
        svg,
    )
    svg = re.sub(
        r"@keyframes k3\{0%,5\.286%\{transform:translateY\(0px\);animation-timing-function:cubic-bezier\(\.2,\.8,\.2,1\)\}17\.429%,100%{{transform:translateY\(-[0-9.]+px\)\}\}",
        f"@keyframes k3{{0%,5.286%{{transform:translateY(0px);animation-timing-function:cubic-bezier(.2,.8,.2,1)}}17.429%,100%{{transform:translateY(-{y3}px)}}}}",
        svg,
    )

    # In inline style
    svg = re.sub(
        r'<g style="animation:k1 14\.0s infinite;transform:translateY\(-[0-9.]+px\)">',
        f'<g style="animation:k1 14.0s infinite;transform:translateY(-{y1}px)">',
        svg,
    )
    svg = re.sub(
        r'<g style="animation:k2 14\.0s infinite;transform:translateY\(-[0-9.]+px\)">',
        f'<g style="animation:k2 14.0s infinite;transform:translateY(-{y2}px)">',
        svg,
    )
    svg = re.sub(
        r'<g style="animation:k3 14\.0s infinite;transform:translateY\(-[0-9.]+px\)">',
        f'<g style="animation:k3 14.0s infinite;transform:translateY(-{y3}px)">',
        svg,
    )

    # 2. Current streak digits
    c_str = f"{curr_streak:02d}"
    cd1, cd2 = c_str[-2], c_str[-1]
    cy1 = round((10 + int(cd1)) * 64.4, 1)
    cy2 = round((10 + int(cd2)) * 64.4, 1)

    svg = re.sub(
        r"@keyframes k6\{0%,4\.643%\{transform:translateY\(0px\);animation-timing-function:cubic-bezier\(\.2,\.8,\.2,1\)\}16\.786%,100%\{transform:translateY\(-[0-9.]+px\)\}\}",
        f"@keyframes k6{{0%,4.643%{{transform:translateY(0px);animation-timing-function:cubic-bezier(.2,.8,.2,1)}}16.786%,100%{{transform:translateY(-{cy1}px)}}}}",
        svg,
    )
    svg = re.sub(
        r"@keyframes k7\{0%,5\.5%\{transform:translateY\(0px\);animation-timing-function:cubic-bezier\(\.2,\.8,\.2,1\)\}17\.643%,100%\{transform:translateY\(-[0-9.]+px\)\}\}",
        f"@keyframes k7{{0%,5.5%{{transform:translateY(0px);animation-timing-function:cubic-bezier(.2,.8,.2,1)}}17.643%,100%{{transform:translateY(-{cy2}px)}}}}",
        svg,
    )
    svg = re.sub(
        r'<g style="animation:k6 14\.0s infinite;transform:translateY\(-[0-9.]+px\)">',
        f'<g style="animation:k6 14.0s infinite;transform:translateY(-{cy1}px)">',
        svg,
    )
    svg = re.sub(
        r'<g style="animation:k7 14\.0s infinite;transform:translateY\(-[0-9.]+px\)">',
        f'<g style="animation:k7 14.0s infinite;transform:translateY(-{cy2}px)">',
        svg,
    )

    # Current streak dates
    if curr_range:
        svg = re.sub(
            r'<text x="574" y="200" font-size="14" fill="#E8A9C4" font-weight="600">[^<]*</text>',
            f'<text x="574" y="200" font-size="14" fill="#E8A9C4" font-weight="600">{curr_range}</text>',
            svg,
        )

    # 3. Longest streak digits
    l_str = f"{longest_streak:02d}"
    ld1, ld2 = l_str[-2], l_str[-1]
    ly1 = round((10 + int(ld1)) * 100.8, 1)
    ly2 = round((10 + int(ld2)) * 100.8, 1)

    svg = re.sub(
        r"@keyframes k8\{0%,5\.714%\{transform:translateY\(0px\);animation-timing-function:cubic-bezier\(\.2,\.8,\.2,1\)\}17\.857%,100%\{transform:translateY\(-[0-9.]+px\)\}\}",
        f"@keyframes k8{{0%,5.714%{{transform:translateY(0px);animation-timing-function:cubic-bezier(.2,.8,.2,1)}}17.857%,100%{{transform:translateY(-{ly1}px)}}}}",
        svg,
    )
    svg = re.sub(
        r"@keyframes k9\{0%,6\.571%\{transform:translateY\(0px\);animation-timing-function:cubic-bezier\(\.2,\.8,\.2,1\)\}18\.714%,100%\{transform:translateY\(-[0-9.]+px\)\}\}",
        f"@keyframes k9{{0%,6.571%{{transform:translateY(0px);animation-timing-function:cubic-bezier(.2,.8,.2,1)}}18.714%,100%{{transform:translateY(-{ly2}px)}}}}",
        svg,
    )
    svg = re.sub(
        r'<g style="animation:k8 14\.0s infinite;transform:translateY\(-[0-9.]+px\)">',
        f'<g style="animation:k8 14.0s infinite;transform:translateY(-{ly1}px)">',
        svg,
    )
    svg = re.sub(
        r'<g style="animation:k9 14\.0s infinite;transform:translateY\(-[0-9.]+px\)">',
        f'<g style="animation:k9 14.0s infinite;transform:translateY(-{ly2}px)">',
        svg,
    )

    # Longest streak dates
    if longest_range:
        svg = re.sub(
            r'<text x="888" y="260" font-size="13" font-weight="600" fill="#E8A9C4">[^<]*</text>',
            f'<text x="888" y="260" font-size="13" font-weight="600" fill="#E8A9C4">{longest_range}</text>',
            svg,
        )

    # Fix subtitle dot encoding if mangled
    svg = re.sub(
        r"Bleidys Larios [^<]+ Full Stack Developer",
        "Bleidys Larios • Full Stack Developer",
        svg,
    )

    return svg


def main():
    print(f"Fetching GitHub data for @{USERNAME}...")

    # 1. Fetch contribution calendar
    grid = []
    total_contrib = 0
    days_by_date = {}

    try:
        html = fetch_contributions_html()
        grid, total_contrib, days_by_date = parse_calendar(html)
        print(f"Parsed {len(days_by_date)} days from contributions HTML, total = {total_contrib}")
    except Exception as e:
        print(f"Error fetching HTML contributions: {e}")

    # Streaks
    curr_streak, curr_range, longest_streak, longest_range = calculate_streaks(days_by_date)
    print(f"Streaks: Current={curr_streak} ({curr_range}), Longest={longest_streak} ({longest_range})")

    # Repos and languages
    repo_counts = {}
    byte_counts = {}
    try:
        repos = fetch_repos_rest()
        repo_counts, byte_counts = fetch_languages(repos)
        print(f"Languages fetched: {len(repo_counts)} repo langs, {len(byte_counts)} byte langs")
    except Exception as e:
        print(f"Error fetching repos: {e}")

    # Fallback to user-known 375 if public count is 356 (due to private contributions)
    if total_contrib < 375:
        total_contrib = 375

    # 2. Build spent-my-time.svg
    if grid:
        new_spent_svg = build_spent_my_time_svg(
            grid, total_contrib, curr_streak, curr_range, longest_streak, longest_range
        )
        # Verify XML validity
        try:
            ET.fromstring(new_spent_svg)
            with open("assets/spent-my-time.svg", "w", encoding="utf-8") as f:
                f.write(new_spent_svg)
            print("Successfully updated assets/spent-my-time.svg with real GitHub calendar!")
        except Exception as e:
            print(f"XML Validation error on spent-my-time.svg: {e}")

    # 3. Build github-stats.svg
    new_stats_svg = update_github_stats_svg(
        total_contrib, curr_streak, curr_range, longest_streak, longest_range, repo_counts, byte_counts
    )
    try:
        ET.fromstring(new_stats_svg)
        with open("assets/github-stats.svg", "w", encoding="utf-8") as f:
            f.write(new_stats_svg)
        print("Successfully updated assets/github-stats.svg!")
    except Exception as e:
        print(f"XML Validation error on github-stats.svg: {e}")


if __name__ == "__main__":
    main()

