# YouTube cookies for yt-dlp (CI)

The pipeline's transcript fetcher (`pipeline/fetch_transcript.py`) has two backends:

1. **SocialKit** (`SOCIALKIT_API_KEY` set) — hosted, residential egress. CI uses this.
2. **yt-dlp fallback** — runs locally; can also run in CI but YouTube usually blocks unauthenticated data-center IPs, so it needs cookies from a logged-in browser session.

The `YT_COOKIES` GitHub secret feeds the yt-dlp fallback path. The monitor workflow at `.github/workflows/monitor.yml` writes the secret directly to `$RUNNER_TEMP/yt-cookies.txt` and exports `YT_COOKIES_FILE=<that path>`.

## Expected format

**Raw Netscape `cookies.txt` content — not base64-encoded.**

The secret value should be the exact contents of a Netscape-format cookies file: a header line, optional comments, then one cookie per line as tab-separated fields.

```
# Netscape HTTP Cookie File
# This is a generated file!  Do not edit.

.youtube.com	TRUE	/	TRUE	1769107200	VISITOR_INFO1_LIVE	abc123...
.youtube.com	TRUE	/	TRUE	1769107200	SID	xyz...
...
```

If you base64-encode the secret, the workflow will write the encoded text to disk and yt-dlp will reject it.

## How to generate

1. Sign in to YouTube in a real browser.
2. Install a cookies.txt exporter extension (e.g. "Get cookies.txt LOCALLY" for Chrome, "cookies.txt" for Firefox).
3. Visit `https://www.youtube.com` while signed in and export cookies for that domain only.
4. Open the downloaded `cookies.txt`; copy the entire contents (including the `# Netscape HTTP Cookie File` header).
5. Paste into the `YT_COOKIES` GitHub secret. Do not encode.

## How to refresh

YouTube session cookies typically last weeks to a few months. Symptoms of expiry:

- Workflow run logs show `Sign in to confirm you're not a bot` or HTTP 403 from yt-dlp.
- SocialKit path still works, so the fallback is silently bypassed — the only signal is repeated yt-dlp failures in logs.

To refresh: repeat the steps above with a freshly signed-in browser session and replace the secret value.

## Verifying locally

```bash
export YT_COOKIES_FILE=/path/to/cookies.txt
python -c "import yt_dlp; \
  ydl = yt_dlp.YoutubeDL({'cookiefile': '$YT_COOKIES_FILE', 'quiet': True}); \
  print(ydl.extract_info('https://www.youtube.com/watch?v=dQw4w9WgXcQ', download=False)['title'])"
```

If this prints the video title without errors, the cookie file is valid.
