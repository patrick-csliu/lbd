# Mock data

Made-up `.lbd` files to try LBD Viewer with, and to test it: a Library of hundreds of files with
labels, files for Explore's panels, large files, a measurement being written. Every generator uses a fixed
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
| `Panels/` | files for Explore's panels: several values on one axis, 3-D maps with a slider, values over different axes, many values, I/Q readout, data points with a shape, variable sweeps (format 2.0), uneven grids | `viewer/tests/mock_values.py` |
| `Large/` (not with `--small`) | the four engine tests, about 214 MB: a curve of 1 000 000 points, 1000 traces × 10 000 points, a 4001 × 4001 map, and a small map with uneven x ([below](#large-files-and-uneven-grids)) | `viewer/tests/mock_large.py` |
| `Examples/` | the repository's examples (`examples/data`) | `examples/make_examples.py` |
| `Live/` (with `--live`) | a measurement being written slowly (it runs on in the background; the script prints its process), and one that stopped before finishing | `viewer/tests/mock_live.py` |

Options: `--files N` (the Library's size), `--no-labels`, `--many-labels` (long lists, below),
`--small` (the panel files with few points, and no `Large/`: quick), `--live` and `--live-seconds S`.

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

**Long lists:** `--many-labels` (`make_mock_data.py`, `dev_viewer.py`, `mock_library.py`) uses a
large vocabulary instead (`many_labels()`): 300 users in 4 labs and 20 teams, 800 tags (some
nested 4 deep), 60 projects, and a few names over 80 characters. Every label is kept in the open
folder, so the lists are long even where few files have them. The tests use it through the
`many_labels_files` fixture.

## Large files and uneven grids

`Large/` holds the engine tests the Explore view was measured with. They have the same numbers as
the Labber logs made from the same definitions, noise included (`mock_large.rng` is that test's
random generator), so LBD and Labber can be compared on identical data. Written in a few seconds;
`--small` leaves them out.

| File | What is in it | What to look for |
|---|---|---|
| `1 accuracy.lbd` | one curve of 1 000 000 points: a sine with noise | nothing is lost when the view is reduced to the screen's pixels: the one-point spike (5 at x ≈ 0.731), the three-point dip (−3 at x = 0.2) and the gap of 100 points (x = 0.5 to 0.5001, a break in the line when zoomed in) all show, zoomed out and in |
| `2 traces.lbd` | 1000 traces × 10 000 points, one dip per trace | the dip moves from 4.5 GHz (trace 0) to 5.5 GHz (trace 999); trace 437 alone has a spike (+3 dB at 5.4 GHz) |
| `3 map.lbd` | a 4001 × 4001 map with a resonance that bends with flux | one hot cell (+10 dB at 4.6 GHz, 0.4005 mA) still shows when the map is reduced; the 16 × 16 checkerboard of +5 and −15 dB in the top right corner (5.97–5.98 GHz) is seen as squares when zoomed in, not as stripes or a blur |
| `4 small map.lbd` | a 5 × 4 map, x = 1, 2, 4, 8, 16, value = column + 5 × row | cells get wider to the right, each edge halfway between two values (1.5, 3, 6, 12); a click reads the cell under it (its value says which column and row) |

The uneven grids are small, so they are in `Panels/` and in every test run:

| File | What to look for |
|---|---|
| `20 uneven map.lbd` | both axes' steps grow: cells get wider to the right and taller to the top, edges halfway between values; value = column + 10 × row, so a click shows whether the right cell was read |
| `21 log axis map.lbd` | a log-spaced axis, saved with a log x scale: there every cell has the same width; on a linear scale they grow |
| `22 uneven curve.lbd` | a curve with points dense near its peak (x = 0.5) and sparse away from it: cursors and the peak snap to the stored points |

## Each generator on its own

```bash
uv run python viewer/tests/mock_library.py FOLDER [N] [--labels] [--many-labels]   # the Library (N files, default 300)
uv run python viewer/tests/mock_values.py FOLDER [--small]          # the panels' files
uv run python viewer/tests/mock_large.py FOLDER                      # the large files (engine tests)
uv run python viewer/tests/mock_live.py FOLDER [--seconds 120]       # a measurement being written
uv run python viewer/tests/mock_live.py FOLDER --copy-to OTHER --as-computer LAB-PC
uv run python viewer/tests/mock_live.py FOLDER --variable            # a variable sweep being written
uv run python examples/make_examples.py [OUTDIR]                     # the examples (keeps saved views)
```

`mock_live.py --copy-to OTHER --as-computer LAB-PC` also copies the file being written, and its
heartbeat, into OTHER every few traces, as a sync tool would bring them from another computer.
Open OTHER in the viewer to see "Measuring on LAB-PC", then "No sign …" once it stops.

`mock_live.py --variable` writes `live variable sweep.lbd` instead: a variable sweep (an axis
group, format 2.0) one power a step, each power with its own frequencies, as
`mock_values.variable_sweep` has them. Explore shows it growing a row at a time.

## In the tests

The tests import the same modules:
- `viewer/tests/conftest.py`'s fixture `library_files` writes the mock Library (120 files);
- `values_files` writes the panels' files with `small=True`, the same structure with few points;
- the large files are not used by the test suites (they take seconds and 214 MB);
  `tests/scripts/test_mock_data.py` checks that `make_mock_data.py` writes them without `--small`;
- `test_mock_library.py` checks that the special cases and the labels are there;
- `scripts/make_screenshots.py` uses them for the documentation's pictures.

To add a case:
1. Add a maker to the module (e.g. a new entry in `mock_values.MAKERS`, or a file in
   `mock_library.SPECIAL`).
2. Check it in `test_mock_*.py`.
3. Use it from a test through the fixture.

Keep the arrays small, so the whole Library stays quick to write (10 000 files in about a minute).
