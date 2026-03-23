# Subtitle Foundry

Subtitle Foundry is a polished web app for analyzing YouTube subtitle availability, previewing transcript content, translating supported tracks, and exporting subtitles in multiple formats.

## What it does

- Detects all available subtitle tracks on a YouTube video
- Separates manual captions from auto-generated tracks
- Lets users filter and search tracks before choosing one
- Previews subtitles in both timestamp and reading views
- Exports subtitles as `SRT`, `TXT`, `CSV`, `VTT`, and `JSON`
- Uses YouTube's transcript translation support when a track exposes it

## Local setup

```bash
cd "/Users/basilahmad/Documents/Playground/Youtube Subtitle Downloader"
python3 -m pip install -r requirements.txt
python3 app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Tests

```bash
python3 -m unittest discover -s tests
```

## Production run

```bash
gunicorn app:app
```

The app reads:

- `PORT` for the HTTP port
- `HOST` for the bind address
- `FLASK_DEBUG` for local debug mode

## Deploy on Render

This repo already includes:

- `render.yaml`
- `Procfile`
- `requirements.txt`

To deploy:

1. Push the project to GitHub.
2. Create a new Web Service on Render.
3. Point Render at the GitHub repo.
4. Confirm the build command is `pip install -r requirements.txt`.
5. Confirm the start command is `gunicorn app:app`.
6. Deploy.
7. After the first successful deploy, attach a custom domain if you want one.

## Notes

- Translation availability depends on the selected subtitle track and what YouTube exposes for that video.
- YouTube may rate-limit or block transcript requests from some networks or hosting IPs.
- If translation fails on the deployed app, original subtitle tracks can still work while translated fetches are blocked.
