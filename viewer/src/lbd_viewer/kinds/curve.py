"""Curves in an Explore session: the code stays in explore.py and reading.py."""

from lbd.plot import render as rnd

from . import Interaction


class Curve(Interaction):
    name = kind = "curve"
    model = rnd.CurveModel
    operations = True

    def setup(self):
        self.s.model = self.s._units_apart(self.s.model)
        self.s._setup_curves()
        self.s.ax.set_aspect("auto")                     # equal axes: `frame` widens the view itself

    def limits(self):
        return self.s._curve_limits()

    def apply(self, settings, chosen, clim):
        self.s._apply_curves(chosen)

    def picture(self, pxe, pye, stat, draft, w, h):
        return self.s._curve_picture(pxe, draft, w, h)

    def read(self, cursor, kind, geo):
        from .. import reading

        return reading._curve_cursor(self.s, cursor, kind, geo, **self.line_options)

    def pick(self, px, py):
        return self.s._pick_curve(px, py)

    def find(self, what, xlim, ylim, trace):
        from .. import reading

        return reading._find_curve(self.s, what, xlim, trace)


INTERACTION = Curve
