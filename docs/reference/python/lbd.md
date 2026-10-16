# `lbd` — reading and writing files

```python
import lbd
```

This reference is generated from the code. For a guided introduction with examples, type tables
and recipes, see [Reading and writing files](../../python/files.md).

## Datasets

::: lbd.Dataset
    options:
      heading_level: 3

::: lbd.Axis
    options:
      heading_level: 3

::: lbd.Value
    options:
      heading_level: 3

## Reading

::: lbd.load
    options:
      heading_level: 3

::: lbd.info
    options:
      heading_level: 3

## Changing a file's saved view

::: lbd.set_plot
    options:
      heading_level: 3

## Versions

::: lbd.version
    options:
      heading_level: 3

## Errors and warnings

`lbd` never changes or drops data silently. Input it can't store raises an error; input it
stores but not exactly as given (or a file with parts it can't read) gives a warning.

| | When |
|---|---|
| `LBDError` | Invalid names, shapes or types; lossy conversions to a forced `dtype`; a file that isn't LBD or breaks the format rules; metadata that can't be stored. |
| `LBDVersionError` | The file's major format version is newer than this module. |
| `TypeError` | An argument of the wrong type, e.g. a number as `unit`. |
| `LBDWarning` | Long double stored as float64; an axis that isn't sorted; a file from a newer minor version; a saved view or metadata that is partly unreadable. |

To silence LBD's warnings on purpose (not recommended while developing):

```python
import warnings
import lbd

warnings.filterwarnings("ignore", category=lbd.LBDWarning)
```

::: lbd.LBDError
    options:
      heading_level: 3

::: lbd.LBDVersionError
    options:
      heading_level: 3

::: lbd.LBDWarning
    options:
      heading_level: 3
