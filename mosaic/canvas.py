"""The 1920x1080 stage, drawn scaled-to-fit.

Used twice: read-only in the output window (what you share) and editable in
the control window (drag to move, bottom-right corner to resize, drop a window
from the pool onto it to add or swap).
"""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, GObject, Graphene, Gsk, Gtk  # noqa: E402

from . import model  # noqa: E402
from .model import CANVAS_H, CANVAS_W  # noqa: E402


def _rgba(s: str) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.parse(s)
    return c


BLACK, DESK = _rgba("#000000"), _rgba("#17181c")
EDGE, ACCENT = _rgba("rgba(255,255,255,0.18)"), _rgba("#78aeff")
EMPTY, LABEL_BG, LABEL_FG = _rgba("#2a2c33"), _rgba("rgba(0,0,0,0.6)"), _rgba("#e8e9ec")
EDGE_TEXT = _rgba("rgba(255,255,255,0.45)")
HANDLE = 16  # widget px
LOGO_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                         "io.github.iamzainrizwan.mosaic.svg")
_logo = None


def logo() -> Gdk.Texture | None:
    global _logo
    if _logo is None:
        try:
            _logo = Gdk.Texture.new_from_filename(LOGO_FILE)
        except Exception:  # noqa: BLE001  (missing file or no svg loader: just skip the logo)
            _logo = False
    return _logo or None


def _rect(x, y, w, h) -> Graphene.Rect:
    r = Graphene.Rect()
    r.init(x, y, w, h)
    return r


def _pt(x, y) -> Graphene.Point:
    p = Graphene.Point()
    p.init(x, y)
    return p


class Canvas(Gtk.Widget):
    def __init__(self, ctx, editable: bool) -> None:
        super().__init__()
        self.ctx = ctx
        self.editable = editable
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_size_request(320, 180)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        if editable:
            self._setup_editing()

    # ---- geometry ----
    def geom(self) -> tuple[float, float, float]:
        W, H = self.get_width(), self.get_height()
        pad = 12 if self.editable else 0
        s = max(0.01, min((W - 2 * pad) / CANVAS_W, (H - 2 * pad) / CANVAS_H))
        return s, (W - CANVAS_W * s) / 2, (H - CANVAS_H * s) / 2

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        s, ox, oy = self.geom()
        return (x - ox) / s, (y - oy) / s

    # ---- drawing ----
    def do_snapshot(self, snap: Gtk.Snapshot) -> None:
        W, H = self.get_width(), self.get_height()
        s, ox, oy = self.geom()
        snap.append_color(DESK if self.editable else BLACK, _rect(0, 0, W, H))
        stage = _rect(ox, oy, CANVAS_W * s, CANVAS_H * s)
        snap.append_color(BLACK, stage)
        lay = self.ctx.state.layout()
        if not lay.tiles:
            self._empty(snap, ox, oy, CANVAS_W * s, CANVAS_H * s)
        snap.push_clip(stage)
        for i, t in enumerate(lay.tiles):
            x, y, w, h = ox + t.x * s, oy + t.y * s, t.w * s, t.h * s
            st = self.ctx.streams.get(t.src)
            tex = st.paintable.tex if st and st.alive else None
            if tex is not None:
                dx, dy, dw, dh = model.fit_contain(tex.get_width(), tex.get_height(), w, h)
                snap.save()
                snap.translate(_pt(x + dx, y + dy))
                st.paintable.snapshot(snap, dw, dh)
                snap.restore()
            elif self.editable:
                snap.append_color(EMPTY, _rect(x, y, w, h))
            if self.editable:
                self._chrome(snap, i, t, x, y, w, h, missing=tex is None)
        snap.pop()

    def _empty(self, snap, x, y, w, h) -> None:
        """mosaic logo (plus a hint in the editor) while the layout has no tiles."""
        tex = logo()
        size = min(w, h) * 0.22
        cy = y + h / 2 - (size * 0.15 if self.editable else 0)
        if tex is not None:
            snap.save()
            snap.translate(_pt(x + (w - size) / 2, cy - size / 2))
            tex.snapshot(snap, size, size)
            snap.restore()
        if self.editable:
            lay = self.create_pango_layout("mosaic: drag a window here from the pool")
            lw, lh = lay.get_pixel_size()
            snap.save()
            snap.translate(_pt(x + (w - lw) / 2, cy + size / 2 + 12))
            snap.append_layout(lay, EDGE_TEXT)
            snap.restore()

    def _chrome(self, snap, i, t, x, y, w, h, missing) -> None:
        sel = i == self.ctx.selected
        col, bw = (ACCENT, 2) if sel else (EDGE, 1)
        rr = Gsk.RoundedRect()
        rr.init_from_rect(_rect(x, y, w, h), 0)
        snap.append_border(rr, [bw] * 4, [col] * 4)
        name = self.ctx.state.name_of(t.src) + ("  (closed)" if missing and t.src not in self.ctx.streams else "")
        lay = self.create_pango_layout(name)
        lw, lh = lay.get_pixel_size()
        snap.append_color(LABEL_BG, _rect(x + 4, y + 4, lw + 12, lh + 6))
        snap.save()
        snap.translate(_pt(x + 10, y + 7))
        snap.append_layout(lay, LABEL_FG)
        snap.restore()
        if sel:
            snap.append_color(ACCENT, _rect(x + w - HANDLE / 1.5, y + h - HANDLE / 1.5, HANDLE / 1.5, HANDLE / 1.5))

    # ---- editing ----
    def _setup_editing(self) -> None:
        self.set_focusable(True)
        self._drag = None
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._begin)
        g.connect("drag-update", self._update)
        g.connect("drag-end", self._end)
        self.add_controller(g)
        m = Gtk.EventControllerMotion()
        m.connect("motion", self._hover)
        self.add_controller(m)
        d = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY)
        d.connect("drop", self._drop)
        self.add_controller(d)

    def _corner(self, t: model.Tile, x: float, y: float) -> bool:
        s, ox, oy = self.geom()
        return abs(ox + (t.x + t.w) * s - x) < HANDLE and abs(oy + (t.y + t.h) * s - y) < HANDLE

    def _pick(self, x: float, y: float) -> tuple[int, str]:
        lay = self.ctx.state.layout()
        sel = self.ctx.selected
        if 0 <= sel < len(lay.tiles) and self._corner(lay.tiles[sel], x, y):
            return sel, "resize"
        i = lay.hit(*self.to_canvas(x, y))
        if i >= 0 and self._corner(lay.tiles[i], x, y):
            return i, "resize"
        return i, "move"

    def _hover(self, _c, x, y) -> None:
        i, mode = self._pick(x, y)
        self.set_cursor_from_name(None if i < 0 else ("se-resize" if mode == "resize" else "move"))

    def _begin(self, _g, x, y) -> None:
        self.grab_focus()
        i, mode = self._pick(x, y)
        self.ctx.select(i)
        if i < 0:
            self._drag = None
            return
        t = self.ctx.state.layout().tiles[i]
        self._drag = (i, mode, t.x, t.y, t.w, t.h)

    def _update(self, _g, dx, dy) -> None:
        if not self._drag:
            return
        i, mode, x0, y0, w0, h0 = self._drag
        s = self.geom()[0]
        lay = self.ctx.state.layout()
        if i >= len(lay.tiles):
            return
        t = lay.tiles[i]
        if mode == "move":
            t.x, t.y = model.snap_move(lay, i, x0 + dx / s, y0 + dy / s)
        else:
            t.w, t.h = model.snap_resize(lay, i, w0 + dx / s, w0 / h0)
        self.ctx.changed(save=False)

    def _end(self, *_):
        if self._drag:
            self._drag = None
            self.ctx.changed()

    def _drop(self, _t, value, x, y) -> bool:
        src = str(value)
        lay = self.ctx.state.layout()
        cx, cy = self.to_canvas(x, y)
        i = lay.hit(cx, cy)
        if i >= 0:
            lay.tiles[i].src = src  # swap the window in, keep the slot
        else:
            st = self.ctx.streams.get(src)
            aspect = st.paintable.aspect() if st else 16 / 9
            lay.tiles.append(model.Tile(src, *model.place_new(aspect, cx, cy)))
            i = len(lay.tiles) - 1
        self.ctx.select(i)
        self.ctx.changed()
        return True
