# Jon Stewart Monologues

A static page listing Jon Stewart's weekly *Daily Show* monologues (newest first), refreshed hourly by GitHub Actions and served by GitHub Pages.

**Live: <https://lysak.github.io/jon-stewart-monologue/>**

## How it works

1. Every hour `scripts/update.py` reads the official ["Jon Stewart Hosting The Daily Show"](https://www.youtube.com/playlist?list=PLeskMkEaHJYfTMaKwmBWGq4NogX9FLF2J) playlist and the latest 50 channel uploads via YouTube Data API v3.
2. Shorts and clips (under 6 minutes) and multi-host weekly recaps (another host named in the title) are skipped first, since recaps reuse the welcome chapter. Otherwise a video is a **monologue** when its description has a `0:00` chapter like `Jon Stewart's TDS Welcome`, `Jon Stewart's TDS Open` or `TDS Welcome from Jon Stewart`.
3. Videos without that chapter go to [Cloudflare Clef](https://blog.cloudflare.com/clef-decision-models/), a decision model on Workers AI (free tier: 10,000 Neurons/day, ~450K Clef tokens). P(monologue) ≥ 0.5 publishes it when the video went up between 22:30 and 01:00 New York time, right after an episode airs; otherwise ≥ 0.45 puts it in **Needs review**. In Oct 2026, 93 of 95 known monologues went up in that slot, where marker-less monologues scored ≥ 0.81 and the 89 rejects (mostly interviews at 23:30) ≤ 0.13. Outside the slot, archive re-uploads at 09:00 score up to 0.8, so those always go to review. Answers are cached per video in `data/clef.json`, so each video is asked once. Without Cloudflare secrets, a heuristic fills **Needs review** instead (description starts with "Jon Stewart", no other host in the title).
4. `data/overrides.json` forces a video id in (`include`) or out (`exclude`). It ships with a hand-checked 2024–2025 archive (marker-less monologues in, archive compilations out), verified against a full export of the playlist in Oct 2026.
5. Every run rewrites `data/status.json` with two timestamps — when the list last changed (`data/last-changed.txt`) and when the data was last refreshed — then redeploys Pages. `data/videos.json`, `data/clef.json` and `data/last-changed.txt` are committed to the separate `data` branch, so `main` only ever holds code and `data/overrides.json`.
6. While anything sits in **Needs review**, the workflow keeps one open issue labelled `needs-review` that mentions the repo owner (so GitHub sends an email). Settle each video in `data/overrides.json` and the next run closes the issue.

Quota: 16 units per run (measured Oct 2026), ~400 per day, out of the free 10,000 per day. `data/videos.json` and `data/clef.json` live on the `data` branch, so they double as the cache between runs: a repeat run makes no Clef calls.

The page (`index.html`) is plain HTML, CSS and JS with no build step: the newest monologue on top, then one ledger row per monologue grouped by year and month, a month index in the margin with shareable `#2025-03` links, a light/dark toggle, and the **Needs review** list at the bottom.

## Setup

1. Create a YouTube Data API v3 key in Google Cloud Console (APIs & Services → Credentials → API key; restrict it to "YouTube Data API v3").
2. Repo → Settings → Secrets and variables → Actions → add secret `YOUTUBE_API_KEY`.
   Optional, for Clef: `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (Cloudflare dashboard → My Profile → API Tokens → "Workers AI" template).
3. Repo → Settings → Pages → Source: **GitHub Actions**.
4. Actions → "Update monologues" → **Run workflow**.

`sitemap.xml` lists the archive's canonical URL. `robots.txt` allows crawling and points to that sitemap. On GitHub Pages, this project is served under `/jon-stewart-monologue/`, but crawlers only use the host-root `https://lysak.github.io/robots.txt`. Add `Sitemap: https://lysak.github.io/jon-stewart-monologue/sitemap.xml` to that root file alongside its existing sitemap, or submit the project sitemap directly in Google Search Console.

## Local run

```bash
cp .env.example .env       # then fill in the keys
set -a; . ./.env; set +a
python3 scripts/update.py
python3 -m unittest discover -s tests
python3 -m http.server   # open http://localhost:8000
```

`data/videos.json`, `data/clef.json` and `data/last-changed.txt` are generated and gitignored; they are kept on the `data` branch. To start from the live state, run `git checkout origin/data -- data/videos.json data/clef.json data/last-changed.txt`.
