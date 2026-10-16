# Languages

One folder per language module for reading and writing `.lbd` files. Every folder has the same
shape and a `language.toml` manifest, so the tests, the version check, the installer and the
viewer's Language modules page pick it up automatically.

| Folder | Module | Users install |
|---|---|---|
| `python/` | `lbd` package (+ `lbd.plot` with `[plot]`) | a wheel, `pip install` |
| `matlab/` | `+lbd` package | `LBD.mltbx` |
| `julia/` | `LBD` package | `Pkg.develop` |
| `_template/` | starting point for a new language (ignored by the tools) | |

Each language folder has a copy of the repository's `LICENSE`, because a module can be installed
from its folder alone (e.g. `pip install "git+…#subdirectory=languages/python"`). A test checks
that every copy matches the one at the top.

**Adding a language** (checklist and the full `language.toml` reference): see the documentation
page *Developers → Adding a language* (`docs/developers/adding-a-language.md`).
