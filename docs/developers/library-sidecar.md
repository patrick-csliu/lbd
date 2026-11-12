# The Library's label file

LBD Viewer's Library keeps the labels people give to data files — a star, a project, users,
tags and a comment — in a small file in each folder that has labelled files:
`.lbd-library.json`. The data files hold their labels too (`/labels`, see
[the file format](../format.md), §1.9); the label file is the
record of every change, for merging two computers' edits, history and removals. This page
defines that file, for anyone who wants to read or write it from their own program. To label
a file from a script, use the language modules' set-labels functions instead
(`lbd.set_labels`): they write the data file, and the Library takes the labels from there.

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
| `labels` | Optional, at the top level next to `files`: labels the folder **keeps without a file** (made with **+ New** in the Library, e.g. a project before its first measurement). Per kind (`"project"`, `"users"`, `"tags"`), per label: `[time, computer, true]` while it is kept, `false` once it was removed (remembered, like a removed tag). |

Labels can be nested with `/` (`Qubit A/Device 3`; users as `group/sub-group/name`); each part is
trimmed and must not be empty. An entry whose labels were all removed stays, with the times of the
removals: they are newer than the labels an older copy of the data file may still hold. An entry
with no label and no recorded change is removed; a folder with no entry and no kept label has no
file.

```json
 "labels": {"project": {"Qubit C/Device 1": ["2026-11-04T05:12:00.250Z", "LAB-PC-2", true]},
            "tags": {"old tag": ["2026-11-04T06:00:00.000Z", "LAPTOP", false]}}
```

A writer keeps keys it doesn't know (written by a newer program of the same `version`), and merges
two `labels` per label: the newer decision wins.

## Writing it safely

Several programs and computers may change one folder's labels (two LBD Viewers, a colleague's
computer through a synced folder). A writer:

1. creates `.lbd-library.lock` in the folder exclusively, holding its own text (computer, process
   id and a random part). If the lock exists, it waits its turn, up to **15 seconds**; then the
   change is refused with an error that says it was not made;
2. while it holds the lock, touches the lock file every **2 seconds**, so a writer that works
   long (a slow or busy computer) never looks like one that stopped;
3. reads the file, applies its changes, recording each in `changed`;
4. just before writing, checks whether the file changed since it was read; if so, reads it
   again and **merges** (below) instead of overwriting;
5. writes a temporary file and renames it over `.lbd-library.json`, then removes the lock, but
   only if it still holds its own text (a lock another writer has taken meanwhile stays).

**A lock left behind** (its writer crashed) is one whose file time **doesn't change for 10
seconds** while a waiting writer watches it, timed on the waiting writer's own clock; it is then
removed. The lock's time is only compared with itself, never with this computer's clock, so on a
shared folder a clock difference between two computers can't make a working writer's lock look
old.

**Merging** two versions of an entry: for `star`, `project` and `comment`, the one with the
newer `changed` time wins; for every single user and tag, the newer record wins (so an addition
and a removal made on two computers both survive); a value that lost goes to `history`; an exact
tie keeps the first value and reports it.

## Labels in the data files

The Library writes a file's labels into the data file too, about 2 seconds after the last edit
(several edits become one write; anything waiting is written before the viewer closes), with
`written` = the time of the entry's newest change. It follows Settings → Library → **Edit data
files** (in place, or copy and swap). The data file's version stays the same for the rest of the
viewer, so nothing open on it is drawn or read again.

- **Which computer writes.** Only the computer that made the newest change (`changed`) writes it
  into the data file. Two viewers on one synced folder never both write a data file.
- **Files that can't be written now** (being measured, read-only, open in another program) are
  written later: a file being written gets its labels when it is finished; the others are tried
  again every 30 s or so, and the Library says why they aren't in the file yet.
- **Labels set before** this (only in the label file) are written into their files once, a few
  at a time, by the computer that last changed them.
- **Reading.** Each label in a data file counts as set at the file's `written` time. Where it is
  newer than the entry's record of that field, tag or user (a script's `lbd.set_labels`, another
  viewer's edit whose label file hasn't arrived), the entry takes it, recorded as changed by
  `"the data file"`, and the values it had are kept in `history`. Where the entry's record is
  newer (an edit in the Library, a removal), the entry wins and is written into the file.
- One `written` time covers all of a file's labels, so a file can't say which field a script
  changed: if a script changes the labels of a file whose newest Library edit isn't in it yet,
  the script's labels win for every field.
- **Copies.** Two files with the same id are compared by their data (labels and format version
  left out), so labels written into one copy don't make them "copies that differ".
- LBD is not a sync tool: it does nothing special about a sync tool's conflict copies of data
  files. Two files with one id are copies, or copies that differ, as before; nothing is deleted
  or merged automatically.

**Sync conflict copies** — files named like `.lbd-library_<computer>_<date>_Conflict.json`
(Synology Drive), `.lbd-library (… conflicted copy …).json` (Dropbox) or `.lbd-library-<computer>.json`
(OneDrive) — are merged the same way and then moved to the Recycle Bin. A file that can't be read
as JSON is set aside as `.lbd-library.broken-<time>.json`.
