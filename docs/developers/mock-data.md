# Mock data

Made-up `.lbd` files to try LBD Viewer with, and to test it: a Library of hundreds of files with
labels, files for Explore's panels, a measurement being written. Every generator uses a fixed
random seed, so it makes the same files every time.

## One command

```bash
uv run python scripts/make_mock_data.py FOLDER
```

FOLDER (empty or new) then holds everything below. Add it to a viewer as one folder, or open a
test viewer on it at once with [`scripts/dev_viewer.py`](index.md#quick-start-for-developers).

| Folder | What is in it | Made by |
|---|---|---|
| `Lab library/` | about 300 measurements (`--files N` for more or fewer): `Lab data/` sorted by date (`YYYY/MM/DD/`) and `Shared/` sorted by project | `viewer/tests/mock_library.py` |
| `Panels/` | files for Explore's panels: several values on one axis, 3-D maps with a slider, values over different axes, many values, I/Q readout, data points with a shape, variable sweeps (format 2.0) | `viewer/tests/mock_values.py` |
| `Examples/` | the repository's examples (`examples/data`) | `examples/make_examples.py` |
| `Live/` (with `--live`) | a measurement being written slowly (it runs on in the background; the script prints its process), and one that stopped before finishing | `viewer/tests/mock_live.py` |

Options: `--files N` (the Library's size), `--no-labels`, `--small` (the panel files with few
points), `--live` and `--live-seconds S`.

## The Library and its labels

`mock_library.py` writes simulated measurements of five kinds: resonator sweeps, Rabi, qubit
spectroscopy, T1 and fridge logs. They were made over two years, in several time zones, with
titles, descriptions and nested metadata to search. Its special cases (`SPECIAL`) are the ones a
list must handle:
- a damaged file;
- a file without a title;
- the same file name in two folders;
- a file of single numbers only;
- a measurement just before midnight.

With labels (the default of `make_mock_data.py`; `mock_library.py FOLDER N --labels`), about
two thirds of the files get:

| Label | What the mock library gives |
|---|---|
| ★ Star | about 15 % of the files |
| Project | one of `LABEL_PROJECTS`, nested 1–3 levels (`Qubit A/Device 3/Cooldown 7`, `Resonator chip 3/Wafer 12/Die 4`), or none |
| Users | 0–3 of `LABEL_USERS`, in groups and sub-groups (`Lab A/Qubit team/Alice`, `Lab B/Bob`, `Guest`) |
| Tags | 0–4 of `LABEL_TAGS`: flat and nested (`flux/bias`, `quality/redo/more averages`), and one long tag to see how lists and chips cope |
| Comment | none, one line, several lines, or a long one |
| Kept without a file | `KEPT`: a project, a user and a tag no file has yet (as **+ New** makes them), in the open folder's labels file |

It also makes the cases labels must survive:
- an identical copy (sharing its labels);
- a copy changed after copying (a conflict);
- files written before format 1.1 (no id);
- a labelled file deleted outside LBD (listed as missing);
- a sync tool's conflict copy of a labels file.

The label vocabulary is at the top of `viewer/tests/mock_library.py`: change `LABEL_*` or `KEPT`
to try other names.

## Each generator on its own

```bash
uv run python viewer/tests/mock_library.py FOLDER [N] [--labels]   # the Library (N files, default 300)
uv run python viewer/tests/mock_values.py FOLDER [--small]          # the panels' files
uv run python viewer/tests/mock_live.py FOLDER [--seconds 120]       # a measurement being written
uv run python viewer/tests/mock_live.py FOLDER --copy-to OTHER --as-computer LAB-PC
uv run python examples/make_examples.py [OUTDIR]                     # the examples (keeps saved views)
```

`mock_live.py --copy-to OTHER --as-computer LAB-PC` also copies the file being written, and its
heartbeat, into OTHER every few traces, as a sync tool would bring them from another computer.
Open OTHER in the viewer to see "Measuring on LAB-PC", then "No sign …" once it stops.

## In the tests

The tests import the same modules:
- `viewer/tests/conftest.py`'s fixture `library_files` writes the mock Library (120 files);
- `values_files` writes the panels' files with `small=True`, the same structure with few points;
- `test_mock_library.py` checks that the special cases and the labels are there;
- `scripts/make_screenshots.py` uses them for the documentation's pictures.

To add a case:
1. Add a maker to the module (e.g. a new entry in `mock_values.MAKERS`, or a file in
   `mock_library.SPECIAL`).
2. Check it in `test_mock_*.py`.
3. Use it from a test through the fixture.

Keep the arrays small, so the whole Library stays quick to write (10 000 files in about a minute).
