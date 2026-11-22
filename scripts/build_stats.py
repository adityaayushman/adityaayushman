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
    own = [r for r in repos if not r["fork"] and not r["private"]]

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

    # ---- layout: flat, theme-aware, no gradients --------------------------
    pub = sum(1 for r in own if not r["archived"] and not r["private"])
    W, H = 860, 410
    F = "font-family=\"-apple-system,'Segoe UI',Helvetica,Arial,sans-serif\""
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W+24}" height="{H}" viewBox="-12 0 {W+24} {H}" role="img" '
         f'aria-label="GitHub activity summary for {USER}">',
         '<style>.t{fill:#1f2328}.m{fill:#59636e}.l{stroke:#d1d9e0}.b{fill:#59636e}.c0{fill:#ebedf0}.c1{fill:#9be9a8}.c2{fill:#40c463}.c3{fill:#30a14e}.c4{fill:#216e39}'
         '@media (prefers-color-scheme:dark){.t{fill:#f0f6fc}.m{fill:#9198a1}.l{stroke:#3d444d}.b{fill:#9198a1}.c0{fill:#151b23}.c1{fill:#033a16}.c2{fill:#196c2e}.c3{fill:#2ea043}.c4{fill:#56d364}}</style>']

    kpis = [(f"{contrib_total:,}", "Contributions, last 12 months"), (str(pub), "Public repositories"),
            (str(len(langs)), "Languages used")]
    cw_ = (W - 2) / 3
    for i, (val, label) in enumerate(kpis):
        x = 1 + i * cw_
        if i:
            o.append(f'<line class="l" x1="{x:.0f}" y1="14" x2="{x:.0f}" y2="70"/>')
        tx = x + (0 if i == 0 else 24)
        o.append(f'<text class="t" x="{tx:.0f}" y="46" {F} font-size="30" font-weight="600">{val}</text>')
        o.append(f'<text class="m" x="{tx:.0f}" y="68" {F} font-size="12">{label}</text>')
    o.append(f'<line class="l" x1="0" y1="96" x2="{W}" y2="96"/>')

    # contribution heatmap, GitHub's own green scale
    o.append(f'<text class="t" x="0" y="124" {F} font-size="13" font-weight="600">Contributions in the last year</text>')
    weeks = cal["weeks"]
    peak = max(d["contributionCount"] for w in weeks for d in w["contributionDays"]) or 1
    cell, step, gx, gy = 12, 15.4, 0, 164
    last_m = None
    for i, w in enumerate(weeks):
        m = w["contributionDays"][0]["date"][5:7]
        if m != last_m and 1 < i < len(weeks) - 2:
            o.append(f'<text class="m" x="{gx+i*step:.1f}" y="{gy-8}" {F} font-size="10">'
                     f'{datetime.strptime(m, "%m").strftime("%b")}</text>')
            last_m = m
        for d in w["contributionDays"]:
            c = d["contributionCount"]
            lvl = 0 if c == 0 else 1 + min(3, int(4 * (c - 1) / peak))
            wd = datetime.strptime(d["date"], "%Y-%m-%d").weekday()
            row = (wd + 1) % 7  # Sunday first, as on GitHub
            o.append(f'<rect class="c{lvl}" x="{gx+i*step:.1f}" y="{gy+row*step:.1f}" width="{cell}" height="{cell}" rx="2">'
                     f'<title>{c} contributions on {d["date"]}</title></rect>')
    ly = gy + 7 * step + 14
    o.append(f'<text class="m" x="{W-150}" y="{ly+9}" {F} font-size="10" text-anchor="end">Less</text>')
    for k in range(5):
        o.append(f'<rect class="c{k}" x="{W-142+k*16}" y="{ly}" width="{cell}" height="{cell}" rx="2"/>')
    o.append(f'<text class="m" x="{W-56}" y="{ly+9}" {F} font-size="10">More</text>')

    # languages: one stacked bar plus an inline legend
    ty = ly + 40
    o.append(f'<line class="l" x1="0" y1="{ty-20}" x2="{W}" y2="{ty-20}"/>')
    o.append(f'<text class="t" x="0" y="{ty}" {F} font-size="13" font-weight="600">Languages, by share of code</text>')
    o.append(f'<clipPath id="r"><rect x="0" y="{ty+14}" width="{W}" height="10" rx="5"/></clipPath><g clip-path="url(#r)">')
    x = 0
    tot = sum(v for _, v in top)
    for name, bts in top:
        w_ = W * bts / tot
        o.append(f'<rect x="{x:.1f}" y="{ty+14}" width="{w_:.1f}" height="10" fill="{LANG_COLORS.get(name, "#8b949e")}"/>')
        x += w_
    o.append('</g>')
    x = 0
    for name, bts in top:
        o.append(f'<circle cx="{x+5}" cy="{ty+42}" r="5" fill="{LANG_COLORS.get(name, "#8b949e")}"/>')
        o.append(f'<text class="t" x="{x+16}" y="{ty+46}" {F} font-size="12">{name} <tspan class="m">{100*bts/total:.0f}%</tspan></text>')
        x += 150
    o.append('</svg>')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(o) + "\n")
    print("wrote", os.path.normpath(OUT), "| contrib", contrib_total, "| active", active, "| langs", top)


if __name__ == "__main__":
    sys.exit(main())
