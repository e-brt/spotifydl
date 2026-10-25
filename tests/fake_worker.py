"""Stands in for the spotDL worker in the GUI tests.

Started by the tests instead of `app.py --spotdl-worker`, in the profile's
destination folder. The first argument selects a scenario:

Process handling (Stop, Close):
- chatty: logs continuously; starts a child that starts a grandchild, like
  spotDL starting FFmpeg.
- silent: same processes, but no output after startup.
- writer: writes "Done Song.mp3", then keeps "Partial Song.mp3" open and growing.
- quick-ok / quick-fail: exits at once with code 0 / 2.

Progress events (see worker.emit):
- full: 10 tracks, 6 up to date, then 4 downloads, one of them failed.
- progress-stop: like full, but hangs before the third download.
- early-exit: exits with code 3 before reporting the total.
- empty: a playlist with no tracks.
- split: one event is written in two parts.
"""

import json
import subprocess
import sys
import time

PREFIX = "@@progress "
mode = sys.argv[1]


def emit(event, **data):
    sys.stdout.write(PREFIX + json.dumps({"event": event, **data}) + "\n")
    sys.stdout.flush()


def run_processes():
    child_code = (
        "import subprocess,sys,time;"
        "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(600)']);"
        "print('GRANDCHILD', g.pid, flush=True);"
        "time.sleep(600)"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code])
    print("CHILD", child.pid, flush=True)
    print("Scanning for known songs, this might take a while...", flush=True)
    partial = None
    if mode == "writer":
        with open("Done Song.mp3", "wb") as done:
            done.write(b"complete")
        partial = open("Partial Song.mp3", "wb")
        print("WRITING", flush=True)
    index = 0
    while True:
        if partial:
            partial.write(b"x" * 1024)
            partial.flush()
        if mode == "chatty":
            print(f"Downloaded track {index} é ü ✓", flush=True)
            index += 1
        time.sleep(0.2)


def run_progress():
    print("log line before", flush=True)
    emit("phase", phase="fetching")
    time.sleep(0.2)
    if mode == "early-exit":
        sys.exit(3)
    total = 0 if mode == "empty" else 10
    emit("phase", phase="checking", total=total)
    time.sleep(0.2)
    sys.stdout.write(PREFIX + "{not json\n")
    sys.stdout.flush()
    emit("total", total=total, done=0 if mode == "empty" else 6)
    if mode == "empty":
        sys.exit(0)
    emit("phase", phase="downloading")
    if mode == "split":
        sys.stdout.write(PREFIX + '{"event": "tr')
        sys.stdout.flush()
        time.sleep(0.3)
        sys.stdout.write('ack", "ok": true, "name": "x"}\n')
        sys.stdout.flush()
    for index, ok in enumerate([True, False, True, True]):
        if mode == "progress-stop" and index == 2:
            time.sleep(600)
        time.sleep(0.15)
        print(f'Downloaded "Track {index}"', flush=True)
        emit("track", ok=ok, name=f"Track {index}")


if mode == "quick-ok":
    print("done quickly")
    sys.exit(0)
if mode == "quick-fail":
    print("failing quickly")
    sys.exit(2)
if mode in ("chatty", "silent", "writer"):
    run_processes()
else:
    run_progress()
