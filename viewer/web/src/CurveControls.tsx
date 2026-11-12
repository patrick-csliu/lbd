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
const CURVE_LOOKS: ((p: KindControlsProps) => ReactElement | null)[] = [ShowPoints];
