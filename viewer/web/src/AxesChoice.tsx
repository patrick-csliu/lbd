/**
 * The axes not drawn, for plots of points (Scatter, Histogram): one axis, or none, gives the colours;
 * every other axis is a slider (one step at a time) or All (its points all go in).
 */

export interface ChoiceAxis {
  name: string;
  label: string;
  length: number;
  elements?: string[] | null;
}

const SHORT = 32;

/** The starting choice: a short axis with texts for the colours, the longest axis All, the rest sliders. */
export function startingAxes(axes: ChoiceAxis[]): { color: string; all: string[] } {
  const named = axes.find((a) => a.elements && a.length <= SHORT);
  const rest = axes.filter((a) => a !== named);
  const longest = rest.reduce<ChoiceAxis | null>((best, a) => (!best || a.length > best.length ? a : best), null);
  return { color: named ? named.name : "none", all: longest ? [longest.name] : [] };
}

export function AxesChoice({ axes, color, all, drawn = [], onChange }: { axes: ChoiceAxis[]; color: string; all: string[]; drawn?: string[]; onChange: (patch: { color: string; all: string[] }) => void }) {
  const free = axes.filter((a) => !drawn.includes(a.name));
  const colours = color === "none" ? null : color;
  return (
    <div className="axes-choice" role="group" aria-label="Axes not drawn">
      <label className="field">
        <span>Colour by</span>
        <select aria-label="Colour by" value={color} onChange={(e) => onChange({ color: e.target.value, all: all.filter((a) => a !== e.target.value) })}>
          <option value="none">None</option>
          {free.map((a) => (
            <option key={a.name} value={a.name}>
              {a.label}
            </option>
          ))}
        </select>
      </label>
      {free
        .filter((a) => a.name !== colours)
        .map((a) => {
          const on = all.includes(a.name);
          return (
            <label key={a.name} className="check" title="All: its points all go in. Otherwise a slider shows one step at a time.">
              <input type="checkbox" checked={on} onChange={() => onChange({ color, all: on ? all.filter((x) => x !== a.name) : [...all, a.name] })} />
              All of {a.label}
            </label>
          );
        })}
    </div>
  );
}
