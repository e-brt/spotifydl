# Spotify Playlist Downloader

A Windows GUI for managing saved Spotify playlist profiles and downloading tracks through [spotDL](https://github.com/spotDL/spotify-downloader).

## Features

- Save multiple playlist profiles, each with a Spotify URL, destination folder, and thread count.
- Create, duplicate, edit, and delete profiles.
- Store configuration persistently in the current user's application-data directory.
- View spotDL output live in the application.
- Start and stop the spotDL worker process.
- Skip existing files and scan the destination for songs when running spotDL.
- Dark interface built with PySide6.

## Requirements

- Windows 10 or Windows 11
- Python 3.10+ compatible with the selected spotDL release
- Deno, FFmpeg, and FFprobe Windows executables

## Prepare the vendor directory

Create a `vendor` directory next to `app.py` and place these files in it:

```text
vendor/
├── deno.exe
├── ffmpeg.exe
└── ffprobe.exe
```

Download Deno from the [official Deno website](https://deno.com/). Download FFmpeg and FFprobe from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or another trusted Windows build provider. Extract the FFmpeg archive and copy `ffmpeg.exe` and `ffprobe.exe` from its `bin` directory into `vendor/`. Review the applicable licenses and redistribution requirements before distributing these binaries.

## Create a virtual environment on Windows

Open PowerShell in the project directory:

```powershell
cd D:\Documents\spotifydl
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation scripts, allow them for the current terminal process only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

In Command Prompt, use `.venv\Scripts\activate.bat` instead.

## Run from source

```powershell
python app.py
```

## Configuration location

The application stores `config.json` next to the executable when running as a packaged application, or next to `app.py` when running from source.

Make sure the application folder is writable. If it is installed under a protected location such as `C:\Program Files`, Windows may prevent saving the configuration. Prefer a user-writable folder, such as a folder under Documents.

Use **File → Show configuration location** in the app to display the full path. Back up `config.json` to preserve your saved profiles.

## Build a Windows executable

Activate the virtual environment, ensure the three files are present in `vendor/`, and run:

```powershell
python -m PyInstaller --clean --noconfirm --windowed --icon "assets\spotifydownloader.ico" --name SpotifyDownloader --collect-all spotdl --collect-all yt_dlp --collect-all syncedlyrics --collect-all pykakasi --collect-all ytmusicapi --collect-all babel --add-binary "vendor\deno.exe;vendor" --add-binary "vendor\ffmpeg.exe;vendor" --add-binary "vendor\ffprobe.exe;vendor" --add-data "assets\spotifydownloader.ico;assets" app.py
```

The executable is created at:

```text
dist\SpotifyDownloader.exe
```

The GUI uses a child process to run spotDL and capture its output. The child process re-launches the packaged executable in worker mode, so do not remove the worker dispatch in `app.py`.

## Troubleshooting

- **Missing FFmpeg:** check that `vendor\ffmpeg.exe` exists and that the filename is exact.
- **Missing Deno:** check `vendor\deno.exe`. Some spotDL features may require it.
- **YouTube HTTP 403 or rate limiting:** these are external-source or extractor errors rather than necessarily build errors. Wait before retrying and consider using fewer threads.
- **Profiles missing after an update:** check `%APPDATA%\SpotifyPlaylistDownloader\config.json`.
- **Worker fails to start:** test with `python app.py` first and inspect the displayed logs.

## Licensing and responsible use

spotDL, FFmpeg, FFprobe, Deno, and the Python dependencies have their own licenses and redistribution conditions. Check the official license files before distributing the application or bundled binaries. Users are responsible for complying with the terms of Spotify and any audio source used, and for downloading only content they are authorized to access.
