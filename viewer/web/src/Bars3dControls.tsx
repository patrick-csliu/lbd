import { ComplexSelect } from "./KindFields";
import { GridAxes } from "./MatrixControls";
import type { KindControlsProps, PlotKind } from "./plotKinds";

/**
 * 3D bars' controls: the data as Matrix, and the angle. In Explore the angle belongs to the view (a
 * drag turns the picture, and the boxes follow it); on the Figure page it is a setting of the figure.
 */

function AngleBox({ label, value, low, high, onSet }: { label: string; value: number; low?: number; high?: number; onSet: (v: number) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        key={value}
        aria-label={label}
        type="number"
        step={5}
        min={low}
        max={high}
        defaultValue={Math.round(value * 10) / 10}
        onBlur={(e) => {
          const v = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(v) && v !== Math.round(value * 10) / 10) onSet(v);
        }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      />
    </label>
  );
}

/** Which value, rows and columns, complex mode (Data). */
function Bars3dControls({ info, resolved: r, update }: KindControlsProps) {
  const complex = info.values.find((v) => v.name === r.values?.[0])?.complex;
  return (
    <>
      <GridAxes info={info} r={r} update={update} kind="bars3d" />
      {complex && <ComplexSelect r={r} update={update} more={[["abs_phase", "Height |z|, colour the phase"]]} />}
    </>
  );
}

/** The angle the bars are seen from (Display, 16.47). */
function Bars3dDisplay({ resolved: r, update, page, angle, setAngle }: KindControlsProps) {
  const options = (r.options ?? {}) as { elev?: number; azim?: number };
  const onFigure = page === "figure";
  const elev = (onFigure ? options.elev : angle?.elev) ?? 35;
  const azim = (onFigure ? options.azim : angle?.azim) ?? -50;
  const set = (patch: { elev?: number; azim?: number }) => {
    if (onFigure) update({ options: { ...(r.options ?? {}), ...patch } });
    else setAngle?.(patch);
  };
  const toDefault = () => {
    if (onFigure) {
      const rest = { ...(r.options ?? {}) };
      delete rest.elev;
      delete rest.azim;
      delete rest.zoom;
      update({ options: rest });
    } else setAngle?.(null);
  };
  return (
    <>
      <AngleBox label="Elevation" value={elev} low={-90} high={90} onSet={(v) => set({ elev: Math.min(90, Math.max(-90, v)) })} />
      <AngleBox label="Azimuth" value={azim} onSet={(v) => set({ azim: v })} />
      <div className="field">
        <button onClick={toDefault} title="The style's angle">
          Default angle
        </button>
      </div>
    </>
  );
}

export const kindRow: PlotKind = {
  kind: "bars3d",
  explore: true,
  controls: Bars3dControls,
  display: Bars3dDisplay,
  cursorTypes: [],
  strips: null,
  darkInverted: false,
  openInFigure: true,
  cursorMark: "cell",
  axes: "3d",
  syncs: false,
  findButtons: false,
  ownData: true,
  scales: [],
  shapeOps: true,
};
