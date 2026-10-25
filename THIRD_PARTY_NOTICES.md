# Third-party notices

Spotify Playlist Downloader is released under the MIT License (see `LICENSE`).
The packaged application also contains the software below, which keeps its own
license. The full license texts are in the `licenses` folder next to the
executable.

## Executables in `_internal\vendor`

These are separate programs that the application starts; they are not linked
with it. Exact versions, download URLs and SHA-256 hashes are in `vendor.json`
in the source repository.

| Program | Version | License | License text | Source |
|---|---|---|---|---|
| FFmpeg and FFprobe (essentials build by gyan.dev) | 2026-10-22-git-bf0e831606 | GNU GPL version 3 | `licenses\ffmpeg\LICENSE.txt` | see below |
| Deno | 2.9.8 | MIT | `licenses\deno\LICENSE.md` | https://github.com/denoland/deno/tree/v2.9.8 |

### FFmpeg source code

The bundled FFmpeg build is distributed under the GNU General Public License
version 3. Its complete corresponding source code is available from:

- the build used: https://github.com/GyanD/codexffmpeg/releases/tag/2026-10-22-git-bf0e831606
  (built by gyan.dev, https://www.gyan.dev/ffmpeg/builds/, which lists the
  sources of every library included in the build);
- FFmpeg itself, at commit `bf0e831606`: https://git.ffmpeg.org/ffmpeg.git

You may also request a copy of this source code by opening an issue on this
project's GitHub repository, for at least three years after the release that
included it.

## Python packages

The application is built with PyInstaller and contains the Python packages
pinned in `requirements.txt`. The main ones are:

| Package | License |
|---|---|
| spotDL | MIT |
| yt-dlp | Unlicense |
| ytmusicapi | MIT |
| spotapi, SpotipyFree | see their license files |
| Qt for Python (PySide6, shiboken6) | LGPL-3.0 (or GPL-2.0 / GPL-3.0) |

`licenses\python\SUMMARY.txt` lists every bundled package with its declared
license, and `licenses\python\<package>-<version>\` contains the license files
each package ships.

### Qt for Python (LGPL-3.0)

Qt and Qt for Python are used under the GNU Lesser General Public License
version 3. They are shipped as separate dynamic libraries in the `_internal`
folder and are not modified, so they can be replaced with compatible versions
built by the user. Their source code is available from https://code.qt.io/ and
https://pypi.org/project/PySide6/#files.

## Responsible use

Users are responsible for complying with the terms of Spotify, YouTube and any
other source used, and for downloading only content they are authorized to
access.
