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

/** The look options of curves, in the order they are shown. */
const CURVE_LOOKS: ((p: KindControlsProps) => ReactElement | null)[] = [];
