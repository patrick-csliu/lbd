# Writing while measuring

Usually a script measures everything and then saves the file once. For a long measurement you
may want more: to look at the data while it is measured (in LBD Viewer, or another script), and
to keep what was measured when the script crashes or the computer loses power. The **Writer**
does that, from every language, with the same calls you use to build a dataset.

## A measurement written as it goes

=== "Python"

    ```python
    import numpy as np
    import lbd

    powers = np.linspace(-60, 0, 7)
    freqs = np.linspace(6.99e9, 7.01e9, 201)

    def measure(p):                                   # your instrument here
        return 1 - 0.8 / (1 + 2j * (freqs - 7e9) / 1e6)

    with lbd.Writer("power_sweep.lbd", title="Resonator power sweep") as w:
        w.add_axis("power", powers, unit="dBm")
        w.add_axis("freq", freqs, unit="Hz")
        w.add_value("S21", axes=["power", "freq"], dtype="complex128")   # no data yet
        w.meta["T_mK"] = 12
        for i, p in enumerate(powers):
            w.write(power=i, S21=measure(p))          # one trace: power i, every frequency
    print(lbd.load("power_sweep.lbd").values["S21"].data.shape)   # (7, 201)
    ```

=== "MATLAB"

    ```matlab
    powers = linspace(-60, 0, 7);
    freqs = linspace(6.99e9, 7.01e9, 201);
    w = lbd.Writer("power_sweep.lbd", Title="Resonator power sweep");
    w.addAxis("power", powers, Unit="dBm");
    w.addAxis("freq", freqs, Unit="Hz");
    w.addValue("S21", [], ["power" "freq"], Dtype="complex128");   % no data yet
    w.Meta.T_mK = 12;
    try
        for i = 1:numel(powers)
            trace = 1 - 0.8 ./ (1 + 2i * (freqs - 7e9) / 1e6);   % your instrument here
            w.write(power=i, S21=trace);              % one trace: power i (from 1), every frequency
        end
        w.close();
    catch err
        w.abort();                                    % keep what was measured, as a .writing file
        rethrow(err);
    end
    disp(size(lbd.load("power_sweep.lbd").Values.S21.Data))   % 7 201
    ```

=== "Julia"

    ```julia
    using LBD

    powers = collect(range(-60.0, 0, 7))
    freqs = collect(range(6.99e9, 7.01e9, 201))
    measure(p) = 1 .- 0.8 ./ (1 .+ 2im .* (freqs .- 7e9) ./ 1e6)   # your instrument here

    lbd_writer("power_sweep.lbd"; title="Resonator power sweep") do w
        add_axis!(w, "power", powers; unit="dBm")
        add_axis!(w, "freq", freqs; unit="Hz")
        add_value!(w, "S21"; axes=["power", "freq"], dtype=ComplexF64)   # no data yet
        w.meta["T_mK"] = 12
        for (i, p) in enumerate(powers)
            write!(w; power=i, S21=measure(p))        # one trace: power i (from 1), every frequency
        end
    end
    println(size(LBD.load("power_sweep.lbd")["S21"].data))   # (7, 201)
    ```

Give every axis and value first, then `write` the data as it is measured. While the script
runs, the file is called `power_sweep.lbd.writing`; when it ends, it becomes `power_sweep.lbd`.

## What `write` takes

One call puts data where the axes say: a single point, a trace, a whole map, or several values
at once.

- A **fixed axis** takes an **index** (from 0 in Python, from 1 in MATLAB and Julia), or one of
  its [elements](concepts.md): `state="excited"`.
- The **data** has the size of the axes you didn't give, in order: `write(power=i, S21=trace)`
  for `S21[power, freq]` takes one number per frequency; `write(power=i, freq=j, S21=z)` one
  number; `write(S21=map)` the whole map.
- Several values in one call: `write(power=i, S21=trace, T=temperature)` (`T` lies on `power`).
- Writing again to the same place replaces what was there; the points can come in any order.
- A name that can't be a keyword: `w.write({"if": 3}, S21=z)` in Python,
  `w.write("if", 3, "S21", z)` in MATLAB, `write!(w, Dict("if" => 3); S21=z)` in Julia.

Mistakes are refused with the reason, before anything is written: a position out of range, data
of the wrong size (the message gives the size it needs), complex data for a real value, or
`1.5` for an integer value.

## An axis of unknown length

A log, or a measurement that runs until you stop it: make its axis **growing**, and give each
point's coordinate with its data. A value on a growing axis has it as its first axis.

=== "Python"

    ```python
    import time
    import lbd

    with lbd.Writer("cooldown.lbd", title="Cool-down") as w:
        w.add_axis("time", unit="s", grows=True)
        w.add_value("T", axes="time", unit="K")
        start = time.time()
        for k in range(5):
            w.write(time=time.time() - start, T=300 - k)   # adds a point
    print(lbd.load("cooldown.lbd").values["T"].data)        # [300. 299. 298. 297. 296.]
    ```

=== "MATLAB"

    ```matlab
    w = lbd.Writer("cooldown.lbd", Title="Cool-down");
    w.addAxis("time", [], Unit="s", Grows=true);
    w.addValue("T", [], "time", Unit="K");
    for k = 0:4
        w.write(time=k, T=300 - k);                   % adds a point
    end
    w.close();
    ```

=== "Julia"

    ```julia
    using LBD

    lbd_writer("cooldown.lbd"; title="Cool-down") do w
        add_axis!(w, "time"; unit="s", grows=true)
        add_value!(w, "T"; axes="time", unit="K")
        for k in 0:4
            write!(w; time=k, T=300 - k)              # adds a point
        end
    end
    ```

A vector of coordinates adds as many points at once (`write(time=[1, 2], T=[10, 20])`).

## A variable sweep

When the inner points depend on the outer ones (here: frequencies chosen around a resonance that
moves with power), use an [axis group](concepts.md#variable-sweeps-axis-groups): `write` adds
each point by its coordinates, and the file holds only measured points, growing as they come.

=== "Python"

    ```python
    import numpy as np
    import lbd

    with lbd.Writer("adaptive.lbd", title="Resonance tracking") as w:
        w.add_group("scan")
        w.add_axis("power", group="scan", unit="dBm")
        w.add_axis("freq", group="scan", unit="Hz")
        w.add_value("S21", axes=["power", "freq"], dtype="complex128")
        for p in np.linspace(-60, 0, 7):
            f0 = 7e9 - 2e6 * 10 ** (p / 20)              # where the resonance is now
            freqs = np.linspace(f0 - 3e6, f0 + 3e6, 21)
            i = w.write(power=p)                         # the power point …
            w.write(parent=i, freq=freqs, S21=1 - 0.8 / (1 + 2j * (freqs - f0) / 6e5))
    print(lbd.load("adaptive.lbd").values["S21"].shape)   # (147,): 7 powers × 21 points each
    ```

=== "MATLAB"

    ```matlab
    w = lbd.Writer("adaptive.lbd", Title="Resonance tracking");
    w.addGroup("scan");
    w.addAxis("power", [], Group="scan", Unit="dBm");
    w.addAxis("freq", [], Group="scan", Unit="Hz");
    w.addValue("S21", [], ["power" "freq"], Dtype="complex128");
    for p = linspace(-60, 0, 7)
        f0 = 7e9 - 2e6 * 10^(p / 20);                     % where the resonance is now
        freqs = linspace(f0 - 3e6, f0 + 3e6, 21);
        i = w.write(power=p);                             % the power point ...
        w.write(Parent=i, freq=freqs, S21=1 - 0.8 ./ (1 + 2i * (freqs - f0) / 6e5));
    end
    w.close();
    disp(size(lbd.load("adaptive.lbd").Values.S21.Data))   % 147 1
    ```

=== "Julia"

    ```julia
    using LBD

    lbd_writer("adaptive.lbd"; title="Resonance tracking") do w
        add_group!(w, "scan")
        add_axis!(w, "power"; group="scan", unit="dBm")
        add_axis!(w, "freq"; group="scan", unit="Hz")
        add_value!(w, "S21"; axes=["power", "freq"], dtype=ComplexF64)
        for p in range(-60.0, 0, 7)
            f0 = 7e9 - 2e6 * 10^(p / 20)                 # where the resonance is now
            freqs = collect(range(f0 - 3e6, f0 + 3e6, 21))
            i = write!(w; power=p)                       # the power point …
            write!(w; parent=i, freq=freqs, S21=1 .- 0.8 ./ (1 .+ 2im .* (freqs .- f0) ./ 6e5))
        end
    end
    println(size(LBD.load("adaptive.lbd")["S21"].data))   # (147,)
    ```

Readers see complete points only: a point whose outer point isn't in the file yet waits for the
next read.

## Points not measured

Before a point is written it holds `NaN`, LBD's "missing". If the measurement stops early, the
points never measured stay `NaN`, and plots leave them empty.

Integer and boolean values (counts, flags) have no `NaN`. For them LBD keeps a **measured
mask**: `d.values["counts"].measured` (`Measured` in MATLAB, `measured` in Julia) is true where
something was written, and `None` / empty / `nothing` when everything was measured. In the file it
is `/measured/counts`, stored only when something is missing.

When you stop on purpose before the end, say so: `w.close(stopped=True)` (MATLAB
`w.close(Stopped=true)`, Julia `close(w; stopped=true)`). The file is finished the same way;
only the warning that an integer value wasn't measured everywhere is left out.

## While it is written

- **LBD Viewer** lists the file as **measuring…** and shows it as it grows, with a status line:
  *Measuring · power 23 of 90 · 26 % · 47 069 of 180 090 points · about 12 min left* (what it
  shows is set in ⚙ → Measurements). When the measurement finishes, its tabs move to the
  finished file by themselves. It draws no Library preview until the file is finished, and
  never writes into it: only the program that measures does.
- **Your own scripts** read it with `lbd.load("power_sweep.lbd.writing")` (any language), which warns
  that it is still being written. `lbd.writing_status(...)` (MATLAB `lbd.writingStatus`) says
  `"measuring"` or `"stopped"`.
- **Other programs** (HDFView, h5py without LBD, ...) are refused while it is written; this
  doesn't disturb the measurement. Open them after it is finished.

Data reaches the file within half a second of `write` (`flush_every`; `w.flush()` writes at
once) and is forced to the disk every 2 seconds (`force_every`), so a power cut loses at most
the last moments.

### The heartbeat: `power_sweep.lbd.live`

Beside the file being written, the Writer (every language) keeps a small text file,
`power_sweep.lbd.live`: which computer and program measure, and how far they are (points written
and how many there will be, the outer axes' positions and how long each step takes). It is
rewritten at least every 30 seconds, even while nothing new is measured, and removed when the
measurement finishes. LBD Viewer reads it for the status line, and on **another computer** (the
folder synced there) to tell *Measuring on LAB-PC* from *No sign from LAB-PC since 10:06* (see
[Several computers](several-computers.md)). Scripts read it too:

<!-- no-check -->
```python
p = lbd.writing_progress("power_sweep.lbd.writing")
p["computer"], p["values"]["S21"]["points"], p["values"]["S21"]["total"]
```

In MATLAB and Julia the heartbeat is rewritten when MATLAB / Julia is free: an instrument call
that blocks for longer than about ten minutes shows as *no sign* on other computers meanwhile.

## When it stops before finishing

A crash, an error in your script, or a script that ended without closing the Writer leaves
`power_sweep.lbd.writing` with everything written until then. In Python and Julia an error inside the
`with` / `do` block does this by itself (the error goes on); in MATLAB call `w.abort()` in your
`catch`, as above.

LBD Viewer marks such a file **stopped before finishing** with a **Recover** button. From code:

=== "Python"

    <!-- no-check -->
    ```python
    lbd.recover("power_sweep.lbd.writing")      # -> power_sweep.lbd (or "power_sweep (2).lbd" if that exists)
    ```

=== "MATLAB"

    <!-- no-check -->
    ```matlab
    lbd.recover("power_sweep.lbd.writing");
    ```

=== "Julia"

    <!-- no-check -->
    ```julia
    LBD.recover("power_sweep.lbd.writing")
    ```

Recover copies what was written into an `.lbd` file (the same measurement: it keeps its id),
checks the copy and removes the `.writing` file (and its heartbeat). It refuses while the
measurement is still running.

A file measured **on another computer** and synced here can't be known to have stopped (it may
still run there). LBD Viewer then offers **Recover a copy…**: `power_sweep (recovered).lbd`, with
everything it holds now, and the file being written is left as it is (removing it would travel
back through the sync). In Python: `lbd.recover(path, keep=True)`.

## Good to know

- The Writer never replaces a file: it refuses at once if `power_sweep.lbd` or `power_sweep.lbd.writing`
  exists, and if `power_sweep.lbd` appears while measuring, it saves as `power_sweep (2).lbd` with a warning.
- If another program still has the file open when the measurement ends, the Writer waits up to
  10 seconds, then says which program holds it; the complete file stays as `.writing`
  (Recover, or rename it).
- **Measure into a folder on this computer** (or a synced folder: the sync tool copies it).
  Writing while measuring onto a network share (NAS) isn't tested yet; every language warns
  when the folder is on one (Windows).
- Tested on Windows; macOS and Linux are checked by the automatic tests.
- Files being written use the HDF5 1.10 format, readable by every HDF5 since 1.10 (MATLAB needs
  HDF5 1.10 or newer to write them).
- The same calls work without a Writer: `add_value` without data and `write` fill an
  `lbd.Dataset` in memory, which you `save` at the end.
- The rules for files being written are in the [file format](../format.md#7-files-being-written).
