# Spotify Playlist Downloader — Project Specification

## 1. Project Overview

**Spotify Playlist Downloader** is a Windows desktop application built with Python and PySide6. It provides a graphical interface for managing Spotify playlist profiles and downloading tracks using spotDL.

The application is intended to be distributed as a standalone Windows application using PyInstaller, so users do not need to install Python or the project's Python dependencies manually.

The main priorities are reliability, clear feedback, safe process management, and a simple user experience.

## 2. Technology Stack

- **Python 3.10**
- **PySide6** for the desktop GUI
- **spotDL** for playlist scanning and downloading
- **QProcess** for launching and managing the spotDL worker process
- **PyInstaller** for packaging the application
- **Deno, FFmpeg and FFprobe** for external runtime dependencies
- **JSON** for local profile configuration

## 3. Current Features

### 3.1 Playlist profiles

Users can create, edit, duplicate, select, and delete playlist profiles.

Each profile contains:
- Profile name
- Spotify playlist URL
- Destination folder
- Number of download threads

Profiles are stored locally in `config.json`. Existing profiles should be preserved when the application is updated or rebuilt.

### 3.2 Download management

The GUI allows users to start a download for the selected profile and monitor spotDL output in real time.

The current command arguments include:

```text
--overwrite skip
--scan-for-songs
--threads <number>
download <playlist_url>
```

The destination folder is created automatically if it does not exist. Existing files should be skipped rather than downloaded again, subject to spotDL's behavior.

### 3.3 Live logs and status

The interface displays:
- Current application status
- Download progress information emitted by spotDL
- Standard output and error output merged into a single log stream
- A button to clear displayed logs

The log view should remain responsive during long-running scans and downloads.

### 3.4 Visual interface and icon

The application uses a dark theme with dedicated Start and Stop buttons, profile management controls, and a custom icon.

The icon is used in two separate places:
- **Executable icon:** embedded by PyInstaller using `--icon`.
- **Application/window icon:** configured through PySide6 using `QIcon`.

The ICO file is stored in `assets/spotifydownloader.ico`. Runtime access must use the correct bundled resource path.

## 4. Architecture and Process Management

The application launches spotDL in a separate worker process rather than running the download directly inside the GUI process.

When packaged, the executable launches itself with the `--spotdl-worker` argument. The worker invokes spotDL's console entry point.

This design is intended to:
- Keep the GUI responsive.
- Capture spotDL output.
- Allow the user to stop a running operation.
- Separate download execution from GUI logic.

The GUI uses `QProcess` signals to receive output, detect process completion, and handle errors.

**Important:** the worker must be managed as an operating-system process. Stopping log reception is not the same as stopping the scan or download.

## 5. Vendor Dependency Management and Limitations

The project currently manages external binaries manually through a `vendor` directory:

```text
vendor/
├── deno.exe
├── ffmpeg.exe
└── ffprobe.exe
```

PyInstaller bundles these binaries into the packaged application using `--add-binary`.

### Limitations of manual vendor management

- **Manual updates:** new versions must be downloaded and added by the maintainer.
- **Version compatibility:** a binary update may introduce incompatibilities with spotDL or other dependencies.
- **Windows compatibility:** executables must match the target Windows architecture and supported operating systems.
- **Distribution size:** bundling external binaries increases the application size.
- **Licensing:** redistribution rights and required license notices must be checked for each bundled dependency.
- **Security:** binaries should come from trusted sources and be updated when needed.
- **Packaging consistency:** development and packaged versions must resolve the intended binary versions.
- **Path handling:** the application must locate bundled executables correctly in a PyInstaller distribution.

The application currently modifies `PATH` to prioritize the bundled vendor directory. Preserve this behavior unless a more reliable dependency-resolution strategy is introduced.

### Potential improvements

1. Pin and document supported versions of spotDL, Deno, FFmpeg and FFprobe.
2. Validate required binaries at startup and display clear messages if one is missing.
3. Document the source, version and license of every bundled executable.
4. Add a repeatable build script that validates vendor files before packaging.
5. Consider controlled, automated vendor updates, including integrity verification and compatibility checks.
6. Test the packaged application on a clean Windows machine without the development environment installed.

Automatic downloading or updating of vendor binaries should not be introduced without considering security, integrity verification, licensing and version compatibility.

## 6. Current Critical Issue: Stop Does Not Work Reliably

**Priority: Critical — first issue to resolve.**

The Stop button currently calls `QProcess.terminate()` and sets a `stop_requested` flag. A timeout followed by `kill()` was introduced in a later fix, but the scan and download behavior must be revalidated.

The GUI has displayed a “Stopping…” status while spotDL continued producing output. After changes intended to fix Stop, scanning/downloading also appeared to stop working correctly. The exact root cause has not been confirmed.

### Required behavior

When the user clicks Stop:

1. The GUI immediately enters a clear “Stopping…” state.
2. The application requests termination of the active spotDL worker.
3. If the worker does not exit within a reasonable timeout, the application forcibly terminates it.
4. If spotDL creates child processes, those processes are handled appropriately so work does not continue in the background.
5. The GUI remains responsive throughout the stopping process.
6. Buffered output is handled consistently; log updates must not determine whether the worker continues running.
7. The final status is **Stopped**, not **Error**, when the user requested the stop.
8. Genuine crashes and unexpected non-zero exits are still reported as errors.
9. The Start button is re-enabled and the Stop button disabled once the process has actually ended.
10. The user can start another download after a successful stop.

### Specific implementation goals

- Review `_stop_download()`.
- Review `_read_process_output()`.
- Review `_process_finished()`.
- Review `_process_error()`.
- Review `closeEvent()`.
- Ensure `stop_requested` is reset correctly before every new download.
- Prevent stale signals from an earlier process from changing the status of a newer download.
- Do not discard logs as a workaround for a process that has not actually stopped.
- Handle Windows process-tree termination correctly.

### Regression tests

- Stop during the initial playlist scan.
- Stop during active track downloads.
- Stop when spotDL is temporarily silent.
- Stop when the worker exits quickly.
- Stop when the worker does not respond to graceful termination.
- Start a new download immediately after stopping the previous one.
- Close the application while a download is running.
- Confirm that no spotDL or related child process continues working after a completed stop.

### Implementation notes (2026-10-25)

Root causes found:
- On Windows, `QProcess.terminate()` only posts `WM_CLOSE` to the process windows. The worker has none, so the request was silently ignored and spotDL kept running.
- `QProcess.kill()` only ends the worker itself; FFmpeg children (and, from source, the real interpreter started by the venv `python.exe` launcher) kept running.
- `app_fixed.py` hid the logs after Stop, which made a still-running worker look stopped.
- `QProcess.processEnvironment()` returns an **empty** environment until one is set. The worker therefore ran with only `PATH`, without `SystemRoot`, `SystemDrive`, `TEMP`, `APPDATA`, etc. A visible symptom was a literal `%SystemDrive%` folder created in the destination folder.

Current design:
- `process_control.ProcessTree` keeps a handle on the worker, enumerates all its descendants from a process snapshot (checking creation times so a reused PID is never targeted), opens them all and only then terminates the whole tree. Collecting first matters: an intermediate process can take others down with it and break the parent/child chain.
- The worker is also placed in a Job Object with `KILL_ON_JOB_CLOSE`, as a safety net if the GUI exits or crashes. On its own this is not enough: when the GUI runs inside a job that allows silent breakaway (some terminals and IDEs do), children escape nested jobs.
- On Windows there is no graceful step: Stop terminates the tree immediately. A watchdog (`STOP_TIMEOUT_MS`) forces termination again if the worker is still alive. On other platforms, `terminate()` is tried first.
- Every `QProcess` signal handler receives the process that emitted it, and ignores signals from a process that is no longer the current one.
- The worker environment starts from `QProcessEnvironment.systemEnvironment()` and sets `PYTHONUNBUFFERED=1` and `PYTHONIOENCODING=utf-8`, so output arrives live and decodes correctly.

Verified from source on Windows 11 with a fake worker (child + grandchild processes, chatty and silent phases, quick exits) and with a real spotDL run on a 194-track playlist (scan, download, Stop while FFmpeg was encoding). Not yet verified with the packaged executable.

### Partially written file after Stop

Stopping while FFmpeg is writing a track leaves a truncated audio file in the destination folder. Because the download uses `--overwrite skip`, the next run would skip this file and it would stay incomplete.

Chosen rule (implemented 2026-10-25): an audio file is considered incomplete and is deleted after a user stop when **both** conditions hold:
- it was created or modified after the download started (with a 2-second tolerance for file-system timestamps);
- it is still held open by a process when Stop is clicked, which is detected just before the worker is killed by opening the file without any sharing allowed (a sharing violation means a writer still has it open).

Files that were completed before Stop, and files that existed before the download, are never deleted. Deletion happens once the worker has exited, with a few retries because killed processes can release their files with a short delay. Each removed file is reported in the log. The same rule applies when the window is closed during a download. Audio extensions considered: `.mp3`, `.flac`, `.ogg`, `.opus`, `.m4a`, `.wav`.

Limitations:
- The open-file check is Windows-only; on other platforms nothing is deleted.
- A track whose file is not open at the exact moment of Stop (for example between the YouTube download and the start of FFmpeg) leaves no file behind, so there is nothing to clean up.

Verified with a fake worker (file kept open while writing, completed file, pre-existing file, window closed while writing) and with a real spotDL run where Stop was clicked during FFmpeg encoding.

## 7. Progress Bar and Track Counter

**Priority: High — planned feature.**

Add a visual progress bar to show how many tracks have been processed out of the total playlist size. For example, for a playlist containing 200 tracks, the interface should show a counter such as **`42 / 200 tracks`** alongside a progress bar.

### Expected behavior

- Display a progress bar in the download area, ideally near the status label and live logs.
- Show the number of completed or processed tracks and the total number of tracks, e.g. `42 / 200`.
- Update the progress bar and counter as tracks are processed.
- Show a percentage when the total is known, e.g. `21%`.
- Reset the progress display when a new download starts.
- Show an indeterminate progress state while scanning if the total is not yet known.
- Handle skipped or already-existing files consistently and clearly define whether the counter represents completed, processed, downloaded, or attempted tracks.
- When the operation completes, show the final count and 100% only if the defined progress metric has genuinely reached completion.
- When the user stops the operation, retain the last known progress and label the operation as stopped.
- If spotDL does not expose reliable structured progress data, parse its output carefully or investigate a more reliable integration. Do not invent progress values from arbitrary log lines.
- Ensure progress updates do not block the GUI or interfere with process termination.

### Acceptance criteria

For a playlist of 200 tracks:
- The interface can show progress such as `42 / 200`.
- The progress bar advances as tracks are processed.
- Scanning displays an indeterminate state until the total is known.
- Skipped tracks are represented according to the documented counting rule.
- Stop remains reliable while progress updates are being received.
- Unknown totals and parsing failures do not crash the application.

### Implementation (2026-10-25)

**Counting rule:** the counter shows **processed / total** tracks. A track is processed when it is already up to date in the destination, when it has been downloaded, or when its download failed. The number of failed tracks is shown separately, e.g. `42 / 194 tracks · 21% · 2 failed`.

**Source of the progress:** the worker reports progress itself, from the data it actually handles, instead of the GUI parsing spotDL's log lines. It writes JSON events on lines starting with `@@progress `, in a single write so logs from other threads cannot split them:
- `phase`: `fetching` (playlist), `checking` (with the total), `downloading`;
- `total`: total tracks and the number already up to date;
- `track`: one download finished, with `ok` and the track name (spotDL returns no file on failure).

The GUI removes these lines from the log view and uses them to update the bar, the counter and the status text ("Fetching playlist…", "Checking existing tracks…", "Downloading…"). Malformed events are ignored.

**Behavior:**
- The bar is indeterminate from the start until the total is known.
- After the check, it starts at the number of tracks already up to date, then advances by one for each finished download.
- On Stop, the last known progress is kept. If the worker exits before the total is known, the indeterminate animation stops at 0.
- An empty playlist shows `0 / 0 tracks · 100%`.
- At the end of a run, the names of the failed tracks are listed in the log.

Verified with a fake worker (complete run with a failure, stop, exit before the total, empty playlist, malformed event, event split across two reads) and with a real 194-track playlist.

**Blocked videos:** some YouTube results are age-restricted, and yt-dlp then fails with "Sign in to confirm your age". The restriction belongs to the video itself: music.youtube.com, youtube.com and yt-dlp's YouTube Music client all fail alike. The worker therefore uses another search result instead (see Section 9).

## 8. Light Theme and Theme Toggle

**Priority: Medium — planned feature.**

The application currently only provides a dark theme. Add a light theme that the user can switch to through a toggle, with the choice saved in the configuration file.

### Expected behavior

- Provide two themes: **Dark** (current default) and **Light**.
- Expose a toggle in the interface, for example a switch or button in the header near the status label, and/or a **View → Light theme** checkable menu action. Both must stay in sync if both exist.
- Switching theme applies immediately to the whole window, without restarting the application and without interrupting a running download.
- The light theme must cover every widget currently styled by the dark theme: window background, menus, group boxes, inputs, profile list, log view, status pill, status bar, splitter, and the Start/Stop/primary buttons (including hover, pressed and disabled states).
- Text contrast must remain readable in both themes, including the log view, hints and disabled buttons.
- Colors should be defined once per theme (for example a palette dictionary used to generate the stylesheet) rather than duplicating two full stylesheets by hand.

### Persistence

- The selected theme is stored in `config.json` under the existing `settings.theme` key, with the values `"dark"` or `"light"`.
- The choice is saved as soon as the user toggles it; it does not depend on the **Save profile** button.
- On startup, the application applies the stored theme before showing the window.
- A missing or unknown `settings.theme` value falls back to `"dark"` without raising an error.
- Existing configuration files and profiles must remain compatible.

### Acceptance criteria

- The user can switch between dark and light themes at any time, including during a download.
- After restarting the application, the last selected theme is restored.
- Deleting or corrupting the `theme` value results in the dark theme, not a crash.
- All widgets are correctly styled and readable in both themes.

### Implementation (2026-10-25)

- `THEMES` in `app.py` holds one color palette per theme; a single `STYLESHEET` template (`string.Template`) is filled with the selected palette.
- Two synchronized toggles: a sun/moon switch in the header, next to the status label (`ThemeSwitch`, drawn with QPainter: moon on the left for dark, sun on the right for light, animated knob, colors from the palette), and a **View → Theme** submenu with two exclusive checkable entries, **Light** and **Dark**.
- Scroll bars, combo box arrows and spin box buttons are styled too, so no native Windows control remains: thin rounded scroll bar handles without arrow buttons, and rounded chevrons drawn at run time in the theme color (PNG files in a temporary folder, so the build does not depend on the Qt SVG plugin).
- `_set_theme()` applies the stylesheet to the whole window and saves `settings.theme` immediately. At startup the saved theme is applied without rewriting the file. A missing or unknown value, or a `settings` entry that is not an object, falls back to dark.
- Verified from source: startup with each saved value, fallback cases, both toggles and their synchronization, saving without touching profiles, and screenshots of both themes during a download.

## 9. Worker, Track Checking and Audio Quality

The worker (`worker.py`) no longer runs spotDL's `download` command as is. It drives spotDL 4.5.2 as a library, in four phases:

1. Fetch the playlist, then complete every track's metadata with `CHECK_THREADS` (8) threads.
2. Create the spotDL downloader, which scans the destination for known tracks (`--scan-for-songs`).
3. Check every track against the destination with `CHECK_THREADS` threads (see the rules below).
4. Hand only the tracks to (re)download to spotDL, with the profile's **Download threads** and `--overwrite force`.

The profile thread count therefore only limits actual downloads, which is what triggers audio provider rate limits. Checking already downloaded tracks no longer goes one track at a time.

### Problems found in spotDL and worked around in the worker

- **YouTube Music returned no results.** spotDL creates its YouTube Music client with `language="de"`. With any non-English language (tested: `de`, `fr`), YouTube Music currently returns no search results at all, ISRC searches included, so tracks failed with "YouTube Music returned no usable results … after 3 attempts". This was not rate limiting: the same queries return results immediately in English. The worker creates the client in English.
- **Each track took about 7 seconds to look up on Spotify.** spotDL reads Spotify through `spotapi`, which creates a new web player client for every track, album and artist lookup, and each client reloads the web player, requests new tokens and downloads about 80 JavaScript files: roughly 250 HTTP requests per track. This was the real cause of the slow "scan", and with several threads it quickly gets the user's IP rate limited by Spotify (HTTP 429, observed for more than half an hour). The worker shares one web player session between clients.
- **Console windows** opened by FFmpeg are hidden (see Section 6 notes).
- **Blocked videos made tracks fail.** Some videos cannot be downloaded without a YouTube account: age-restricted, private, region-locked or members-only. When yt-dlp reports such an error, the worker records the video id and removes it from later YouTube Music search results. The track is then searched and downloaded again, up to 3 other results (`MAX_ALTERNATIVE_RESULTS`), and a `[Retry]` line is logged. spotDL also reads the view count of every close candidate through yt-dlp to break ties, so a single blocked candidate used to make the whole search fail; a blocked candidate now counts as 0 views. Bot checks and rate limits are not treated as blocked videos, because they apply to every video. Verified with "Nirvana - Come As You Are", whose first result is age-restricted, and with a fake downloader for the retry loop.

### Spotify cache between runs

Even with the shared session, one run cost about 3 Spotify web player requests per track (about 600 for a 194-track playlist) plus about 80 to load the session. A dozen full runs within an hour got the IP rate limited again (HTTP 429), which blocks every run until it lifts.

spotDL's own cache file only works with the official Spotify API, so the worker keeps its own cache in `spotify_cache.json`, next to `config.json` (beside the executable, or beside `app.py` when running from source). Like the configuration, it is lost if the build output folder is wiped:
- **Track metadata** (`Song.from_url`, used by spotDL wherever it completes a track) is stored per Spotify track id and reused for `TRACK_CACHE_DAYS` (30) days.
- **Web player query hashes** are stored with the URL of the web player's main JavaScript file, and reused until Spotify deploys a new build (the URL changes). Only the `"name","query|mutation","hash"` entries spotapi looks up are kept.
- **The playlist itself is always fetched again**, so added or removed tracks are seen.

The cache is saved after the check phase (so a stopped run keeps what it fetched) and at the end of the run. A missing or damaged file, or entries written by a spotDL version with other fields, are ignored and fetched again. Deleting the file is always safe.

These workarounds patch spotDL and spotapi internals. They must be checked again whenever spotDL, spotapi or ytmusicapi is updated.

### Audio format and bitrate

Each profile has an **Audio format** (`mp3`, `m4a`, `opus`, `ogg`, `flac`, `wav`) and a **Bitrate** (`auto`, `128k`, `160k`, `192k`, `256k`, `320k`), stored in `config.json` as `format` and `bitrate`. The defaults, also used for existing profiles, are `mp3` and `128k`: spotDL's own defaults, so existing libraries are not downloaded again unexpectedly. The bitrate is disabled for lossless formats.

- `auto` keeps the bitrate of the YouTube source, usually 128k to 160k.
- A higher bitrate makes larger files but cannot add quality that the source does not have.

### Rules for existing files

A track is downloaded again when none of its existing files (the expected file name, or a file of the selected format whose metadata points to the same Spotify track) passes all of these checks:
- the file can be read;
- its duration is at least 75% of the Spotify track duration (catches truncated files);
- for a fixed bitrate, its measured bitrate is at least 90% of the selected bitrate (65% for Opus, which is variable bitrate and was measured at 72–81% of the requested value).

Limitations:
- Only files in the selected format are checked. After a format change, tracks are downloaded in the new format and the files in the old format are left untouched.
- `auto` checks the format and duration only.
- The Opus bitrate check is approximate.

## 10. Further Potential Improvements

These are future opportunities, not requirements for the immediate Stop fix.

### Reliability
- Add a configurable timeout for graceful termination.
- Improve handling of unexpected process errors.
- Prevent duplicate download processes.
- Validate required binaries and destination paths before starting.
- Initialize the worker environment consistently, including `HOME` and `USERPROFILE`.

### User experience
- Distinguish “Scanning”, “Downloading”, “Stopping”, “Stopped”, “Completed” and “Error”.
- Add clearer diagnostic messages when a process cannot start.
- Preserve logs for troubleshooting.
- Keep the GUI responsive during large playlists.
- Consider confirmation before stopping a long-running operation, if appropriate.
- Add the track counter and progress bar described in Section 7.

### Packaging and maintenance
- Make builds reproducible with a single PowerShell build script.
- Verify the executable icon and runtime window icon separately.
- Test the onedir distribution on a clean Windows installation.
- Document how to update Python dependencies and vendor binaries.
- Keep user configuration separate from application binaries so rebuilding does not erase profiles.

## 11. Development Priorities

| Priority | Objective | Status |
|---|---|---|
| P0 | Make Stop reliably terminate the worker and relevant child processes | Fixed from source; packaged build not yet tested |
| P0 | Ensure manually stopped downloads finish with “Stopped”, not “Error” | Verified from source |
| P0 | Restore and validate normal scanning and downloading after Stop changes | Verified from source (real playlist) |
| P0 | Avoid leaving a truncated track after Stop (see Section 6) | Fixed from source; packaged build not yet tested |
| P1 | Ensure logs remain accurate and responsive during scanning, downloading and stopping | Needs verification |
| P1 | Add a progress bar and track counter (`x / total`) | Verified from source (real playlist) |
| P2 | Handle age-restricted YouTube results by using another result | Verified from source (single track) |
| P1 | Cache Spotify track metadata between runs to avoid HTTP 429 | Verified from source: 663 requests (25 s) on a cold cache, 5 (3 s) on the next run |
| P1 | Fix "no usable results" from YouTube Music (Section 9) | Verified from source (real playlist) |
| P1 | Check existing tracks with more threads than downloads (Section 9) | Verified from source: 194 tracks checked in about 25 s |
| P1 | Choose format and bitrate per profile; re-download non-matching files (Section 9) | Verified from source (128k to 320k re-download) |
| P1 | Verify restart behavior after stopping a download | Verified from source |
| P1 | Verify runtime icon and executable icon independently | Window icon now appears to work |
| P2 | Add a light theme with a toggle, persisted in `settings.theme` | Done: sun/moon switch and View → Theme (Light / Dark), saved on toggle, all controls themed, verified from source |
| P2 | Improve vendor dependency validation and version documentation | Done: Python packages pinned in requirements.txt; vendor executables pinned in vendor.json (URL and SHA-256 of archive, executables and licenses) and downloaded by fetch_vendor.ps1, verified from an empty folder |
| P2 | Create a repeatable build and regression-testing procedure | Done: build.ps1 (version, vendor and package checks, tests, keeps user files, licenses, packaged self-check, `-Package` archive) and tests\ (46 tests, about 35 s, no network: `python -m unittest discover -s tests`). Real downloads are still checked by hand |
| P2 | Versioning: single version in version.py, shown in the window title, Help → About and the executable's file properties; CHANGELOG.md checked by build.ps1 | Done, verified from source and on a build from scratch |
| P2 | Licensing: MIT LICENSE for the project; THIRD_PARTY_NOTICES.md and license texts (FFmpeg GPL-3.0, Deno, 76 Python packages) shipped next to the executable | Done |
| P2 | Publish the release archive on GitHub (.github/workflows/release.yml: tag vX.Y.Z builds, checks and publishes a Release) | Written and checked locally (build from scratch, release notes extraction); not yet run on GitHub |

## 12. Definition of Done

The immediate Stop task is complete only when:
- Stop reliably terminates the active operation on Windows.
- No background download processes remain after a completed stop.
- The GUI displays the correct final state.
- Logs do not misleadingly suggest that a stopped download is still progressing.
- Normal playlist scanning and downloading still work.
- A new download can start after a previous download is stopped.
- The packaged application behaves consistently with the development version.

The progress feature is complete when:
- The GUI shows a track counter and progress bar when reliable progress information is available.
- The display handles unknown totals during scanning.
- Skipped tracks follow a documented counting rule.
- Progress updates remain responsive and do not interfere with Stop.

The theme feature is complete when:
- A toggle switches between dark and light themes immediately.
- The selected theme is persisted in `config.json` (`settings.theme`) and restored on startup.
- Invalid or missing theme values fall back to dark.

**Immediate focus:** fix and test Stop without breaking the normal scan/download workflow. Then implement the progress bar and track counter. Vendor automation and broader enhancements remain secondary until the core behavior is stable.
