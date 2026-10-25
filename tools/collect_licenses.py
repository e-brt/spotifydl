"""Copy the license files of every package pinned in requirements.txt.

Usage: python tools/collect_licenses.py <requirements.txt> <target folder>

For each package, the license files shipped in its .dist-info folder
(LICENSE, COPYING, NOTICE, AUTHORS...) are copied to
<target>/<name>-<version>/. A summary, SUMMARY.txt, lists every package with
its declared license, so packages without a license file are still listed.
Used by build.ps1 so that the release archive carries these licenses.
"""

import re
import shutil
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice|authors)", re.IGNORECASE)
# Development tools pinned in requirements.txt but not part of the build.
NOT_BUNDLED = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile"}


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_license(dist):
    meta = dist.metadata
    value = meta.get("License-Expression") or meta.get("License") or ""
    if value and len(value) < 80:
        return value
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    return ", ".join(classifiers) or "see license files"


def main(requirements, target):
    target = Path(target)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    summary = []
    missing = []
    for line in Path(requirements).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name, version = line.split("==")
        if normalize(name) in NOT_BUNDLED:
            continue
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            missing.append(name)
            continue
        folder = target / f"{normalize(dist.metadata['Name'])}-{dist.version}"
        copied = 0
        for file in dist.files or []:
            in_dist_info = file.parts and file.parts[0].endswith(".dist-info")
            if in_dist_info and LICENSE_FILE.match(file.name):
                destination = folder / Path(*file.parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file.locate(), destination)
                copied += 1
        summary.append(f"{dist.metadata['Name']} {dist.version}: {declared_license(dist)}"
                       + ("" if copied else "  (no license file shipped)"))
    (target / "SUMMARY.txt").write_text(
        "Python packages bundled in the application, with their declared license.\n\n"
        + "\n".join(sorted(summary, key=str.lower)) + "\n",
        encoding="utf-8",
    )
    if missing:
        print("Not installed: " + ", ".join(missing))
        return 1
    print(f"Collected licenses of {len(summary)} packages in {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
