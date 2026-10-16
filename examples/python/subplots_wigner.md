1. **Mock data.** The Wigner function of an even cat state on a 201 × 201 grid. Its projection
   P(x), the probability of finding the position x, is W summed over p. The fringes of W near p = 0
   become the oscillations of P(x).
2. **A Dataset in memory.** W depends on (p, x), so the value gets `axes=["p", "x"]`: rows p,
   columns x. Labels such as `"$x$"` are matplotlib math.
3. **A colour scale centred on zero.** W is negative where the state is non-classical. A
   diverging colour map (`RdBu_r`) with limits `-w … +w` puts zero in white. The limits and the map
   are set for the quantity `W` in the style.
4. **Two panels, one x axis.** [`lp.subplots`][lbd.plot.subplots] works like `plt.subplots`, at
   the style's size (or the `height_mm` you give). `sharex=True` gives both panels the same x
   range; `height_ratios` makes the heat map twice as tall.
5. **Mix the tool's plot with your own.** The top panel is plain matplotlib (`top.plot`); the
   bottom one is [`lp.plot`][lbd.plot.plot] with `ax=bottom`. Inside
   [`lp.use`][lbd.plot.use], both get the same fonts, line widths and ticks.
6. **Panel labels.** `set_title("(a)", loc="left")` puts (a) and (b) above the panels, as
   journals ask.

**Change it**

- The projection on p instead: sum over `axis=1`, and use `sharey=True` with the panels side by
  side, `lp.subplots(1, 2, ...)`.
- A full-width figure: `width_mm=170`.
