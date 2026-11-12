import type { ReactElement } from "react";
import type { KindControlsProps } from "./plotKinds";

/**
 * Curves' look options (Display, 16.47). Curves' Data part (values, axes, one curve per …) lives in
 * ExploreTab and FileView, as it always has. Each option below is its own small component, so
 * that options can be added one at a time.
 */
export function CurveDisplay(props: KindControlsProps) {
  const parts = CURVE_LOOKS.map((Part, i) => <Part key={i} {...props} />);
  return parts.length ? <>{parts}</> : null;
}

/** Grid lines at the ticks: as the style says until ticked or unticked here (`options.grid`). */
export function GridTick({ resolved, update }: KindControlsProps) {
  const on = (resolved.options?.grid as boolean | undefined) ?? !!resolved.style_grid;
  return (
    <label className="check" title="Grid lines at the ticks. Their colour and width are the style's">
      <input type="checkbox" checked={on} onChange={(e) => update({ options: { ...(resolved.options ?? {}), grid: e.target.checked } })} />
      Grid
    </label>
  );
}

/** One stored unit as long both ways (`options.equal`); linear axes only. */
export function EqualAxes({ resolved, update, settings, page }: KindControlsProps) {
  const xs = page === "explore" ? settings?.xscale ?? resolved.x_scale : resolved.x_scale;
  const ys = page === "explore" ? settings?.yscale ?? resolved.y_scale : resolved.y_scale;
  const log = xs === "log" || ys === "log";
  return (
    <label className="check" title={log ? "Only on linear axes: untick Log first" : "The same scale both ways, so that a circle looks like a circle"}>
      <input type="checkbox" checked={!!resolved.options?.equal && !log} disabled={log} onChange={(e) => update({ options: { ...(resolved.options ?? {}), equal: e.target.checked } })} />
      Equal axes
    </label>
  );
}

/** Show points (16.39): a small dot on the stored points; off by default. */
function ShowPoints({ resolved, update }: KindControlsProps) {
  return (
    <label className="check" title="A small dot on every stored point. In Explore, one dot per pixel that holds points: dots in one pixel would cover each other">
      <input type="checkbox" checked={!!resolved.options?.points} onChange={(e) => update({ options: { ...(resolved.options ?? {}), points: e.target.checked } })} />
      Show points
    </label>
  );
}

/** The look options of curves, in the order they are shown. */
const CURVE_LOOKS: ((p: KindControlsProps) => ReactElement | null)[] = [GridTick, EqualAxes, ShowPoints];
