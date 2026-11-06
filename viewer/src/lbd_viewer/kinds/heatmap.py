"""Maps in an Explore session: the code stays in explore.py and reading.py."""

from lbd.plot import render as rnd

from . import Interaction


class Heatmap(Interaction):
    name = kind = "heatmap"
    model = rnd.MapModel
    operations = True
    strips = "cuts"

    def setup(self):
        self.s._setup_map()

    def limits(self):
        return self.s._map_limits()

    def apply(self, settings, chosen, clim):
        self.s._apply_map(settings, chosen if self.s.base_kind == "heatmap" else None, clim)

    def picture(self, pxe, pye, stat, draft, w, h):
        r = self.s.pyramid.raster(pxe, pye, stat)
        self.s.image.set_data(r.image)
        return r.note(), r.reduced

    def read(self, cursor, kind, geo):
        from .. import reading

        return reading._map_cursor(self.s, cursor, kind)

    def pick(self, px, py):
        s = self.s
        xd, yd = s.ax.transData.inverted().transform([(px, s.fig.bbox.height - py)])[0]
        return s._pick_cell(xd, yd)

    def find(self, what, xlim, ylim, trace):
        from .. import reading

        return reading._find_map(self.s, what, xlim, ylim)

    def cuts(self, cursor, kind, geo):
        from .. import reading

        return reading._cuts(self.s, cursor, kind, geo)

    def values(self):
        return self.s._finite_z()


INTERACTION = Heatmap
