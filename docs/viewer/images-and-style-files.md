# Images and style files

## Images

Clicking an image in the folder panel shows it, **view only**: the viewer never changes images.
Below the image you see:

| Item | Meaning |
|---|---|
| Format, pixels | e.g. PNG, 2007 × 1464. |
| Printed size | Pixels ÷ dpi, in mm, when the file stores its dpi. For figures exported by LBD this equals the style's size, e.g. 85 × 64 mm. |
| Resolution | The stored dpi. |
| Colour | Colour mode and bit depth, e.g. RGBA, 8 bit; 16-bit camera TIFFs are shown with their contrast stretched. |
| Frames | For animated GIFs and multi-page TIFFs (the first is shown). |
| File size, modified | |
| Embedded information | Text stored in the file. For example, figures exported by LBD record which program, version and data file made them; photos show camera EXIF data. |

**Zoom: 100 %** shows the image at its printed size when the dpi is known. TIFF and BMP files
are converted for display only. SVG files are shown as images, with scripts blocked.

## Style files

Clicking a `.lbd.json` [style file](../styles/files-and-export.md#style-files) shows:
- its name, description, size and font;
- a **preview**: the first data file open in another tab, plotted in this style;
- **All settings** as JSON.

**Import as preset** adds it to the Styles page under a name you choose. A preset with that name
is never overwritten.
