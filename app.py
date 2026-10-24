import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse


APP_NAME = "Spotify Playlist Downloader"


def resource_path(*parts):
    base = Path(
        getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    )
    return base.joinpath(*parts)


def ask_playlist_url():
    while True:
        url = input("\nSpotify playlist URL: ").strip()

        try:
            parsed = urlparse(url)

            if parsed.scheme == "https" and parsed.hostname in (
                "open.spotify.com",
                "spotify.link",
            ):
                return url

        except ValueError:
            pass

        print("Invalid Spotify URL. Please try again.")


def ask_destination():
    while True:
        raw = input("\nDestination folder: ").strip().strip('"')

        if not raw:
            print("The path cannot be empty.")
            continue

        try:
            destination = Path(raw).expanduser().resolve()
            destination.mkdir(parents=True, exist_ok=True)
            return destination
        except (OSError, ValueError) as exc:
            print(f"Unable to access the folder: {exc}")


def main():
    os.system("cls" if os.name == "nt" else "clear")

    print("=" * 54)
    print(f"  {APP_NAME}")
    print("=" * 54)

    url = ask_playlist_url()
    destination = ask_destination()

    vendor = resource_path("vendor")
    deno = vendor / "deno.exe"
    ffmpeg = vendor / "ffmpeg.exe"
    ffprobe = vendor / "ffprobe.exe"

    # Make the bundled executables accessible to the dependencies.
    env = os.environ.copy()
    env["PATH"] = str(vendor) + os.pathsep + env.get("PATH", "")

    print("\nChecking dependencies:")
    for name, path in (
        ("Deno", deno),
        ("FFmpeg", ffmpeg),
        ("FFprobe", ffprobe),
    ):
        print(f"  {name}: {'OK' if path.is_file() else 'MISSING'}")

    if not ffmpeg.is_file():
        print("\nERROR: ffmpeg.exe is missing from the vendor folder.")
        input("\nPress Enter to exit...")
        return

    if not deno.is_file():
        print("\nWARNING: deno.exe is missing from the vendor folder.")

    # spotDL is called directly through the Python libraries
    # bundled by PyInstaller, rather than through spotdl.exe.
    try:
        os.environ.update(env)
        os.chdir(destination)

        sys.argv = [
            "spotdl",
        #   "--log-level", "DEBUG",
            "--overwrite", "skip",
            "--scan-for-songs",
            "--threads", "3",
            "download",
            url,
        ]

        from spotdl.console.entry_point import console_entry_point

        print(f"\nDestination: {destination}")
        print("\nStarting spotDL...\n")

        console_entry_point()

    except KeyboardInterrupt:
        print("\nDownload interrupted.")

    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(f"\nspotDL exited with code: {exc.code}")

    except Exception:
        print("\nAn error occurred:")
        traceback.print_exc()

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
