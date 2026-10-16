1. **Mock data.** A noise power spectral density with a 1/f part and a white floor. The corner
   frequency is where the two are equal.
2. **Your own figure in the house style.** Everything inside `with lp.use():`
   ([`lp.use`][lbd.plot.use]) uses the style: the figure size, fonts, line widths, ticks and
   colours. With no argument it is the default style (or the one chosen in the viewer); pass a
   preset name, a style file or a dict to use another.
3. **Plain matplotlib.** `ax.loglog` draws on log-log axes; the rest is ordinary matplotlib, so
   any figure type works.
4. **Readable numbers and labels.** [`lp.prefix`][lbd.plot.prefix] turns 3125 Hz into
   (3.1, "kHz"). [`lp.axis_label`][lbd.plot.axis_label] writes "Frequency (Hz)" in the style's
   unit format, so labels match the viewer's.
5. **Save.** [`lp.save`][lbd.plot.save] saves at the exact figure size and the style's
   resolution.

**Change it**

- Only the x axis logarithmic: `ax.semilogx(...)`.
- With the tool's own plot instead: `lp.plot(d, "curve", "S_V", x_scale="log", y_scale="log")`.
- A thesis-sized figure: `lp.use("thesis")`, if you have a preset of that name.
