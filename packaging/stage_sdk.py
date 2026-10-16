"""Build the language modules into the app's sdk/ folder, one subfolder per language.

    python packaging/stage_sdk.py --dest <dist>/LBDViewer/sdk [--skip ID ...]

For every languages/<id>/language.toml, [sdk] says what goes into sdk/<id>/:
    build          command that writes into {dest} (e.g. a wheel, a .mltbx)
    fallback_copy  files copied instead when the build tool is missing or --skip <id> is given
    copy           files always copied
language.toml, LICENSE, the example file and README.md are always copied, so the installed viewer can
show install instructions for every language.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--skip", nargs="*", default=[], metavar="ID",
                    help="don't run the build step of these languages; use fallback_copy")
    args = ap.parse_args(argv)
    try:
        version = release_version()
    except VersionError as e:
        raise SystemExit(f"{e}\nSet one version everywhere before building (see scripts/check_versions.py).")
    langs = discover()
    unknown = set(args.skip) - {lang.id for lang in langs}
    if unknown:
        raise SystemExit(f"--skip: unknown language id(s) {sorted(unknown)}; known: {[lang.id for lang in langs]}")

    dest: Path = args.dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for lang in langs:
        sdk = lang.section("sdk")
        out = dest / lang.id
        out.mkdir()
        if sdk.get("build"):
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
