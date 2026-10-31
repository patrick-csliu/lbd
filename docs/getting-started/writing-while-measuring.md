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

- **LBD Viewer** lists the file as **measuring…** and opens it as it is now; open it again to see
  newer data. It draws no Library preview until the file is finished, and doesn't rename,
  recycle or save views into it.
- **Your own scripts** read it with `lbd.load("power_sweep.lbd.writing")` (any language), which warns
  that it is still being written. `lbd.writing_status(...)` (MATLAB `lbd.writingStatus`) says
  `"measuring"` or `"stopped"`.
- **Other programs** (HDFView, h5py without LBD, ...) are refused while it is written; this
  doesn't disturb the measurement. Open them after it is finished.

Data reaches the file within half a second of `write` (`flush_every`; `w.flush()` writes at
once) and is forced to the disk every 2 seconds (`force_every`), so a power cut loses at most
the last moments.

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
checks the copy and removes the `.writing` file. It refuses while the measurement is still
running.

## Good to know

- The Writer never replaces a file: it refuses at once if `power_sweep.lbd` or `power_sweep.lbd.writing`
  exists, and if `power_sweep.lbd` appears while measuring, it saves as `power_sweep (2).lbd` with a warning.
- If another program still has the file open when the measurement ends, the Writer waits up to
  10 seconds, then says which program holds it; the complete file stays as `.writing`
  (Recover, or rename it).
- **Measure into a folder on this computer.** Writing while measuring onto a network share
  (NAS) isn't tested yet; Python warns when the folder is on one.
- Tested on Windows; macOS and Linux are checked by the automatic tests.
- Files being written use the HDF5 1.10 format, readable by every HDF5 since 1.10 (MATLAB needs
  HDF5 1.10 or newer to write them).
- The same calls work without a Writer: `add_value` without data and `write` fill an
  `lbd.Dataset` in memory, which you `save` at the end.
- The rules for files being written are in the [file format](../format.md#7-files-being-written).
