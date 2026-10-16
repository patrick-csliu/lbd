import numpy as np
import lbd

f = np.linspace(4e9, 8e9, 401)
p = np.arange(-40, 1, 4.0)
s21 = np.exp(1j * np.outer(p, f) * 1e-10)        # shape (11, 401) = (power, freq)

d = lbd.Dataset(title="Resonator power sweep")
d.add_axis("power", p, unit="dBm", label="Power")
d.add_axis("freq", f, unit="Hz", label="Frequency")
d.add_value("S21", s21, axes=["power", "freq"])
d.add_axis("t", np.linspace(0, 1e-6, 201), unit="s", label="Time")
d.add_value("trace", np.sin(2e7 * np.linspace(0, 1e-6, 201)), axes="t", unit="V")
d.meta["T_mK"] = 12
d.meta["vna"] = {"ifbw_Hz": 1000.0, "averages": 4}
d.save("example.lbd")

d = lbd.load("example.lbd")
print(d)
print(d["S21"].data.shape, d["S21"].axes)

# --- with lbd[plot]: figures in the viewer's styles, without saving a file first ---
try:
    import lbd.plot as lp
except ImportError:
    print('install "lbd[plot]" to plot from Python')
else:
    fig = lp.plot(d, kind="heatmap", values="S21", complex="phase")   # the viewer's default style
    lp.save(fig, "example_heatmap.pdf")

    import matplotlib.pyplot as plt
    with lp.use():                                   # your own figure, same size/fonts/colours
        fig, ax = plt.subplots()
        t2, tu = lp.prefix(d["t"].data, "s")         # 0..1e-6 s -> 0..1 µs, like the viewer
        ax.plot(t2, d["trace"].data)
        ax.set_xlabel(lp.axis_label("Time", tu))
        ax.set_ylabel(lp.axis_label("Signal", "V"))
        fig.savefig("example_trace.pdf")
