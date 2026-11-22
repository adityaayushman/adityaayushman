"""Build assets/stats.svg: a self-contained GitHub dashboard card.

Reads live data from the GitHub API (no third-party stats service), so the
card cannot break when someone else's server is down. Run locally with the
GitHub CLI logged in, or in Actions with GITHUB_TOKEN set.
"""
import json
import os
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

USER = "adityaayushman"
LIVE_PRODUCTS = 6  # the six featured products in the README, each with a live demo
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "stats.svg")

LANG_COLORS = {
    "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "HTML": "#e34c26", "CSS": "#8957e5", "Java": "#b07219", "C++": "#f34b7d",
    "Dockerfile": "#384d54", "Jupyter Notebook": "#DA5B0B", "HCL": "#844FBA",
    "Solidity": "#AA6746", "Dart": "#00B4AB", "Shell": "#89e051",
}


def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


TOKEN = token()


def api(path):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def graphql(query):
    req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps({"query": query}).encode(),
                                 headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "profile-stats"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def main():
    repos, page = [], 1
    while True:
        chunk = api(f"/users/{USER}/repos?per_page=100&page={page}&type=owner")
        repos += chunk
        if len(chunk) < 100:
            break
        page += 1
    own = [r for r in repos if not r["fork"]]

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    active = sum(1 for r in own if not r["archived"]
                 and datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00")) >= cutoff)

    langs = defaultdict(int)
    for r in own:
        if r["archived"]:
            continue
        for k, v in api(f"/repos/{USER}/{r['name']}/languages").items():
            langs[k] += v
    for noise in ("Jupyter Notebook", "Dockerfile", "HCL"):
        langs.pop(noise, None)
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:5]

    cal = graphql('query{user(login:"%s"){contributionsCollection{contributionCalendar{totalContributions '
                  'weeks{contributionDays{date contributionCount}}}}}}' % USER)["data"]["user"][
        "contributionsCollection"]["contributionCalendar"]
    contrib_total = cal["totalContributions"]
    months = defaultdict(int)
    for w in cal["weeks"]:
        for d in w["contributionDays"]:
            months[d["date"][:7]] += d["contributionCount"]
    keys = sorted(months)[-12:]
    series = [(datetime.strptime(k, "%Y-%m").strftime("%b"), months[k]) for k in keys]
    while len(series) > 6 and series[0][1] == 0:  # start at the first active month (min 6 bars)
        series.pop(0)

    # ---- layout --------------------------------------------------------
    W, H = 860, 430
    F = "font-family=\"'Segoe UI',-apple-system,Helvetica,Arial,sans-serif\""
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="GitHub activity dashboard for {USER}">',
         '<defs>'
         '<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a371f7"/>'
         '<stop offset="1" stop-color="#388bfd"/></linearGradient>'
         '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0d1117"/>'
         '<stop offset="1" stop-color="#161b22"/></linearGradient></defs>',
         f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="16" fill="url(#bg)" stroke="#30363d"/>',
         f'<text x="32" y="46" {F} font-size="20" font-weight="700" fill="#f0f6fc">GitHub, at a glance</text>',
         f'<text x="{W-32}" y="46" {F} font-size="12" fill="#8b949e" text-anchor="end">'
         f'Live from the GitHub API · updated {datetime.now(timezone.utc):%d %b %Y}</text>']

    kpis = [(f"{contrib_total:,}", "contributions, last 12 months"), (str(active), "repos active in 90 days"),
            (str(LIVE_PRODUCTS), "live ML products"), (str(len(langs)), "languages shipped")]
    tw, gap = 188, 16
    for i, (val, label) in enumerate(kpis):
        x = 32 + i * (tw + gap)
        o.append(f'<rect x="{x}" y="70" width="{tw}" height="92" rx="12" fill="#0d1117" stroke="#30363d"/>')
        o.append(f'<rect x="{x}" y="70" width="4" height="92" rx="2" fill="url(#g)"/>')
        o.append(f'<text x="{x+22}" y="118" {F} font-size="36" font-weight="700" fill="#f0f6fc">{val}</text>')
        o.append(f'<text x="{x+22}" y="144" {F} font-size="12" fill="#8b949e">{label}</text>')

    # monthly bars
    cx, cy, cw, ch = 32, 196, 520, 200
    o.append(f'<text x="{cx}" y="{cy+16}" {F} font-size="14" font-weight="600" fill="#f0f6fc">Contributions by month</text>')
    mx = max(v for _, v in series) or 1
    n = len(series)
    bw = min(56, (cw - 10 * (n - 1)) / n)
    bg_ = (cw - n * bw) / max(1, n - 1)
    base = cy + ch - 24
    for i, (m, v) in enumerate(series):
        x = cx + i * (bw + bg_)
        h = max(3, (v / mx) * (ch - 80))
        o.append(f'<rect x="{x:.1f}" y="{base-h:.1f}" width="{bw}" height="{h:.1f}" rx="5" fill="url(#g)" opacity="0.92"/>')
        o.append(f'<text x="{x+bw/2:.1f}" y="{base-h-8:.1f}" {F} font-size="11" fill="#c9d1d9" text-anchor="middle">{v}</text>')
        o.append(f'<text x="{x+bw/2:.1f}" y="{base+16}" {F} font-size="11" fill="#8b949e" text-anchor="middle">{m}</text>')

    # languages
    lx = 596
    o.append(f'<text x="{lx}" y="{cy+16}" {F} font-size="14" font-weight="600" fill="#f0f6fc">Languages by code written</text>')
    for i, (name, b) in enumerate(top):
        y = cy + 46 + i * 36
        pct = 100 * b / total
        col = LANG_COLORS.get(name, "#8b949e")
        o.append(f'<text x="{lx}" y="{y}" {F} font-size="13" fill="#c9d1d9">{name}</text>')
        o.append(f'<text x="{W-32}" y="{y}" {F} font-size="13" fill="#8b949e" text-anchor="end">{pct:.0f}%</text>')
        o.append(f'<rect x="{lx}" y="{y+8}" width="232" height="8" rx="4" fill="#21262d"/>')
        o.append(f'<rect x="{lx}" y="{y+8}" width="{max(6, 232*pct/100):.1f}" height="8" rx="4" fill="{col}"/>')
    o.append('</svg>')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(o) + "\n")
    print("wrote", os.path.normpath(OUT), "| contrib", contrib_total, "| active", active, "| langs", top)


if __name__ == "__main__":
    sys.exit(main())
