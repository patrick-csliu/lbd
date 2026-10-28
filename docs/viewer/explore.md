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
7. **The cursors' values**, as stored in the file, see [Reading values](#reading-values).

Below the side panel's colours is the **Cursors** section (see [Reading values](#reading-values)).
Click **?** under the plot (or press **?** on it) for every mouse action and key.

## Moving around

| Do | What happens |
|---|---|
| Turn the mouse wheel | Zooms in or out around the mouse. **Shift**: only horizontally; **Alt**: only vertically. |
| Drag with the left button | Zooms to the box you drew. A flat box zooms one axis only. |
| Drag with the right or middle button | Moves the view. |
| Double-click | Shows all the data again (also **Reset view**). |
| Click | Puts cursor 1 on the nearest stored point (curves) or on the cell (maps), see [Reading values](#reading-values). |
| Right-click | A menu: cursors, Max, Min, Peak, cuts, show everything. |
| Type in **Horizontal** / **Vertical** *from … to* | Shows exactly that range. Empty boxes mean "to the end of the data". |

Every picture is complete: its axes always match its data. While you zoom or pan, the data is
drawn at half resolution, which is faster; as soon as the mouse rests, the sharp picture follows.
Pictures are drawn by the same engine as the figures, so Explore and Figure look alike.

## Choosing traces

Under the controls, a list shows each position of the axis that makes the traces: **Curves
shown** (one curve per …) or **Rows in the map** (the map's vertical axis). While every trace
is shown, the list is folded under its title ("all 4001"); click the title to open it.

- Click a value: only that trace. **Shift**-click: every trace from the last one you clicked to
  this one. **Ctrl**-click (**⌘** on macOS) or the box: add or remove one.
- **All** and **None** at the top.

In a map, rows you leave out stay **empty, in their place**: the vertical axis always tells the
truth. (Packing the chosen rows together would move them.)

## Reading values

![Two cursors on a map, with its cuts](img/reading.png)

1. **The row** through cursor 1, on the map's horizontal axis.
2. **The column** through cursor 1, on the map's vertical axis.
3. **Cursor 1** (red) on a cell, **cursor 2** (blue), and the range between them.

Under the plot are their values, as stored, and the differences and means between them. The
**Cursors** section of the side panel (below the colours) has the same and more: the cursor
type, typed positions, Max · Min · Peak, the cuts, and taking a cut out.

Cursors sit **on the stored data**: a click puts cursor 1 on the nearest point of the nearest
trace (curves) or on the cell (maps), and every number shown is the value stored in the file,
with its index ("stored at freq[4031], trace[12]"). Values are as plotted, for example |S21| in
dB for a complex value shown in dB.

| Do | What happens |
|---|---|
| Click | Cursor 1 there. |
| **Shift** + click | Cursor 2: a range, shaded, with the differences (Δ) and means between the two cursors. |
| Drag a cursor | Moves it. A cursor on a trace stays on that trace and follows it. |
| **Alt** + click or drag | A free position, not on the data; the read-out then gives the nearest stored value. |
| **Esc** | Removes the cursors. |

**Cursor types**, in the Cursors section:

- **Crosshair** (the default): a point of one trace, or a cell.
- **Vertical:** a line at one x; the section lists **every visible trace's value there**, the
  cursor's own trace first.
- **Horizontal:** a line at one height, for example to compare peaks with a level.

**The Cursors section** shows each cursor's numbers. Positions can be typed (with a prefix if you
like: `5.12 GHz`); the cursor then moves to the nearest stored point. **Max**, **Min** and
**Peak** move cursor 1 to the highest, the lowest, or the point farthest from the median (a dip
or a spike, whichever stands out more): between the two cursors when there are two, otherwise in
what is in view; on curves, on cursor 1's trace if it is on one. They search the stored data,
not the picture.

**Cuts** (maps): the row and the column through cursor 1 are drawn above and beside the map, on
exactly the map's axes, and follow the cursor while you drag it. Their value axis fits the part
in view; when a cut has more points than pixels, each pixel shows its lowest and highest value.
Hover a cut to read it. **Cuts** above the plot (or the key **C**) turns them off.

**Cursors** above the plot (or the key **K**) switches the cursors off: a click then does
nothing, and the cursors, cuts and values are hidden. Switched on again, the same cursors come
back.

**Taking a cut out:**

- **Row as curve** / **Column as curve** shows that row or column as a curve in the same tab;
  **◂ Back to the map** returns.
- **Save row…**, **Save column…** (maps) and **Save trace…** (curves) write a new `.lbd` file in
  the same folder, with a suggested name you can change. It holds the stored data (complex
  values stay complex), its axis and units, and in its metadata where it came from: the source
  file, and the index and value of each fixed axis (`cut_from`, `cut_index`, `cut_at`; the
  source's own metadata under `source_meta`). The source file is not changed, and an existing
  file is never overwritten.

**Keys**, after clicking the plot:

| Key | Does |
|---|---|
| ← → | Moves the active cursor one stored point (**Shift**: 10). |
| ↑ ↓ | Curves: the next or previous trace; maps: one row. |
| Tab | Switches the active cursor (1 ↔ 2). |
| M, N, P | Max, Min, Peak. |
| [ ] | The first slider one step back or on. |
| + − | Zooms in or out around cursor 1. |
| Home or 0 | Shows everything. |
| C | Cuts on or off (maps). |
| K | Cursors on or off (off: a click does nothing). |
| Esc | Cancels a box being drawn; otherwise removes the cursors. |
| ? | The list of mouse actions and keys. |

## Operations

The **Operations** section (in the side panel, above Scales) works on the data as shown: add
operations with **+ Add operation**, in any order and as many as you like. Each runs on the
result of the ones above it. Explore only: they are remembered with the view on this computer,
never written into the file; **Figure** always shows the stored data.

| Operation | What it does | Unit |
|---|---|---|
| **Subtract the mean** | each trace minus its mean; *along* a map's other axis it removes a background that changes from row to row | as before |
| **Normalize** | (value − mean) / standard deviation | none (σ) |
| **Derivative** | d/dx, with the real steps (uneven ones too) | per the axis' unit, e.g. dB/GHz |
| **Smooth** | running mean over N points; missing points are skipped and stay missing | as before |
| **Subtract the first trace** / **the previous trace** | across the traces (or a map's rows) | as before |
| **Average** / **Std of the traces** | one curve from the shown traces | as before |
| **FFT** | amplitude spectrum, positive frequencies (a sine of amplitude A peaks at A); needs evenly spaced points without gaps | the axis becomes 1/its unit: s → Hz, Hz → s |
| **Histogram** | counts of the values, in N bins; the value becomes the horizontal axis | counts |

- Each operation runs **along** an axis: the horizontal axis (within each trace, or each row of
  a map), or **across the traces** (the curves of one curve per …, or along a map's vertical
  axis). Operations across traces use only the traces you chose.
- **▲ ▼** move an operation, **×** removes it, its box turns it off; **on** at the top turns
  them all off, to compare with the stored data.
- An operation that can't apply where it is (an FFT on uneven steps, "subtract the previous
  trace" after averaging) turns **red** with the reason; the plot then shows the result of the
  operations above it.
- Under the list: what the plot shows now, and in which unit.
- **Cursors** read the values as shown and, while each shown point is still one stored point,
  also the stored value: `S21 − mean = 1.07 dB … (stored: S21 = 0.19 dB)`. After an average, an
  FFT or a histogram the points are new ones, so only the shown value is read, and a cut can't
  be saved (turn the operations off to save the stored data).

## Scales, colours and limits

- **Scales:** log horizontal, log vertical, and for maps a log colour scale. Values of 0 or
  below can't be shown on a log scale and are left out.
- **Colour** (maps): a colour map (*viridis*, *plasma*, *magma* and *cividis* are even to the
  eye; *gray*; *RdBu* for values around zero; *twilight* for phases, which wrap around),
  **Invert**, and the **Colour range** (empty: from the data).
- **Contrast** (maps): a histogram of the map's values (all its cells, not only the view) with
  the colour range as two lines. Drag a line to move that end, or drag between them to move the
  range. **Auto** leaves out the outliers (0.5 % of the cells at each end), **Full** spans every
  value, **Style** goes back to the style's own range. The colour range stays the same while
  you zoom.
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
- **Many curves** (more than 30 on screen) are drawn together as one picture, which is much faster;
  their lines are then not smoothed (antialiased), so they look a little sharper-edged. Choose a
  few traces to see them drawn as in a figure.
- Zoomed in far enough, every cell or point is drawn as stored ("every cell shown").

Cursor values never come from the picture: they are read from the file's data.

## What is remembered, and where

The viewer remembers how you explored each file: what was plotted, the chosen traces, the
operations, colours, scales, limits, the zoom and the cursors. Opening the file again shows the same.

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
shows the new data within about two seconds and **keeps your zoom, choices and cursors** (their
values are read again). If all the data
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
