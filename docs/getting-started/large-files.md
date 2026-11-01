# Large files

A measurement can be larger than your computer's memory: a long time trace, a fine map, many
repetitions. `load` reads every value whole, so such a file can't be loaded. **`open`** reads
only what you ask for, in every language, and **LBD Viewer** shows such files too. The file
itself is the same: any `.lbd` file can be opened either way.

## Reading part of a file: `open`

`open` reads the file's structure at once (axes, metadata, the saved view, each value's shape)
and leaves the value data in the file. Each value's `data` is an **on-disk array**: its size and
type are known without reading, and indexing it reads only that part.

=== "Python"

    ```python
    import numpy as np
    import lbd

    with lbd.open("big.lbd") as d:
        s21 = d.values["S21"]
        print(s21.data.shape)                # nothing read yet
        row = s21.data[3]                    # power number 3, every frequency: one read
        part = s21.data[:, 100:200]          # a block
        print(np.abs(row).max(), part.shape)
    # the file is closed here; `row` and `part` are ordinary numpy arrays
    ```

=== "MATLAB"

    ```matlab
    d = lbd.open("big.lbd");
    s21 = d.Values.S21.Data;                 % an lbd.OnDisk: nothing read yet
    disp(size(s21))
    row = s21(4, :);                         % power number 4, every frequency
    part = s21(:, 101:200);                  % a block
    d.close();
    disp(max(abs(row)))
    ```

=== "Julia"

    ```julia
    using LBD

    LBD.open("big.lbd") do d
        s21 = d["S21"].data                  # an LBD.OnDisk (an AbstractArray): nothing read yet
        println(size(s21))
        row = s21[4, :]                      # power number 4, every frequency
        part = s21[:, 101:200]               # a block
        println(maximum(abs.(row)))
    end
    ```

- Read what you need in one piece (a row, a block) rather than point by point: each indexing is
  one read from the file.
- Reading it all is still possible: `np.asarray(v.data)` (Python), `Data.read()` or `Data(:, :)`
  (MATLAB), `collect(v.data)` (Julia).
- `rows`, `coords` and `to_dense` of [variable sweeps](concepts.md) work the same on an opened
  file and read only what they need (`rows` one row at a time).
- After closing, what you read stays usable; reading more says the file is closed.
- A file **being written** (`.lbd.writing`, see [Writing while measuring](writing-while-measuring.md))
  can be opened too: you see it as it was when you opened it, and the measurement goes on.

## Changing an opened file: `mode="r+"`

By default an opened file is read only. With `mode="r+"` (MATLAB: `Mode="r+"`) you can change it
without loading it:

- `write` puts new numbers at points that exist (the file doesn't grow: no new points or axes);
- `save()` with no file name writes the title, description, metadata and saved view into the
  file itself (the data is already there);
- `save("other.lbd")` copies the file piece by piece, never holding a whole value.

=== "Python"

    ```python
    import numpy as np
    import lbd

    f = lbd.info("big.lbd").axes["freq"].data
    with lbd.open("big.lbd", mode="r+") as d:
        d.write(power=0, S21=np.zeros(len(f)))     # replace the first trace, in place
        d.meta["checked_by"] = "Ana"
        d.save()                                   # metadata written into big.lbd
        d.save("big_copy.lbd")                     # a copy, piece by piece
    ```

=== "MATLAB"

    ```matlab
    d = lbd.open("big.lbd", Mode="r+");
    d.write(power=1, S21=zeros(1, numel(d.Axes.freq.Data)));   % replace the first trace, in place
    d.Meta.checked_by = "Ana";
    d.save();                                      % metadata written into big.lbd
    d.save("big_copy.lbd");                        % a copy, piece by piece
    d.close();
    ```

=== "Julia"

    ```julia
    using LBD

    LBD.open("big.lbd"; mode="r+") do d
        write!(d; power=1, S21=zeros(length(d.axes["freq"].data)))   # replace the first trace, in place
        d.meta["checked_by"] = "Ana"
        LBD.save(d)                                # metadata written into big.lbd
        LBD.save("big_copy.lbd", d)                # a copy, piece by piece
    end
    ```

## Large files in LBD Viewer

The viewer decides by itself, by the memory the computer has free **now**:

- **A value that fits** is read whole, as for any file.
- **A bigger value** is read by part: only the map or the curves on screen. Parts already read
  are kept while memory is free (moving a slider back is instant) and the next slider positions
  are read ahead; when other programs need the memory, the oldest parts are dropped.
- **A single map or set of curves that doesn't fit at all** is *summarised* once: the viewer
  reads the file part by part (with a progress bar and **Cancel**) and keeps, for blocks of
  cells or points, their highest, lowest and mean value, on disk. The next time the same plot
  opens at once. Zooming in reads only the part of the file in view, so you always see the
  stored numbers when you are close enough.

What works on summarised data:

| | |
|---|---|
| Zoom, pan, max / min / mean per pixel | as usual, the same picture |
| Clicks, cursors, cuts, max / min / peak | read the exact stored numbers from the file |
| A map's contrast histogram | from the summary: approximate (it says so); lowest and highest exact |
| Operations, choosing a map's rows | refused, with a message: they need all the data at once |
| Curves of several values, an unwrapped phase | refused, with a message |
| Library previews | not drawn: open the file in Explore |

The viewer always leaves some memory for the rest of the computer. **⚙ Settings → Memory for
data** sets:

- **Leave free**: memory never used by LBD (automatic: 2 GB or 10 % of the memory, whichever
  is more);
- **Use at most**: an optional limit for LBD's data;
- **Summaries of large data on disk**: how much disk the summaries may take (20 GB; the least
  recently used are removed first), and **Empty** to remove them now. Summaries are made again
  when needed; a changed file gets a new one.

A data file is never changed by viewing it, summarised or not.
