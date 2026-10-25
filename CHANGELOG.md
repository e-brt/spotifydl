# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/). The
version itself is defined in `src/version.py`; `build.ps1` refuses to build a
version that has no section here.

## [Unreleased]

### Added
- A `.m3u8` playlist file is written in the destination folder after each
  run, with the tracks in the playlist order.
- After a complete run, files of tracks no longer in the playlist can be moved
  to the Recycle Bin, after confirmation.

### Changed
- The code is in `src\`; run it from source with `python src\main.py`.

## [1.0.0] - 2026-10-25

First release.

### Added
- Playlist profiles: name, Spotify playlist URL, destination folder, audio
  format (mp3, m4a, opus, ogg, flac, wav), bitrate (auto, 128k to 320k) and
  number of download threads; create, duplicate, edit and delete.
- Live spotDL output in the window, with a progress bar and a
  `processed / total tracks` counter, and the list of failed tracks at the end.
- Existing files are checked before downloading: unreadable, truncated or
  lower-bitrate files are downloaded again. The check uses more threads than
  the downloads.
- Tracks whose YouTube video is age restricted, private or region locked are
  downloaded from another search result.
- Spotify track data is cached next to the configuration, so that repeated runs
  on the same playlist make almost no Spotify requests.
- Light and dark themes
- `build.ps1` to build the executable (checks the vendor binaries and Python
  packages, runs the tests, keeps the configuration and cache, checks the
  result), `fetch_vendor.ps1` to download pinned and verified FFmpeg and Deno
  builds, and a test suite in `tests\`.

### Fixed
- Stop now ends the whole spotDL process tree on Windows, including FFmpeg, and
  removes the track that was being written.
- YouTube Music searches no longer return "no usable results" for every track
  (spotDL's YouTube Music client is created in English).
- Spotify lookups take about 1 second per track instead of 7, and no longer
  get the IP rate limited.
- No console window opens for FFmpeg in the packaged application.
- The worker now runs with the full system environment.
