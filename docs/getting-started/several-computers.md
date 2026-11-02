# Several computers

LBD reads and changes data on any computer, and many labs keep their data in a folder that a
sync tool (Synology Drive, OneDrive, Dropbox …) copies between computers, or on a network
share. **LBD has no sync of its own**: what happens when two computers change the same file is
decided by the sync tool or the share, not by LBD. This page says what is safe and what to
watch out for. LBD's own rule is never to lose or mix up data because of another computer: when
in doubt, it keeps both and says so.

## Safe to sync

- **Finished data files** (`.lbd`). A file is written once and only changed afterwards when you
  ask for it (Save view, give ids, rename, recycle). Copies of one measurement are recognised by
  their id.
- **Labels** (`.lbd-library.json` in each folder: stars, projects, users, tags, comments). Two
  computers can label the same files: their changes are merged item by item, and a sync tool's
  "conflict" copy of the label file is merged in too. Nothing is lost.
- **Files being measured** (`name.lbd.writing`). Only the measuring computer writes them; the
  others watch. The heartbeat file `name.lbd.live` tells them *Measuring on LAB-PC*, or *No sign
  from LAB-PC since 10:06* when it stopped changing (it probably stopped, or the sync is paused:
  this computer can't tell which). Recover on such a computer makes a copy and leaves the
  original alone. See [Writing while measuring](writing-while-measuring.md).

## Kept on each computer, on purpose

- **LBD's database**: the Library's index, previews and summaries of large data (all made again
  from the files on each computer), the Explore views LBD remembers and the Library previews you
  chose. Explore views stay on the computer where you made them, like a browser's history; the
  view saved *into the file* (Save view in Figure) is the one every computer sees.
- **Settings and styles.** A style can be shared as a `.lbd.json` file.

Never put LBD's settings or database folder into a synced folder: a database copied by a sync
tool while it is in use gets damaged.

## Watch out

- **Two computers changing the same file** before the sync has passed the first change on (for
  example both save a view of `rabi.lbd` within a minute): the sync tool decides. Most keep both,
  with a "conflict" name (`rabi_LAPTOP_…_Conflict.lbd`, `rabi (conflicted copy).lbd`); some keep
  only the newest. Both copies hold the same data; keep the one with the view you want and
  recycle the other.
- **A network share** (the folder opened over the network, not synced): there is only one file,
  so the last save wins. Measure into a folder on the measuring computer (or a synced one), not
  over a share: writing while measuring there isn't tested yet.
