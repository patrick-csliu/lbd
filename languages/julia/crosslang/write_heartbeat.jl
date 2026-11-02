# The heartbeat check (tests/crosslang/README.md, "The heartbeat"): in folder OUT, stopped.lbd
# written 3 of 4 rows and left without finishing, and finished.lbd written to the end.
using LBD

out = ARGS[1]
mkpath(out)
for (name, rows) in (("stopped", 3), ("finished", 4))
    w = LBD.Writer(joinpath(out, "$name.lbd"); flush_every=0.05)
    add_axis!(w, "power", collect(0.0:3); unit="dBm")
    add_axis!(w, "freq", collect(range(1, 2; length=7)); unit="Hz")
    add_value!(w, "S21"; axes=["power", "freq"], dtype=ComplexF64)
    for i in 1:rows
        write!(w; power=i, S21=ones(ComplexF64, 7))
    end
    if name == "stopped"
        sleep(11)                             # the heartbeat is rewritten with all three rows
        LBD.abort!(w)                         # as a crash: no finish
    else
        close(w)
    end
end
