1. **What exists.** [`lp.list_styles`][lbd.plot.list_styles] lists the presets: the built-in
   ones and those made on the viewer's Styles page or in Python.
2. **Start from a style and change it.** [`lp.load_style`][lbd.plot.load_style] returns a
   [`Style`][lbd.plot.Style]. Its settings follow matplotlib's structure
   (`style.figure.font.size_pt`), every one is listed in [Style settings](../styles/settings.md),
   and each assignment is checked: a wrong value or a typo is an error. `style.description` is
   the one-line note shown on the Styles page; give a new preset its own, or it keeps the
   default's.
3. **Store it as a preset.** [`PresetStore().save`][lbd.plot.PresetStore.save] stores it under a
   name, shared with the viewer. [`style.diff()`][lbd.plot.style.Style.diff] keeps only what differs from
   the default, so later changes to the default still reach the preset.
4. **Keep it with the paper, share it.** [`style.save`][lbd.plot.style.Style.save] writes a complete
   `.lbd.json` style file that works on any computer.
   [`to_mplstyle`][lbd.plot.style.Style.to_mplstyle] gives the same look to colleagues who use
   matplotlib without LBD: `plt.style.use("talk.mplstyle")`.
5. **Use it.** Anywhere a style is taken (`lp.use`, `lp.plot`, `lp.save`, …), give a preset name
   (`"talk"`), a style file (`"talk.lbd.json"`), a dict of changes, or the `Style` itself.

**Change it**

- Only for one figure, without a preset: `lp.plot(..., style={"figure": {"width_mm": 120}})`.
- Make it the viewer's default: on the Styles page, or in the viewer's settings.
- Remove the preset: `lp.PresetStore().delete("talk")`.
