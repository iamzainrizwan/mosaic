"""mosaic: tile live app windows onto one 1920x1080 stage and share that.

Two windows:
  control  - pool of captured windows, layouts, editable live preview
  output   - the clean stage; park it on another workspace (F11) and share it
"""
from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from . import model  # noqa: E402
from .canvas import Canvas  # noqa: E402
from .live import Stream  # noqa: E402
from .portal import ScreenCast  # noqa: E402

APP_ID = "io.github.iamzainrizwan.mosaic"

CSS = """
.poolcard { padding: 8px; border-radius: 10px; background: alpha(currentColor, 0.06); }
.poolcard picture { border-radius: 6px; background: black; }
.tilebar { padding: 4px 8px; }
.hint { opacity: 0.6; }
"""


class Ctx:
    """Shared app state the widgets read from and report changes to."""

    def __init__(self) -> None:
        self.state = model.State.load()
        self.streams: dict[str, Stream] = {}
        self.casts: dict[str, ScreenCast] = {}
        self.selected = -1
        self.canvases: list[Canvas] = []
        self.on_select = []   # callbacks()
        self.on_pool = []     # callbacks()
        self.on_layouts = []  # callbacks()
        self.toast = lambda msg: print(msg, file=sys.stderr)

    def redraw(self) -> None:
        for c in self.canvases:
            c.queue_draw()

    def changed(self, save: bool = True) -> None:
        self.redraw()
        if save:
            self.state.save()

    def select(self, i: int) -> None:
        self.selected = i
        self.redraw()
        for cb in self.on_select:
            cb()

    def layouts_changed(self) -> None:
        self.selected = -1
        self.state.save()
        self.redraw()
        for cb in self.on_layouts + self.on_select:
            cb()

    def pool_changed(self) -> None:
        self.redraw()
        for cb in self.on_pool:
            cb()

    # ---- capture sessions ----
    def start_session(self, sess: model.Session, restoring: bool) -> None:
        cast = ScreenCast()
        self.casts[sess.id] = cast

        def ready(streams, open_remote, token):
            sess.token = token or sess.token
            for i, (node_id, _props) in enumerate(streams):
                while len(sess.names) <= i:
                    sess.names.append(f"window {self.state.next_window_number()}")
                if i in sess.hidden:
                    continue
                try:
                    fd = open_remote()  # one pipewire connection per window
                except GLib.Error as e:
                    self.toast(f"couldn't open {sess.names[i]}: {e.message}")
                    continue
                st = Stream(sess.src_id(i), fd, node_id)
                os.close(fd)
                st.connect("frame", self._on_frame)
                st.connect("ended", self._on_ended)
                self.streams[st.src_id] = st
            if sess not in self.state.sessions:
                self.state.sessions.append(sess)
            self.state.save()
            self.pool_changed()

        def fail(msg):
            self.casts.pop(sess.id, None)
            what = ", ".join(sess.names) or "those windows"
            self.toast(f"couldn't reconnect {what}: add them again" if restoring else msg)

        cast.start(sess.token if restoring else "", ready, fail)

    def add_windows(self) -> None:
        self.start_session(model.Session(), restoring=False)

    def restore_all(self) -> None:
        for sess in self.state.sessions:
            if sess.token:
                self.start_session(sess, restoring=True)

    def forget(self, src: str) -> None:
        st = self.streams.pop(src, None)
        if st:
            st.stop()
        sid, _, i = src.partition(":")
        sess = self.state.session(sid)
        if sess and i.isdigit() and int(i) not in sess.hidden:
            sess.hidden.append(int(i))
            if all(sess.src_id(k) not in self.streams for k in range(len(sess.names))):
                cast = self.casts.pop(sess.id, None)
                if cast:
                    cast.close()
                self.state.sessions.remove(sess)
        self.state.save()
        self.pool_changed()

    def _on_frame(self, st: Stream) -> None:
        if any(t.src == st.src_id for t in self.state.layout().tiles):
            self.redraw()

    def _on_ended(self, st: Stream) -> None:
        self.streams.pop(st.src_id, None)
        self.toast(f"{self.state.name_of(st.src_id)} was closed")
        self.pool_changed()


# ---------------------------------------------------------------- output window

class OutputWindow(Gtk.Window):
    def __init__(self, app: Adw.Application, ctx: Ctx) -> None:
        super().__init__(application=app, title="mosaic output")
        self.set_default_size(1280, 720)
        self.set_hide_on_close(True)
        canvas = Canvas(ctx, editable=False)
        ctx.canvases.append(canvas)
        self.set_child(canvas)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        dbl = Gtk.GestureClick()
        dbl.connect("pressed", lambda _g, n, *_: n == 2 and self.toggle_fs())
        canvas.add_controller(dbl)

    def toggle_fs(self) -> None:
        self.unfullscreen() if self.is_fullscreen() else self.fullscreen()

    def _key(self, _c, keyval, *_):
        if keyval == Gdk.KEY_F11:
            self.toggle_fs()
            return True
        if keyval == Gdk.KEY_Escape and self.is_fullscreen():
            self.unfullscreen()
            return True
        return False


# ---------------------------------------------------------------- control window

def _icon_button(icon: str, tip: str, cb) -> Gtk.Button:
    b = Gtk.Button(icon_name=icon, tooltip_text=tip)
    b.add_css_class("flat")
    b.connect("clicked", lambda *_: cb())
    return b


class ControlWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, ctx: Ctx, output: OutputWindow) -> None:
        super().__init__(application=app, title="mosaic")
        self.ctx, self.output = ctx, output
        self.set_default_size(1200, 800)

        self.toasts = Adw.ToastOverlay()
        ctx.toast = lambda msg: self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(msg)))

        header = Adw.HeaderBar()
        add = Gtk.Button(label="Add windows", tooltip_text="Pick one or more windows to capture")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: ctx.add_windows())
        header.pack_start(add)
        header.pack_end(_icon_button("video-display-symbolic", "Show the output window (share that one)",
                                     output.present))

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(self._sidebar())
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body.append(self._main())

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(body)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

        ctx.on_layouts.append(self._fill_layouts)
        ctx.on_pool.append(self._fill_pool)
        ctx.on_select.append(self._sync_tilebar)
        self._fill_layouts()
        self._fill_pool()
        self._sync_tilebar()

    # ---- layouts sidebar ----
    def _sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=220)
        title = Gtk.Label(label="Layouts", xalign=0, margin_start=14, margin_top=12, margin_bottom=6)
        title.add_css_class("heading")
        box.append(title)
        self.layout_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.layout_list.add_css_class("navigation-sidebar")
        self.layout_list.connect("row-selected", self._layout_picked)
        sc = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_child(self.layout_list)
        box.append(sc)
        acts = Gtk.Box(spacing=2, margin_start=6, margin_end=6, margin_bottom=6, margin_top=6)
        acts.append(_icon_button("list-add-symbolic", "New layout", self._new_layout))
        acts.append(_icon_button("edit-copy-symbolic", "Duplicate layout", self._dup_layout))
        acts.append(_icon_button("document-edit-symbolic", "Rename layout", self._rename_layout))
        acts.append(_icon_button("user-trash-symbolic", "Delete layout", self._delete_layout))
        box.append(acts)
        return box

    def _fill_layouts(self) -> None:
        self._filling = True
        self.layout_list.remove_all()
        cur = self.ctx.state.layout()
        for l in self.ctx.state.layouts:
            row = Gtk.ListBoxRow()
            row.lid = l.id
            row.set_child(Gtk.Label(label=l.name, xalign=0, ellipsize=Pango.EllipsizeMode.END, margin_start=6, margin_top=6,
                                    margin_bottom=6))
            self.layout_list.append(row)
            if l.id == cur.id:
                self.layout_list.select_row(row)
        self._filling = False

    def _layout_picked(self, _lb, row) -> None:
        if self._filling or row is None or row.lid == self.ctx.state.current:
            return
        self.ctx.state.current = row.lid
        self.ctx.layouts_changed()

    def _new_layout(self) -> None:
        self.ctx.state.add_layout()
        self.ctx.layouts_changed()

    def _dup_layout(self) -> None:
        self.ctx.state.add_layout(copy_from=self.ctx.state.layout())
        self.ctx.layouts_changed()

    def _rename_layout(self) -> None:
        lay = self.ctx.state.layout()
        entry = Gtk.Entry(text=lay.name, activates_default=True)
        dlg = Adw.MessageDialog(transient_for=self, heading="Rename layout")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Rename")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def done(_d, resp):
            name = entry.get_text().strip()
            if resp == "ok" and name:
                lay.name = name
                self.ctx.layouts_changed()

        dlg.connect("response", done)
        dlg.present()

    def _delete_layout(self) -> None:
        if len(self.ctx.state.layouts) < 2:
            self.ctx.toast("that's the only layout")
            return
        lay = self.ctx.state.layout()
        dlg = Adw.MessageDialog(transient_for=self, heading=f"Delete “{lay.name}”?")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(_d, resp):
            if resp == "delete":
                self.ctx.state.delete_layout(lay.id)
                self.ctx.layouts_changed()

        dlg.connect("response", done)
        dlg.present()

    # ---- main area: tile bar, preview, pool ----
    def _main(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)

        bar = Gtk.Box(spacing=4)
        bar.add_css_class("tilebar")
        self.tile_label = Gtk.Label(xalign=0, hexpand=True)
        self.tile_label.add_css_class("hint")
        bar.append(self.tile_label)
        self.tile_btns = [
            _icon_button("go-top-symbolic", "Bring to front", self._front),
            _icon_button("view-fullscreen-symbolic", "Fill the stage", self._fill),
            _icon_button("window-close-symbolic", "Remove from this layout (Delete)", self._remove),
        ]
        for b in self.tile_btns:
            bar.append(b)
        box.append(bar)

        self.preview = Canvas(self.ctx, editable=True)
        self.ctx.canvases.append(self.preview)
        box.append(self.preview)

        pool_head = Gtk.Box(margin_start=14, margin_end=14, margin_top=8)
        lbl = Gtk.Label(label="Windows", xalign=0, hexpand=True)
        lbl.add_css_class("heading")
        pool_head.append(lbl)
        tip = Gtk.Label(label="drag onto the stage to place, onto a tile to swap")
        tip.add_css_class("hint")
        pool_head.append(tip)
        box.append(pool_head)

        self.pool = Gtk.Box(spacing=10, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        sc = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, height_request=170)
        sc.set_child(self.pool)
        box.append(sc)
        return box

    def _sync_tilebar(self) -> None:
        lay = self.ctx.state.layout()
        i = self.ctx.selected
        ok = 0 <= i < len(lay.tiles)
        self.tile_label.set_label(self.ctx.state.name_of(lay.tiles[i].src) if ok
                                  else "click a tile to select it")
        for b in self.tile_btns:
            b.set_sensitive(ok)

    def _sel_tile(self):
        lay = self.ctx.state.layout()
        i = self.ctx.selected
        return (lay, i) if 0 <= i < len(lay.tiles) else (lay, -1)

    def _front(self) -> None:
        lay, i = self._sel_tile()
        if i >= 0:
            lay.tiles.append(lay.tiles.pop(i))
            self.ctx.select(len(lay.tiles) - 1)
            self.ctx.changed()

    def _fill(self) -> None:
        lay, i = self._sel_tile()
        if i >= 0:
            t = lay.tiles[i]
            t.x, t.y, t.w, t.h = 0, 0, model.CANVAS_W, model.CANVAS_H
            self.ctx.changed()

    def _remove(self) -> None:
        lay, i = self._sel_tile()
        if i >= 0:
            lay.tiles.pop(i)
            self.ctx.select(-1)
            self.ctx.changed()

    def _key(self, _c, keyval, *_):
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and self.preview.has_focus():
            self._remove()
            return True
        return False

    def _fill_pool(self) -> None:
        while (c := self.pool.get_first_child()) is not None:
            self.pool.remove(c)
        if not self.ctx.streams:
            empty = Gtk.Label(label="No windows yet. Open your apps, press “Add windows” and tick the ones you want.",
                              hexpand=True, wrap=True)
            empty.add_css_class("hint")
            self.pool.append(empty)
            return
        for src, st in self.ctx.streams.items():
            self.pool.append(self._card(src, st))

    def _card(self, src: str, st: Stream) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("poolcard")
        pic = Gtk.Picture(paintable=st.paintable, content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True,
                          width_request=176, height_request=99)
        card.append(pic)

        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY)

        def prepare(*_):
            v = GObject.Value()
            v.init(GObject.TYPE_STRING)
            v.set_string(src)
            return Gdk.ContentProvider.new_for_value(v)

        drag.connect("prepare", prepare)
        drag.connect("drag-begin", lambda s, _d: s.set_icon(Gtk.WidgetPaintable.new(pic), 0, 0))
        pic.add_controller(drag)

        row = Gtk.Box(spacing=2)
        name = Gtk.EditableLabel(text=self.ctx.state.name_of(src), hexpand=True, width_chars=10)

        def renamed(lbl, _p):
            if not lbl.get_editing():
                self.ctx.state.rename(src, lbl.get_text().strip() or "window")
                self.ctx.changed()
                self._sync_tilebar()

        name.connect("notify::editing", renamed)
        row.append(name)
        row.append(_icon_button("list-add-symbolic", "Add to this layout", lambda: self._add_tile(src)))
        row.append(_icon_button("window-close-symbolic", "Stop capturing this window",
                                lambda: self.ctx.forget(src)))
        card.append(row)
        return card

    def _add_tile(self, src: str) -> None:
        lay = self.ctx.state.layout()
        st = self.ctx.streams.get(src)
        lay.tiles.append(model.Tile(src, *model.place_new(st.paintable.aspect() if st else 16 / 9)))
        self.ctx.select(len(lay.tiles) - 1)
        self.ctx.changed()


# ---------------------------------------------------------------- app

class MosaicApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.ctx: Ctx | None = None
        self.control: ControlWindow | None = None

    def do_activate(self) -> None:
        if self.control:
            self.control.present()
            return
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        self.ctx = Ctx()
        output = OutputWindow(self, self.ctx)
        self.control = ControlWindow(self, self.ctx, output)
        self.control.connect("close-request", lambda *_: self.quit() or False)
        output.present()
        self.control.present()
        self.ctx.restore_all()

    def do_shutdown(self) -> None:
        if self.ctx:
            for st in self.ctx.streams.values():
                st.stop()
        Adw.Application.do_shutdown(self)


def main() -> int:
    return MosaicApp().run(sys.argv)
