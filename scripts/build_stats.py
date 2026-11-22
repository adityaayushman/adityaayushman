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
    W, H = 860, 300
    F = "font-family=\"-apple-system,'Segoe UI',Helvetica,Arial,sans-serif\""
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W+24}" height="{H}" viewBox="-12 0 {W+24} {H}" role="img" '
         f'aria-label="GitHub activity summary for {USER}">',
         '<style>.t{fill:#1f2328}.m{fill:#59636e}.l{stroke:#d1d9e0}.b{fill:#59636e}.k{fill:#eaeef2}'
         '@media (prefers-color-scheme:dark){.t{fill:#f0f6fc}.m{fill:#9198a1}.l{stroke:#3d444d}.b{fill:#9198a1}.k{fill:#262c36}}</style>']

    kpis = [(f"{contrib_total:,}", "Contributions, last 12 months"), (str(pub), "Public repositories"),
            (str(active), "Updated in the last 90 days"), (str(len(langs)), "Languages used")]
    cw_ = (W - 2) / 3
    for i, (val, label) in enumerate(kpis):
        x = 1 + i * cw_
        if i:
            o.append(f'<line class="l" x1="{x:.0f}" y1="14" x2="{x:.0f}" y2="70"/>')
        tx = x + (0 if i == 0 else 24)
        o.append(f'<text class="t" x="{tx:.0f}" y="46" {F} font-size="30" font-weight="600">{val}</text>')
        o.append(f'<text class="m" x="{tx:.0f}" y="68" {F} font-size="12">{label}</text>')
    o.append(f'<line class="l" x1="0" y1="96" x2="{W}" y2="96"/>')

    # monthly bars (single muted colour)
    cx, cy, cw, ch = 0, 120, 470, 170
    o.append(f'<text class="t" x="{cx}" y="{cy+8}" {F} font-size="13" font-weight="600">Contributions by month</text>')
    mx = max(v for _, v in series) or 1
    n = len(series)
    bw = min(34, (cw - 8 * (n - 1)) / n)
    gap_ = (cw - n * bw) / max(1, n - 1) if n > 1 else 0
    base = cy + ch - 18
    for i, (m, v) in enumerate(series):
        x = cx + i * (bw + gap_)
        h = max(2, (v / mx) * (ch - 70))
        o.append(f'<rect class="b" x="{x:.1f}" y="{base-h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="2"/>')
        o.append(f'<text class="m" x="{x+bw/2:.1f}" y="{base-h-6:.1f}" {F} font-size="10" text-anchor="middle">{v}</text>')
        o.append(f'<text class="m" x="{x+bw/2:.1f}" y="{base+14}" {F} font-size="10" text-anchor="middle">{m}</text>')

    # languages: one stacked bar plus a plain legend
    lx, lw = 540, W - 540
    o.append(f'<text class="t" x="{lx}" y="{cy+8}" {F} font-size="13" font-weight="600">Languages, by share of code</text>')
    o.append(f'<clipPath id="r"><rect x="{lx}" y="{cy+26}" width="{lw}" height="10" rx="5"/></clipPath><g clip-path="url(#r)">')
    x = lx
    for name, bts in top:
        w_ = lw * bts / sum(v for _, v in top)
        o.append(f'<rect x="{x:.1f}" y="{cy+26}" width="{w_:.1f}" height="10" fill="{LANG_COLORS.get(name, "#8b949e")}"/>')
        x += w_
    o.append('</g>')
    for i, (name, bts) in enumerate(top):
        y = cy + 66 + i * 22
        o.append(f'<circle cx="{lx+5}" cy="{y-4}" r="5" fill="{LANG_COLORS.get(name, "#8b949e")}"/>')
        o.append(f'<text class="t" x="{lx+18}" y="{y}" {F} font-size="13">{name}</text>')
        o.append(f'<text class="m" x="{W}" y="{y}" {F} font-size="13" text-anchor="end">{100*bts/total:.0f}%</text>')
    o.append('</svg>')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(o) + "\n")
    print("wrote", os.path.normpath(OUT), "| contrib", contrib_total, "| active", active, "| langs", top)


if __name__ == "__main__":
    sys.exit(main())
