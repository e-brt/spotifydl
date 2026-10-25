# Spotify Playlist Downloader — Project Specification

Current state of the project, as of version **1.1.0** (2026-10-25). The
README explains how to install, run, test, build and release;
`CHANGELOG.md` lists the changes of each version. This document describes
what the application does, how it is built, the decisions behind it and what
remains to do.

## 1. Overview

**Spotify Playlist Downloader** is a Windows desktop application that keeps
local folders of audio files (mp3 by default, with full metadata) in sync with
Spotify playlists. It is built with Python and PySide6 on top of
[spotDL](https://github.com/spotDL/spotify-downloader), which finds each track
on YouTube Music and downloads it with yt-dlp and FFmpeg.

It is distributed as a standalone Windows build (PyInstaller, one folder), so
users do not need Python. Releases are published on GitHub.

Priorities: reliability, clear feedback, safe process management, never
losing or silently deleting the user's files, and a simple user experience.

## 2. Technology and project layout

- **Python 3.13** (spotDL supports 3.10 to 3.14), **PySide6 6.12** for the
  GUI, **spotDL 4.5.2** with yt-dlp, ytmusicapi, spotapi and SpotipyFree.
- **PyInstaller 6.22** for the build; **Deno, FFmpeg and FFprobe** as external
  executables.
- All Python packages are pinned in `requirements.txt` (80 packages); the
  external executables are pinned in `vendor.json`.

```text
src\                 application code (run from source: python src\main.py)
  main.py            entry point: window, --spotdl-worker, --self-check
  main_window.py     window layout, menus, theme, About, closing
  profiles.py        playlist profiles (mixin of MainWindow)
  downloads.py       worker start/stop, logs, progress, end of run (mixin)
  worker.py          the spotDL worker process
  theme.py, widgets.py, config_manager.py, process_control.py,
  recycle_bin.py, resources.py, version.py
tests\               unittest suite (87 tests, about 80 s, no network)
tools\               collect_licenses.py (build)
assets\              application icon
build.ps1            build, test and package
fetch_vendor.ps1     download the pinned external executables (vendor.json)
.github\workflows\   release workflow
```

The packaged application keeps its folder uncluttered:

```text
SpotifyDownloader\
├── SpotifyDownloader.exe
├── _internal\     code, libraries, vendor executables, icon
├── data\          config.json, spotify_cache.json, logs\ (the user's files)
└── docs\          LICENSE, CHANGELOG.md, THIRD_PARTY_NOTICES.md, licenses\
```

## 3. Features

### 3.1 Playlist profiles

Users create, duplicate, edit, select and delete profiles. Each profile has:
name, Spotify playlist URL, destination folder, audio format (`mp3`, `m4a`,
`opus`, `ogg`, `flac`, `wav`), bitrate (`auto`, `128k` to `320k`; disabled for
lossless formats) and number of download threads (1 to 16).

Profiles are stored in `data\config.json` (section 6). Defaults are `mp3` and
`128k`, spotDL's own defaults, so libraries created before these settings
existed are not downloaded again.

### 3.2 Downloading

Start downloads the selected profile's playlist into its destination folder
(created if needed). The worker checks what is already there and only
downloads what is missing or does not match the selected quality (section
5.3). spotDL's live output is shown in the window, wrapped to its width, with
rich's line padding removed.

**Download all** downloads every profile in turn, in the list order; the
profile being downloaded is selected in the list, and each run has its own
saved log. The queue never waits for the user:
- a profile that cannot be downloaded (invalid URL, no destination, missing
  vendor executable, folder that cannot be created) is skipped with a
  `[Download all] Skipped …` log line instead of a dialog;
- a failed run does not stop the queue; Stop ends the current run and cancels
  the remaining profiles;
- the per-run notification and clean-up questions are kept for the end: one
  notification with a summary (e.g. "3 profile(s): 2 completed, 1 skipped."),
  then the clean-up questions of each completed profile, titled with its name;
- Retry failed applies to the last profile downloaded.

### 3.3 Progress

A progress bar and a counter, e.g. `42 / 194 tracks · 21% · 2 failed`.

- **Counting rule:** processed / total, where a track is processed when it is
  already up to date, downloaded, or failed; failures are also shown apart.
- The bar is indeterminate until the total is known, starts at the number of
  tracks already up to date, then advances with each finished download. The
  status text follows the phases: "Fetching playlist…", "Checking existing
  tracks…", "Downloading…".
- On Stop, the last known progress is kept. An empty playlist shows
  `0 / 0 tracks · 100%`.
- The progress comes from events sent by the worker (section 4.3), not from
  parsing spotDL's log lines.

### 3.4 Stop and Close

Stop ends the whole worker process tree, FFmpeg included, and the final status
is **Stopped** (not Error). Closing the window during a download asks for
confirmation and stops it the same way. The track that was being written at
that moment is removed (section 4.2), so it is downloaded again next time
instead of being kept truncated.

### 3.5 End of a run

- **Failed tracks** are listed in the log, and a **Retry failed (N)** button
  downloads again only those tracks.
- **Notification:** when a run ends while the window is in the background, the
  taskbar button flashes and a Windows notification summarizes it (e.g. "194
  tracks: 182 downloaded, 10 already up to date, 2 failed."). Clicking it
  brings the window back; the notification area icon disappears once the
  window is used again. No notification after Stop.
- **Playlist file:** `<playlist name>.m3u8` is written in the destination
  after each complete run, with the tracks in the Spotify playlist order
  (spotDL's own `--m3u` only lists the tracks downloaded during the run).
- **Clean-up offers**, after a complete run only, each with its own
  confirmation dialog (file list in the details, **Keep** as the default):
  - files whose track is no longer in the playlist (found through the Spotify
    URL spotDL writes in each file's metadata);
  - older copies of tracks in another audio format, after a format change
    (same name, other extension), only when the file in the selected format
    exists.

  Confirmed files are moved to the **Windows Recycle Bin**, so they can be
  restored. Nothing is ever deleted without confirmation.

### 3.6 Saved logs

Each run's log is saved in `data\logs\<start time> <profile>.log` (e.g.
`2026-10-25 14-30-12 Rock.log`), opened with **File → Open logs folder**.

- The file holds exactly what the log view shows, starting with a header line
  (application version and start time), without the progress events.
- The log view (`widgets.LogView`) writes each line to the file as it is shown
  and flushes it, so the log survives a crash; the view itself keeps only its
  last 5,000 lines, the file keeps everything, and clearing the view does not
  touch the file.
- The file stays attached until the next run starts or the window closes, so
  messages written after the worker ended (removal of a partial file, Recycle
  Bin results) are saved too.
- Only the latest `MAX_LOG_FILES` (100) logs are kept. If the folder cannot be
  used, the run continues and the log view says so.

### 3.7 Interface

- Dark and light themes, switched with a sun/moon switch in the header or
  **View → Theme → Light / Dark** (exclusive, kept in sync), saved in
  `settings.theme` as soon as it changes, applied before the window is shown;
  a missing or unknown value falls back to dark.
- One color palette per theme (`theme.THEMES`) fills a single stylesheet
  template; scroll bars, combo box arrows and spin box buttons are styled too
  (chevrons drawn at run time in the theme color, so the build does not need
  the Qt SVG plugin).
- The window's minimum size is the one its layout needs (minimum width 850
  px), so fields are never squeezed.
- The version is shown in the title, next to the application name, in
  **Help → About** (with the spotDL version and licenses) and in the
  executable's Windows file properties.

## 4. Architecture

### 4.1 Worker process

spotDL runs in a separate worker process, so the GUI stays responsive and the
download can be stopped. The packaged executable starts itself with
`--spotdl-worker` (from source: `python src\main.py --spotdl-worker`), with
arguments `--url`, `--format`, `--bitrate`, `--threads` and, for a retry,
`--only-tracks <JSON file of Spotify track URLs>`.

The GUI starts it with `QProcess`, in the destination folder, with:
- the full system environment (`QProcessEnvironment.systemEnvironment()`;
  `processEnvironment()` is empty until one is set, which previously left the
  worker without `SystemRoot`, `TEMP`, `APPDATA`…);
- `vendor` first in `PATH`, `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8` and
  `COLUMNS=300` (rich otherwise wraps at 80 columns);
- each `QProcess` signal bound to the process that emitted it, so signals from
  an earlier worker never change the state of a newer download.

The worker starts FFmpeg, FFprobe and Deno with `CREATE_NO_WINDOW`, so no
console window flashes in the windowed build.

### 4.2 Stopping the process tree (`process_control.py`)

On Windows, `QProcess.terminate()` only posts `WM_CLOSE`, which a windowless
worker never receives, and `kill()` only ends the worker itself. Therefore:

- `ProcessTree` keeps a handle on the worker (so its PID cannot be reused),
  enumerates all its descendants from a process snapshot (a child is trusted
  only if it was created after its parent), opens them all, and only then
  terminates the whole tree. Collecting first matters: an intermediate process
  can take others down with it and break the parent/child chain.
- The worker is also in a Job Object with `KILL_ON_JOB_CLOSE`, as a safety net
  if the GUI exits or crashes (not sufficient alone: a GUI started inside a job
  that allows silent breakaway, as some terminals and IDEs do, lets children
  escape nested jobs).
- On Windows Stop terminates the tree at once; a watchdog (`STOP_TIMEOUT_MS`,
  5 s) forces it again if the worker is still alive.

**Partially written file:** just before killing, the GUI lists the audio
files of the destination created or modified since the download started (2 s
tolerance) that another process still holds open (opening them without
sharing fails). After the worker exited, these files are deleted, with retries
(`PARTIAL_DELETE_ATTEMPTS` × `PARTIAL_DELETE_RETRY_MS`) because killed
processes release their files with a delay. Completed files and files that
existed before are never touched.

### 4.3 Progress events

The worker writes JSON events on output lines starting with `@@progress `,
each in a single write so log lines from other threads cannot split it. The
GUI removes them from the log view; malformed events are ignored.

| Event | Data |
|---|---|
| `phase` | `fetching`, `checking` (with `total`), `downloading` |
| `total` | `total` tracks, `done` = already up to date |
| `track` | one download finished: `ok`, `name`, `url` (Spotify) |
| `cleanup` | end of a complete run: `removed`, `other_formats` (paths relative to the destination) |

### 4.4 Worker phases (`worker.py`)

The worker drives spotDL as a library rather than running its `download`
command:

1. Fetch the playlist (always, so added and removed tracks are seen); for a
   retry, keep only the requested tracks.
2. Complete every track's metadata with `CHECK_THREADS` (8) threads.
3. Create spotDL's downloader, which scans the destination for known tracks.
4. Check every track against the destination with `CHECK_THREADS` threads
   (section 5.3).
5. Hand only the tracks to (re)download to spotDL, with the profile's thread
   count and `--overwrite force`. The thread count therefore only limits
   actual downloads, which is what triggers provider rate limits.
6. For a complete run (not a retry): write the `.m3u8` file and report the
   clean-up candidates.

## 5. spotDL integration

### 5.1 Fixes applied to spotDL and its dependencies

These patch internals of spotDL, spotapi, SpotipyFree and ytmusicapi. The
packaged `--self-check` verifies that every patched attribute still exists,
and `build.ps1` runs it on each build; they must still be checked by hand,
with a real download, whenever one of these packages is upgraded.

- **YouTube Music returned no results.** spotDL creates its YouTube Music
  client with `language="de"`; with any non-English language YouTube Music
  currently returns no search results at all, so every track failed with "no
  usable results". The worker creates the client in English.
- **Spotify lookups were slow and got the IP rate limited.** spotapi creates a
  new web player client for every track, album and artist lookup, and each
  reloads the web player, new tokens and about 80 JavaScript files: about 250
  requests and 7 s per track, and HTTP 429 for over half an hour after a few
  runs. The worker shares one web player session between clients (about 3
  requests and 1 s per track).
- **Blocked videos.** Age-restricted, private, region-locked or members-only
  videos cannot be downloaded without a YouTube account; the restriction
  belongs to the video, so youtube.com, music.youtube.com and yt-dlp's YouTube
  Music client fail alike. When yt-dlp reports such an error, the video id is
  removed from later YouTube Music results and the track is searched and
  downloaded again, up to `MAX_ALTERNATIVE_RESULTS` (3) other results. spotDL
  also reads the view count of close candidates through yt-dlp to break ties;
  a blocked candidate now counts as 0 views instead of making the whole search
  fail. Bot checks and rate limits are not treated as blocked videos.

### 5.2 Spotify cache

spotDL's own cache only works with the official Spotify API, so the worker
keeps `data\spotify_cache.json`:
- **track metadata** (`Song.from_url`), per Spotify track id, for
  `TRACK_CACHE_DAYS` (30) days;
- **web player query hashes**, until Spotify deploys a new web player build
  (only the entries spotapi looks up are kept: about 18 kB instead of 6.8 MB).

The playlist itself is always fetched. A repeated run on a 194-track playlist
makes 5 Spotify requests instead of 663 (3 s instead of 25 s for the check).
The cache is saved after the check phase and at the end of the run; a missing,
damaged or incompatible file is ignored, and deleting it is always safe.

### 5.3 Rules for existing files

A track is downloaded again when none of its existing files (the expected
name, or a file of the selected format whose metadata points to the same
Spotify track) passes all of these checks:
- the file can be read;
- its duration is at least 75% of the Spotify track duration (truncated
  files);
- for a fixed bitrate, its measured bitrate is at least 90% of the selected
  one (65% for Opus, which is variable bitrate and measured at 72–81% of the
  requested value).

`auto` keeps the bitrate of the YouTube source (usually 128k to 160k); a
higher bitrate makes larger files but cannot add quality the source does not
have. Only files in the selected format are checked; older copies in another
format are offered for clean-up (section 3.5).

## 6. User files

`config_manager.py` stores the user's files in `data\`, next to the executable
(or in the project folder from source): `config.json`, `config.json.broken`
(a damaged configuration is set aside there and replaced by a default one),
`spotify_cache.json` and `logs\` (section 3.6). The configuration is written atomically (temporary
file, then replace). Files left next to the executable by builds before
`data\` existed are moved there on the next start; a file already in `data\`
is never overwritten.

`build.ps1` keeps these files across rebuilds (PyInstaller deletes the output
folder), in both the current and the former location, and the release
archive never contains them.

## 7. Build, test and release

### 7.1 Dependencies

- `requirements.txt` pins all 80 Python packages; `build.ps1` refuses to build
  if the installed versions differ.
- `vendor.json` pins Deno 2.9.8 and FFmpeg/FFprobe
  2026-10-22-git-bf0e831606 (gyan.dev essentials build): URL and SHA-256 of
  each archive, executable and license. `fetch_vendor.ps1` downloads only what
  is missing or different, checks every hash, and stops without changing
  `vendor\` on any mismatch. `vendor\` is not versioned.

### 7.2 Tests

`python -m unittest discover -s tests`: 87 tests, about 80 s, no network. The
GUI tests run the real window with a fake worker (`tests\fake_worker.py`), an
in-memory configuration and a temporary folder. They cover Stop and Close
(Windows process tree, partial file), progress, end of run (retry,
notification, clean-up offers, Recycle Bin calls), Download all, saved logs, themes, the minimum window
size (on the real Windows platform, with a transparent window), the
configuration location and migration, the worker logic (blocked video retry,
Spotify cache, quality check on files generated with FFmpeg, playlist file,
removed tracks, older format copies), release consistency and the self-check.
Real downloads are checked by hand.

### 7.3 Build

`build.ps1` (`-Package` for the release archive, `-SkipTests` to skip the
tests):
1. reads the version from `src\version.py` and checks that `CHANGELOG.md` has
   a section for it;
2. runs `fetch_vendor.ps1`;
3. checks the installed packages against `requirements.txt`, then runs the
   tests;
4. keeps the user files of the previous build;
5. runs PyInstaller (entry `src\main.py`), with the version in the
   executable's file properties, then restores the user files;
6. adds `docs\` (license, changelog, third-party notices, license texts of
   FFmpeg, Deno and the 76 bundled Python packages);
7. checks the output and runs the packaged `--self-check`;
8. with `-Package`, writes `dist\SpotifyDownloader-<version>-win64.zip`
   (without `data\`) and its `.sha256`.

### 7.4 Versioning and release

- Semantic Versioning; the version is defined once in `src\version.py`.
- `CHANGELOG.md` follows Keep a Changelog; new entries go under
  `[Unreleased]`.
- Pushing an annotated tag `vX.Y.Z` runs `.github/workflows/release.yml`: it
  builds on Windows with Python 3.13 and `build.ps1 -Package`, checks that the
  tag matches `src\version.py`, and publishes a GitHub Release with the zip,
  its SHA-256 and the changelog section as release notes. The workflow can
  also be run by hand to only build the archive.
- Published: **1.0.0** and **1.1.0**.

### 7.5 Licensing

The project is MIT licensed. The build ships `THIRD_PARTY_NOTICES.md` and the
license texts of the bundled software: FFmpeg (GPL-3.0; the notice says where
its corresponding source is), Deno (MIT), Qt for Python (LGPL-3.0, shipped as
replaceable dynamic libraries), spotDL (MIT), yt-dlp (Unlicense) and the other
Python packages (`docs\licenses\python\SUMMARY.txt`).

## 8. Known limitations

- **Genre metadata is empty**: Spotify returns empty genres through the web
  player API spotDL uses.
- **YouTube changes break downloads** until yt-dlp is updated, and the
  versions are pinned: an upgrade must be made by hand (section 9).
- **Opus bitrate check** is approximate (variable bitrate).
- **The executable is not code-signed**: Windows SmartScreen shows "unknown
  publisher" the first time a downloaded build runs.
- **Spotify rate limiting** can still happen with many complete runs on
  uncached playlists in a short time (HTTP 429, lifts by itself).
- Windows only: the open-file check, process tree handling and Recycle Bin
  are Windows specific.

## 9. Roadmap

| Priority | Item | Notes |
|---|---|---|
| P1 | Run the tests on every push to `main` | Small workflow; today they only run when building a release |
| P1 | Keep yt-dlp up to date | Dependabot (or a documented routine) to propose pin upgrades, validated by the tests and a real download |
| P2 | Fill the genre metadata | e.g. from the artist's genres |
| P2 | Lyrics | Check spotDL's lyrics providers; optional synced lyrics (`.lrc`) per profile |
| P2 | Automatic sync | Headless mode (`SpotifyDownloader.exe --sync "<profile>"`) for the Windows Task Scheduler |
| P3 | Save each run's log | e.g. in `data\logs\` ||
