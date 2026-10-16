"""Build the language modules into the app's sdk/ folder, one subfolder per language.

    python packaging/stage_sdk.py --dest <dist>/LBDViewer/sdk [--skip ID ...] [--prebuilt ID=DIR ...]

For every languages/<id>/language.toml, [sdk] says what goes into sdk/<id>/:
    build          command that writes into {dest} (e.g. a wheel, a .mltbx)
    fallback_copy  files copied instead when the build tool is missing or --skip <id> is given
    copy           files always copied
--prebuilt ID=DIR uses the files in DIR instead of running that language's build: GitHub's
release workflow builds LBD.mltbx in a MATLAB job and hands it to the Windows and Linux builds.
language.toml, LICENSE, the example file and README.md are always copied, so the installed viewer
can show install instructions for every language.
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict

ROOT =Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_versions import VersionError, release_version  # noqa: E402
from languages import discover  # noqa: E402


def copy_items(lang, names, dest: Path) -> None:
    for name in names:
        src = lang.dir / name
        if src.is_dir():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
        elif src.is_file():
            shutil.copy2(src, dest / name)
        else:
            raise SystemExit(f"{lang.id}: '{name}' listed in language.toml does not exist")


def parse_prebuilt(items, known) -> Dict[str, Path]:
    """--prebuilt ID=DIR values -> {id: folder}; every id must exist and every folder hold files."""
    result = {}
    for item in items:
        lang_id, sep, folder = item.partition("=")
        if not sep or not folder:
            raise SystemExit(f"--prebuilt {item!r}: write ID=DIR, e.g. matlab=build/mltbx")
        if lang_id not in known:
            raise SystemExit(f"--prebuilt: unknown language id {lang_id!r}; known: {known}")
        path = Path(folder)
        if not path.is_dir() or not any(path.iterdir()):
            raise SystemExit(f"--prebuilt {lang_id}: {path} is missing or empty")
        result[lang_id] = path
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--skip", nargs="*", default=[], metavar="ID",
                    help="don't run the build step of these languages; use fallback_copy")
    ap.add_argument("--prebuilt", nargs="*", default=[], metavar="ID=DIR",
                    help="use the files in DIR instead of running that language's build step")
    args = ap.parse_args(argv)
    try:
        version = release_version()
    except VersionError as e:
        raise SystemExit(f"{e}\nSet one version everywhere before building (see scripts/check_versions.py).")
    langs = discover()
    known = [lang.id for lang in langs]
    unknown = set(args.skip) - set(known)
    if unknown:
        raise SystemExit(f"--skip: unknown language id(s) {sorted(unknown)}; known: {known}")
    prebuilt = parse_prebuilt(args.prebuilt, known)
    both = set(args.skip) & set(prebuilt)
    if both:
        raise SystemExit(f"{sorted(both)}: given in both --skip and --prebuilt; choose one")

    dest: Path = args.dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for lang in langs:
        sdk = lang.section("sdk")
        out = dest / lang.id
        out.mkdir()
        if lang.id in prebuilt:
            print(f"{lang.name}: using the prebuilt files in {prebuilt[lang.id]}")
            for item in prebuilt[lang.id].iterdir():
                (shutil.copytree if item.is_dir() else shutil.copy2)(item, out / item.name)
        elif sdk.get("build"):
            missing = lang.missing_tool("sdk")
            if lang.id in args.skip or missing:
                why = "skipped" if lang.id in args.skip else f"{missing} not on PATH"
                if not sdk.get("fallback_copy"):
                    raise SystemExit(f"{lang.name}: can't build the SDK ({why}) and there is no fallback_copy")
                print(f"{lang.name}: {why}; copying {sdk['fallback_copy']} instead")
                copy_items(lang, sdk["fallback_copy"], out)
            else:
                print(f"{lang.name}: building")
                r = lang.run(sdk["build"], capture=False, dest=out, version=version)
                if r.returncode != 0:
                    raise SystemExit(f"{lang.name}: SDK build failed (exit code {r.returncode})")
                (out / ".gitignore").unlink(missing_ok=True)  # uv build drops one into its output folder
        copy_items(lang, sdk.get("copy", []), out)
        extras = ["language.toml", "LICENSE"] + [n for n in (lang.data.get("example"), "README.md") if n]
        copy_items(lang, [n for n in extras if (lang.dir / n).exists()], out)
        print(f"{lang.name}: {sorted(p.name for p in out.iterdir())}")

    shutil.copy2(ROOT / "spec" / "LBD-v1.md", dest / "LBD-v1.md")
    shutil.copy2(ROOT / "LICENSE", dest / "LICENSE")
    (dest / "README.txt").write_text(
        f"LBD language modules, version {version}\n\n"
        "Open LBD Viewer > Language modules for install instructions.\n"
        "File format: LBD-v1.md\n",
        encoding="utf-8",
    )
    print(f"SDK staged in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
