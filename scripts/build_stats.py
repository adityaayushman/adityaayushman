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
    W, H = 860, 400
    F = "font-family=\"-apple-system,'Segoe UI',Helvetica,Arial,sans-serif\""
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W+24}" height="{H}" viewBox="-12 0 {W+24} {H}" role="img" '
         f'aria-label="GitHub activity summary for {USER}">',
         '<style>.t{fill:#1f2328}.m{fill:#59636e}.l{stroke:#d1d9e0}.b{fill:#59636e}.gs{stroke:#30a14e}.c0{fill:#ebedf0}.c1{fill:#9be9a8}.c2{fill:#40c463}.c3{fill:#30a14e}.c4{fill:#216e39}'
         '@media (prefers-color-scheme:dark){.t{fill:#f0f6fc}.m{fill:#9198a1}.l{stroke:#3d444d}.b{fill:#9198a1}.gs{stroke:#2ea043}.c0{fill:#151b23}.c1{fill:#033a16}.c2{fill:#196c2e}.c3{fill:#2ea043}.c4{fill:#56d364}}</style>']

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

    # weekly trend (area chart) and weekday pattern, in GitHub's green
    weeks = cal["weeks"]
    wk = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in weeks]
    first = next((i for i, v in enumerate(wk) if v), 0)
    first = max(0, min(first - 2, len(wk) - 20))  # start just before the first active week
    weeks, wk = weeks[first:], wk[first:]
    cy, cw, ch = 124, 520, 150
    o.append(f'<text class="t" x="0" y="{cy}" {F} font-size="13" font-weight="600">Weekly contributions</text>')
    top_y, base = cy + 28, cy + ch
    mx = max(wk) or 1
    pts = [(i * cw / (len(wk) - 1), base - (v / mx) * (base - top_y)) for i, v in enumerate(wk)]
    for g in (0, 0.5, 1):
        y = base - g * (base - top_y)
        o.append(f'<line class="l" x1="0" y1="{y:.1f}" x2="{cw}" y2="{y:.1f}" stroke-dasharray="{"0" if g == 0 else "2 4"}"/>')
        if g:
            o.append(f'<text class="m" x="{cw+6}" y="{y+3:.1f}" {F} font-size="10">{int(mx*g)}</text>')
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    o.append(f'<polygon class="c2" opacity="0.28" points="0,{base} {line} {cw},{base}"/>')
    o.append(f'<polyline fill="none" class="gs" stroke-width="2" stroke-linejoin="round" points="{line}"/>')
    pk = wk.index(mx)
    o.append(f'<circle class="c4" cx="{pts[pk][0]:.1f}" cy="{pts[pk][1]:.1f}" r="3.5"/>')
    o.append(f'<text class="m" x="{min(pts[pk][0], cw-60):.1f}" y="{pts[pk][1]-9:.1f}" {F} font-size="10">peak week: {mx}</text>')
    last = None
    for i, w in enumerate(weeks):
        m = w["contributionDays"][-1]["date"][5:7]
        if m != last and 0 < i < len(weeks) - 2:
            o.append(f'<text class="m" x="{pts[i][0]:.1f}" y="{base+16}" {F} font-size="10" text-anchor="middle">'
                     f'{datetime.strptime(m, "%m").strftime("%b")}</text>')
        last = m

    # weekday pattern (horizontal bars)
    wx, ww = 590, W - 590
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    tot_wd = [0] * 7
    for w in weeks:
        for d in w["contributionDays"]:
            tot_wd[datetime.strptime(d["date"], "%Y-%m-%d").weekday()] += d["contributionCount"]
    mw = max(tot_wd) or 1
    o.append(f'<text class="t" x="{wx}" y="{cy}" {F} font-size="13" font-weight="600">Busiest days of the week</text>')
    for i, (n_, v) in enumerate(zip(names, tot_wd)):
        y = cy + 24 + i * 20
        o.append(f'<text class="m" x="{wx}" y="{y+10}" {F} font-size="11">{n_}</text>')
        bwid = max(2, (ww - 76) * v / mw)
        o.append(f'<rect class="c3" x="{wx+34}" y="{y}" width="{bwid:.1f}" height="12" rx="2"/>')
        o.append(f'<text class="m" x="{wx+34+bwid+6:.1f}" y="{y+10}" {F} font-size="10">{v}</text>')
    ly = base
    # languages: one stacked bar plus an inline legend
    ty = ly + 56
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
