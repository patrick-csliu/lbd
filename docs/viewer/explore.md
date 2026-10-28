# Explore

**Explore** is where you look at data: zoom in, read exact values, step through traces, switch
between curves and maps. It is the viewer's default workspace: double-clicking a data file
opens it here. For a figure to export, use **Figure** (one click away, see below).

![The Explore workspace: numbered parts](img/explore.png)

1. **Workspaces:** **Library** (find files), **Explore** (look at data) and **Figure** (make
   figures). Each has its own tabs; a file can be open in Explore and in Figure at once.
2. **Tabs** of the files open in Explore. A single click on a file shows it in a *preview* tab
   (in italics), which the next single click replaces; a double-click keeps it open. Right-click
   a tab to close it, open it in Figure or in a new browser tab.
3. **What to plot:** curves or a map, the values, the horizontal axis, one curve per … (or the
   map's vertical axis), complex values, and a slider for each other dimension.
4. **Which traces, scales and colours:** see [Choosing traces](#choosing-traces) and
   [Scales, colours and limits](#scales-colours-and-limits).
5. **How the data fits the screen:** for example "max of 6×8 cells per pixel" (see
   [Large data](#large-data)).
6. **The plot.** Zoom, pan and click on it, see [Moving around](#moving-around).
7. **The value you clicked**, as stored in the file.

## Moving around

| Do | What happens |
|---|---|
| Turn the mouse wheel | Zooms in or out around the mouse. **Shift**: only horizontally; **Alt**: only vertically. |
| Drag with the left button | Zooms to the box you drew. A flat box zooms one axis only. |
| Drag with the right or middle button | Moves the view. |
| Double-click | Shows all the data again (also **Reset view**). |
| Click | Reads the nearest point (curves) or the cell (maps): its value as stored in the file, where it is, and which trace. The trace is highlighted. |
| Type in **Horizontal** / **Vertical** *from … to* | Shows exactly that range. Empty boxes mean "to the end of the data". |

The view follows the mouse at once; the sharp picture follows a moment later (it is drawn by the
same engine as the figures, so Explore and Figure look alike).

## Choosing traces

Under the controls, a list shows each position of the axis that makes the traces: **Curves
shown** (one curve per …) or **Rows in the map** (the map's vertical axis).

- Click a value: only that trace. **Shift**-click: every trace from the last one you clicked to
  this one. **Ctrl**-click (**⌘** on macOS) or the box: add or remove one.
- **All** and **None** at the top.

In a map, rows you leave out stay **empty, in their place**: the vertical axis always tells the
truth. (Packing the chosen rows together would move them.)

## Scales, colours and limits

- **Scales:** log horizontal, log vertical, and for maps a log colour scale. Values of 0 or
  below can't be shown on a log scale and are left out.
- **Colour** (maps): a colour map (*viridis*, *plasma*, *magma* and *cividis* are even to the
  eye; *gray*; *RdBu* for values around zero; *twilight* for phases, which wrap around),
  **Invert**, and the **Colour range** (empty: from the data).
- **Complex values:** magnitude, dB, phase in radians or degrees, the phase **unwrapped** (its
  2π jumps along the horizontal axis removed), real or imaginary part.

## A value as the horizontal axis

The horizontal axis can also be another value of the file with the same axes, for example a
frequency that differs from trace to trace (a VNA whose span changes with power). Each trace is
then drawn at its own x. A value against a value that isn't sorted (say a phase against a
magnitude) is drawn point after point as stored, and the note says so; with more than 200 000
points it is thinned for drawing, keeping the lowest and highest point of each stretch.

## Large data

A screen has far fewer pixels than a large file has numbers: a map of 4001 × 4001 cells shown
in 700 × 500 pixels puts about 50 cells into each pixel. The viewer chooses on purpose what a
pixel shows, and says so in the note above the plot:

- **Maps:** **Several cells per pixel** sets whether a pixel shows the **max** of its cells
  (peaks and single hot cells stay visible), the **min** (dips stay visible) or the **mean**
  (the overall look; a single odd cell fades).
- **Curves:** each pixel column keeps the lowest and highest point in it, so a spike of one point
  still shows.
- Zoomed in far enough, every cell or point is drawn as stored ("every cell shown").

Clicked values never come from the picture: they are read from the file's data.

## What is remembered, and where

The viewer remembers how you explored each file: what was plotted, the chosen traces, colours,
scales, limits and the zoom. Opening the file again shows the same.

- This is kept **on this computer**, in the viewer's own database (in its settings folder, see
  [Command line and settings](command-line.md)). **Nothing is written into the data file.** The
  file holds the data, its description and the figure's saved view (see
  [Saving views](saving-and-exporting.md)).
- Without a remembered view, Explore starts from what the file's saved figure view plots.
- **Forget this view** (at the top) starts afresh. If a file changed so that the remembered view
  no longer fits (an axis it used is gone), a note says so and Explore starts afresh.
- Renaming a file in the viewer keeps its remembered view.

## Files that change

When the program writing a file adds data (a measurement or a simulation that runs), Explore
shows the new data within about two seconds and **keeps your zoom and choices**. If all the data
was shown, the view grows with it. If the file was rewritten with other contents (other axes or
values), Explore starts afresh and a note says why. A file that is still being written shows
"Updating…" until it can be read.

## Explore and Figure

- **Open in Figure** (at the top of an Explore tab) opens the same file in Figure, with the
  figure's own settings and style ([Plotting](plotting.md)).
- In Figure, **Open in Explore** goes the other way.
- In the folder panel, right-click a data file: **Open in Explore** or **Open in Figure**.
- Data files double-clicked in File Explorer or Finder open in Explore, or in Figure: choose in
  **⚙** (see [Settings](index.md#settings)).
