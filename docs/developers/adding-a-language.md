# Adding a language

Each folder here is one language module for reading and writing `.lbd` files:

| Folder | Module | Users install |
|---|---|---|
| `languages/python/` | `lbd` package | a wheel, `pip install` |
| `languages/matlab/` | `+lbd` package | `LBD.mltbx` |
| `languages/julia/` | `LBD` package | `Pkg.develop` |

Every language folder has the same shape and a manifest, `language.toml`. The repository's
tools read the manifests, so **adding a language means adding a folder**. Nothing else in the
repository needs to change. These tools read them:

- the unit-test runner (`scripts/test_all.py`)
- the cross-language round trip (`tests/crosslang/run_all.py`)
- the version check (`scripts/check_versions.py`)
- the installer's SDK packaging (`packaging/stage_sdk.py`)
- the viewer's **Language modules** page

## Folder layout

```
languages/<id>/
  language.toml      manifest (see below)
  README.md          short intro; copied into the installed viewer's sdk/<id>/
  example.<ext>      example shown on the Language modules page
  crosslang/         fixture writer and checker for the cross-language round trip
  ...                the module's own sources and tests, in whatever layout the language expects
```

Folders whose names start with `_` (like `languages/_template/`) are ignored.

## Steps

1. **Copy the template:** `cp -r languages/_template languages/<id>`. The `id` is lower case
   and must equal the folder name.
2. **Implement the format** following the [file format specification](../format.md). Mirror the existing
   API so the docs read the same in every language:
   - `Dataset`, `add_axis`, `add_value`, `save`, `load`, `info`, `version`;
   - errors for invalid names, shapes, unknown files, and newer major versions.

   Pay particular attention to:
   - **Dimension order** (spec §2). Column-major languages reverse the dimensions when writing
     and reading, so the logical shape matches Python.
   - **Complex numbers**: an HDF5 compound with members `r`, `i`.
   - **Booleans**: `uint8` plus the attribute `lbd_bool = 1`.
   - **Strings**: variable-length UTF-8.
3. **Write unit tests** in the language's usual framework.
4. **Write the cross-language scripts** in `crosslang/`, following
   the [cross-language fixture](testing.md#cross-language-fixture):
   - `write`: create `<out>/fixture.lbd` with exactly the fixture content;
   - `check`: read **every** `<root>/*/fixture.lbd`, compare it with the fixture definition,
     print one line per file, and exit non-zero on any mismatch.

   The existing scripts in `python/crosslang/` are the reference.
5. **Write `example.<ext>`**, the same example as the other languages, and `README.md`.
6. **Fill in `language.toml`**, using the reference below.
7. **Check:**
   ```bash
   uv run python scripts/languages.py          # is it discovered, and is its manifest valid?
   uv run python scripts/check_versions.py     # same release version as the others?
   uv run python scripts/test_all.py           # its unit tests and the N x N cross-language matrix
   ```
8. **Document the API** in `docs/<id>.md`, following the MATLAB and Julia pages. Add it to
   the navigation in `mkdocs.yml`.

## `language.toml` reference

```toml
id = "python"              # required; equals the folder name
name = "Python"            # required; display name
order = 1                  # sort order (tabs, test runs); default 100
requirements = "..."       # shown on the Language modules page
example = "example.py"     # example file (must exist)
check = "python -c ..."    # command users run to check the install
notes = ["..."]            # extra remarks for users
```

### `[[version]]` and `[format_version]`

```toml
[[version]]                # one entry per place the release version is written
file = "pyproject.toml"    # relative to the language folder
pattern = '^version\s*=\s*"([^"]+)"'   # regex, multiline; group 1 is the version

[format_version]           # which LBD format version the module implements
file = "src/lbd/io.py"
pattern = '^FORMAT_VERSION\s*=\s*"([^"]+)"'
```

`scripts/check_versions.py` requires:
- every `[[version]]` to equal the viewer's version;
- every `[format_version]` to equal the version in the spec.

### `[test]`, `[crosslang]`, `[sdk]`

```toml
[test]
requires = "julia"         # optional: program that must be on PATH, else the suite is skipped
command = ["julia", "--project=.", "-e", "using Pkg; Pkg.test()"]

[crosslang]
requires = "julia"
write = ["julia", "--project=.", "crosslang/write.jl", "{out}"]
check = ["julia", "--project=.", "crosslang/check.jl", "{root}"]

[sdk]
requires = "matlab"        # needed by `build`
build = ["matlab", "-batch", "..."]    # writes the module's files into {dest}
fallback_copy = ["+lbd"]   # copied instead of building when `requires` is missing or --skip <id>
copy = ["src", "README.md"]            # always copied
```

Commands are argument lists and run with the language folder as the working directory. The
first element is looked up on `PATH`. These placeholders are replaced:

| Placeholder | Value | Also in env var |
|---|---|---|
| `{python}` | the Python running the tool | `LBD_PYTHON` |
| `{repo}` | repository root | `LBD_REPO` |
| `{lang_dir}` | this language folder | `LBD_LANG_DIR` |
| `{out}` | `[crosslang].write`: folder to write `fixture.lbd` into | `LBD_OUT` |
| `{root}` | `[crosslang]`: folder holding every language's fixture folder | `LBD_ROOT` |
| `{dest}` | `[sdk].build`: this language's folder in the SDK | `LBD_DEST` |
| `{version}` | `[sdk].build`: release version | `LBD_VERSION` |

Prefer the environment variables when a path ends up inside the language's own string syntax
(as MATLAB code passed to `matlab -batch` does), because then nothing needs quoting.

`language.toml`, the `example` file and `README.md` are always copied into the SDK, so the
installed viewer can show instructions for every language.

### `[[install]]`: the Language modules page

```toml
[[install]]
where = "sdk"              # "sdk" = installed viewer, "source" = running from the repo, "any"
if_exists = "lbd-*.whl"    # optional glob; the entry is used only if a file in the folder matches
steps = [
    { label = "In a terminal:", code = 'pip install "{path}/{match}"' },
]
upgrade = 'pip install --upgrade "{path}/{match}"'
uninstall = "pip uninstall lbd"
```

The viewer shows the **first** entry that fits. Put specific entries (with `if_exists`)
before general ones. In `steps`, `upgrade` and `uninstall`, these placeholders are replaced;
any other braces are left as they are:

| Placeholder | Value |
|---|---|
| `{path}` | the language folder: `<install dir>/sdk/<id>` installed, `languages/<id>` from source |
| `{match}` | the file name matched by `if_exists` |
| `{version}` | the `lbd` version |
