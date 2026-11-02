function write_heartbeat(out)
%WRITE_HEARTBEAT The heartbeat check (tests/crosslang/README.md, "The heartbeat"): in folder OUT,
%   stopped.lbd written 3 of 4 rows and left without finishing, and finished.lbd written to the end.
if ~isfolder(out), mkdir(out); end
for name = ["stopped" "finished"]
    w = lbd.Writer(fullfile(out, name + ".lbd"), FlushEvery=0.05);
    w.addAxis("power", 0:3, Unit="dBm");
    w.addAxis("freq", linspace(1, 2, 7), Unit="Hz");
    w.addValue("S21", [], ["power" "freq"], Dtype="complex128");
    rows = 3 + (name == "finished");
    for i = 1:rows
        w.write(power=i, S21=ones(1, 7));
    end
    if name == "stopped"
        pause(11);                            % the heartbeat is rewritten with all three rows
        w.abort();                            % as a crash: no finish
    else
        w.close();
    end
end
end
