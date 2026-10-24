# Spotify Playlist Downloader

A Windows desktop/console application for downloading songs from Spotify playlists using [spotDL](https://github.com/spotDL/spotify-downloader).

The application is built with Python and can be packaged into a standalone Windows executable with PyInstaller. It uses bundled versions of Deno, FFmpeg, and FFprobe.

> **Note:** This project downloads audio from sources supported by spotDL; Spotify itself does not provide downloadable audio files through this application. Use it only for content you are authorized to download and in accordance with the relevant services' terms.

## Features

- Enter a Spotify playlist URL.
- Choose a destination folder for downloaded tracks.
- Use spotDL to find and download matching audio.
- Package the Python application and its dependencies into a single executable.
- Bundle Deno, FFmpeg, and FFprobe with the application.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or another Python version supported by the project's dependencies
- `pip` and Python's `venv` module
- The Deno, FFmpeg, and FFprobe Windows executables
- An internet connection

## Project layout

The project should have a structure similar to this:

```text
spotifydl/
├── app.py
├── vendor/
│   ├── deno.exe
│   ├── ffmpeg.exe
│   └── ffprobe.exe
└── README.md
```

PyInstaller will generate the build output, including `build/`, `dist/`, and a `.spec` file.

## 1. Install Python

Install Python for Windows from [python.org](https://www.python.org/downloads/windows/).

During installation, enable **Add Python to PATH** if that option is available.

Open PowerShell or Command Prompt and check that Python is available:

```powershell
python --version
python -m pip --version
```

If the `python` command is not recognized, reinstall Python or correct your PATH configuration.

## 2. Open the project directory

In PowerShell, navigate to the project folder. For example:

```powershell
cd D:\Documents\spotifydl
```

Run the following commands from this directory unless stated otherwise.

## 3. Create and activate a virtual environment

Create a virtual environment named `.venv`:

```powershell
python -m venv .venv
```

Activate it in **PowerShell**:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, you can allow scripts for the current PowerShell process only, then activate the environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Alternatively, in **Command Prompt (`cmd.exe`)**, activate it with:

```bat
.venv\Scripts\activate.bat
```

When activation succeeds, `(.venv)` should appear at the start of your terminal prompt.

Upgrade the packaging tools:

```powershell
python -m pip install --upgrade pip setuptools wheel
```

## 4. Install the Python dependencies

Install the application's dependencies into the active virtual environment.

If the project has a `requirements.txt` file, use:

```powershell
python -m pip install -r requirements.txt
```

If it does not have one yet, install the packages used by the current PyInstaller build:

```powershell
python -m pip install pyinstaller spotdl yt-dlp syncedlyrics pykakasi ytmusicapi babel
```

For reproducible builds, keep a tested `requirements.txt` with the versions that work with the project. You can create or update it from the active environment with:

```powershell
python -m pip freeze > requirements.txt
```

Review the generated file before committing it, since it records all packages installed in the environment.

## 5. Prepare the bundled executables

Before building the application, download the required Windows executables and place them in the `vendor/` directory at the root of the project.

- **Deno:** Download the Windows x64 installer or binary from the [official Deno website](https://deno.com/).
- **FFmpeg and FFprobe:** Download a Windows build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or another trusted FFmpeg build provider. Extract the downloaded archive and locate `ffmpeg.exe` and `ffprobe.exe` inside its `bin/` directory.

Your project directory should contain the following files:

```text
vendor/
├── deno.exe
├── ffmpeg.exe
└── ffprobe.exe
```

Make sure the filenames match exactly. These executables are required by the PyInstaller build command and must be present before compiling the application. Check the respective projects' license terms before redistributing these binaries.

## 6. Run the application from source

With the virtual environment activated, run:

```powershell
python app.py
```

Test the playlist URL, destination-folder selection, and download workflow before creating a release build.

## 7. Build the Windows executable

From the project root, with `.venv` activated, run:

```powershell
python -m PyInstaller --clean --noconfirm --onefile --console --name SpotifyDownloader --collect-all spotdl --collect-all yt_dlp --collect-all syncedlyrics --collect-all pykakasi --collect-all ytmusicapi --collect-all babel --add-binary "vendor\deno.exe;vendor" --add-binary "vendor\ffmpeg.exe;vendor" --add-binary "vendor\ffprobe.exe;vendor" app.py
```

### What the command does

- `--clean`: clears cached build data before building.
- `--noconfirm`: overwrites existing build output without asking.
- `--onefile`: packages the application into one executable.
- `--console`: keeps the console visible, which is useful for logs and debugging.
- `--name SpotifyDownloader`: names the output executable `SpotifyDownloader.exe`.
- `--collect-all ...`: collects package data, submodules, and binaries for the listed dependencies.
- `--add-binary ...`: bundles Deno, FFmpeg, and FFprobe and places them in the `vendor` directory inside the packaged application.

### Build output

After a successful build, the executable should be located at:

```text
dist\SpotifyDownloader.exe
```

Run it from PowerShell to see diagnostic output:

```powershell
.\dist\SpotifyDownloader.exe
```

Keep the console enabled when troubleshooting download or dependency errors.

## 8. Troubleshooting

### `ModuleNotFoundError` or missing package data

Make sure the virtual environment is activated and that the dependencies were installed into that same environment. Then run the PyInstaller command again.

### Missing Deno, FFmpeg, or FFprobe

Check that all three files exist under `vendor\` and that their filenames match the command exactly. Confirm that `app.py` resolves bundled paths correctly when running as a PyInstaller executable.

### YouTube rate limiting or HTTP 403 errors

These errors can originate from the external audio source or its download tooling, and are not necessarily PyInstaller build errors. Avoid repeatedly retrying in quick succession. Wait and retry later, and consider reducing spotDL's download concurrency. Keep spotDL and its related dependencies compatible with one another.

### Lyrics provider errors

Errors from lyrics providers may be independent of audio downloading. Check the full log to determine whether the audio download itself failed.

### Test the packaged executable

After each build, test the executable with a small playlist before using a large playlist. Confirm that the selected destination folder is writable and that the bundled tools can be found.

## 9. Deactivate the virtual environment

When you are finished working:

```powershell
deactivate
```

Activate it again whenever you return to development:

```powershell
cd D:\Documents\spotifydl
.\.venv\Scripts\Activate.ps1
```

## License and Third-Party Notices

### Project License

The license for this project has not yet been specified. Unless a license is added to this repository, no permission is granted to redistribute, modify, or reuse the project's source code beyond what is permitted by applicable law.

### Third-Party Software

This project relies on third-party software and Python packages, including:

- **[spotDL](https://github.com/spotDL/spotify-downloader)** — Spotify playlist and track metadata processing and audio downloading.
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — media extraction and downloading.
- **[SyncedLyrics](https://github.com/moehmeni/syncedlyrics)** — lyrics retrieval.
- **[pykakasi](https://github.com/miurahr/pykakasi)** — Japanese text conversion.
- **[ytmusicapi](https://github.com/sigma67/ytmusicapi)** — interaction with YouTube Music.
- **[Babel](https://babel.pocoo.org/)** — internationalization and localization utilities.
- **[PyInstaller](https://pyinstaller.org/)** — packaging the Python application into an executable.
- **[Deno](https://deno.com/)** — JavaScript and TypeScript runtime.
- **[FFmpeg](https://ffmpeg.org/)** — audio and multimedia processing.
- **[FFprobe](https://ffmpeg.org/ffprobe.html)** — multimedia stream and file inspection.

Each third-party component is distributed under its own license and may have additional notices or redistribution requirements. Please consult the official project pages and license files for the applicable terms.

### Redistribution

Before distributing this application or its bundled executable, verify the licenses and redistribution requirements of every included dependency and binary. Include any required copyright notices, license texts, and third-party acknowledgements.

In particular, review the licensing and build configuration of FFmpeg, as redistribution obligations may depend on how the binary was built and which codecs or libraries it includes.

### Use of External Services

This application may interact with Spotify, YouTube, YouTube Music, and third-party lyrics providers. These services have their own terms of service and usage restrictions. Users are responsible for complying with those terms and for ensuring that they have the necessary rights to download or use any content.

This project is not affiliated with, endorsed by, or officially associated with Spotify, YouTube, YouTube Music, or the third-party software projects listed above.