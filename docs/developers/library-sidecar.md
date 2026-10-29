# The Library's label file

LBD Viewer's Library keeps the labels people give to data files — a star, a project, users,
tags and a comment — in a small file in each folder that has labelled files:
`.lbd-library.json`. Data files are never written for a label. This page defines that file, for
anyone who wants to read or write it from their own program.

## Layout

```json
{
 "format": "lbd-library",
 "version": 1,
 "files": [
  {
   "id": "0199dc2a-4b7e-7f30-8a41-5c6d7e8f9a0b",
   "name": "sweep.lbd",
   "created": "2026-10-13T16:09:00+08:00",
   "star": true,
   "project": "Qubit A/Device 3",
   "users": ["Lab A/Qubit team/Patrick"],
   "tags": ["flux/bias", "resonator"],
   "comment": "punch-out at -20 dBm",
   "changed": {
    "star": ["2026-10-29T02:00:01.120Z", "LAB-PC-2"],
    "project": ["2026-10-29T02:00:01.120Z", "LAB-PC-2"],
    "users": {"Lab A/Qubit team/Patrick": ["2026-10-29T02:00:01.120Z", "LAB-PC-2", true]},
    "tags": {"resonator": ["2026-10-29T02:00:01.120Z", "LAB-PC-2", true],
             "old tag": ["2026-10-29T03:10:00.000Z", "LAPTOP", false]}
   },
   "history": [{"field": "comment", "value": "first try", "changed": ["2026-10-28T09:00:00.000Z", "LAPTOP"]}]
  }
 ]
}
```

| Key | Meaning |
|---|---|
| `format`, `version` | `"lbd-library"` and `1`. A reader must not change a file of a newer `version` (LBD shows its labels read-only). |
| `id` | The data file's `id` (format 1.1). An entry is found by it; `null` for files without one. |
| `name`, `created` | The data file's name in this folder and its `created` time: how files without `id` are found again. |
| `star` | `true` or `false`. |
| `project` | One label or `null`. |
| `users`, `tags` | Lists of labels. |
| `comment` | Text (may span lines). |
| `changed` | When each field was last set: `[UTC time with milliseconds, computer]`. For `users` and `tags`, per label: `[time, computer, true]` when added, `false` when removed (a removal is remembered). |
| `history` | Values that lost a merge (the latest 50), so nothing is lost silently. |

Labels can be nested with `/` (`Qubit A/Device 3`; users as `group/sub-group/name`); each part is
trimmed and must not be empty. An entry with no label left is removed; a folder with none has no
file.

## Writing it safely

Several programs and computers may change one folder's labels (two LBD Viewers, a colleague's
computer through a synced folder). A writer:

1. creates `.lbd-library.lock` in the folder exclusively (if it exists and is older than 10
   seconds, it was left behind and may be removed);
2. reads the file, applies its changes, recording each in `changed`;
3. just before writing, checks whether the file changed since it was read; if so, reads it
   again and **merges** (below) instead of overwriting;
4. writes a temporary file and renames it over `.lbd-library.json`, then removes the lock.

**Merging** two versions of an entry: for `star`, `project` and `comment`, the one with the
newer `changed` time wins; for every single user and tag, the newer record wins (so an addition
and a removal made on two computers both survive); a value that lost goes to `history`; an exact
tie keeps the first value and reports it.

**Sync conflict copies** — files named like `.lbd-library_<computer>_<date>_Conflict.json`
(Synology Drive), `.lbd-library (… conflicted copy …).json` (Dropbox) or `.lbd-library-<computer>.json`
(OneDrive) — are merged the same way and then moved to the Recycle Bin. A file that can't be read
as JSON is set aside as `.lbd-library.broken-<time>.json`.
