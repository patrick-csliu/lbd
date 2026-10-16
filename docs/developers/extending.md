# Extending LBD

## Add a language
Copy `languages/_template/` to `languages/<id>/`, implement the format, the unit tests, the two
cross-language scripts and an example, and fill in `language.toml`. Then:

```bash
uv run python scripts/languages.py        # discovered and valid?
uv run python scripts/check_versions.py   # same release version?
uv run python scripts/test_all.py         # unit tests + the (N+1) x (N+1) matrix
```

Nothing else in the repository needs to change:
- the test runners, the version check and the installer's SDK packaging read the manifest;
- the viewer's Language modules page gets a new tab.

Finally, add `docs/languages/<id>.md`. The full checklist and the manifest reference are in
[Adding a language](adding-a-language.md).

## Add a style setting
1. Add a field with a default, limits and a `description` to the right model in
   `languages/python/src/lbd/plot/style.py`, at the place in the Figure → Axes → … tree where
   matplotlib has it.
2. Map it to matplotlib in `Style.to_rcparams()` if matplotlib has an rcParam for it (then
   `lbd.plot.use()` and the `.mplstyle` export get it for free). Otherwise use it in
   `lbd/plot/render.py` and in `lbd.plot.apply()`.
3. The Styles page form picks it up from the schema automatically. Add a friendly title to
   `TITLES` in `viewer/web/src/StylesPage.tsx` (it holds the names of fields and of sections).
4. The tables in [Style settings](../styles/settings.md) are generated from the model, so the
   field's `description` is its documentation. A new model also needs a
   `{{ style_table("NewModel") }}` line there. Add a test in
   `languages/python/tests/test_plot.py`.

## Add a plot kind or plot-spec key
1. `languages/python/src/lbd/plot/render.py`:
   - allow it in `KINDS`;
   - resolve its defaults in `resolve_spec`, which must also work on header-only datasets from
     `lbd.info`;
   - draw it in `build_figure`.
2. A new plot-spec key also goes into `SPEC_KEYS` in `lbd/plot/api.py`, so `lbd.plot.plot()`
   accepts it.
3. Add controls to `PlotControls` in `viewer/web/src/FileView.tsx` and the field to `PlotSpec`
   in `viewer/web/src/api.ts`.
4. Add tests in `languages/python/tests/test_plot.py` and `test_render_kinds` in the viewer
   tests. Document it in [Plot settings](../styles/plot-settings.md) and in the docstring of
   `lbd.plot.plot` (the API reference is generated from it).

## Change the file format
1. Update [the format specification](../format.md) (`spec/LBD-v1.md`) first.
   - **Additive changes** (new optional attributes or groups) bump the minor version. Old
     readers keep working.
   - **Breaking changes** bump the major version, and need a new spec file.
2. Implement the change in **every** folder under `languages/`.
3. Update each module's format version. `[format_version]` in each `language.toml` says where
   it lives, and `check_versions.py` compares them with the spec.
4. Extend the fixture: the table in [the cross-language fixture](testing.md#cross-language-fixture)
   and every language's `crosslang/` writer and checker. Then run the matrix.
