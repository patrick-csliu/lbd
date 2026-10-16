1. **Mock data.** 1000 complex I + iQ readings for each prepared state, in volts. They are kept
   together as one value `IQ` with the axes `state` (2 points) and `shot` (1000 points), the way a
   measurement would store them.
2. **The I/Q plane.** With `kind="scatter"` and `complex="iq"`, [`lp.plot`][lbd.plot.plot]
   draws the real part against the imaginary part of every point, with one scale for both axes, so
   the clouds keep their shape.
3. **One colour per state.** `color="state"` colours the points by the `state` axis. Because
   that axis is short (no more points than the style has colours), each state gets a colour of
   its own and a legend entry. A long axis, or a value such as a temperature, gets a colour bar
   instead ([plot settings](../styles/plot-settings.md)).
4. **Override the style for this figure.** The I/Q plot has its own quantity key, `IQ.iq`
   (value name and complex mode). `"prefix": "m"` shows it in mV whatever the data
   ([fixed unit prefixes](../styles/scales-and-units.md)). `x_label` and `y_label` replace the
   default "Re IQ" and "Im IQ".

**Change it**

- All points in one colour: leave out `color`.
- Only one state: add `index={"state": 1}`.
- Mark the centres and the threshold: see the [heat map example](heatmap_single_shot.md).
