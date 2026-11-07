"""One captured window: a pipewiresrc pipeline feeding a shared Gdk.Paintable.

The same paintable is drawn by the pool thumbnail, the preview and the output,
so each frame is copied once and only re-drawn by GTK.

Cost control:
  - frames come straight from PipeWire as BGRx/BGRA, no videoconvert pass
    (falls back to videoconvert only if the compositor offers something else)
  - at most MAX_FPS frames per second are copied; the rest are dropped before
    any copy happens
  - windows that aren't on the stage are paused (PipeWire stops asking GNOME
    to render them) and only grab a single frame now and then for the pool
"""
from __future__ import annotations

import os
import time

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GLib, GObject, Graphene, Gst, GstVideo  # noqa: E402

Gst.init(None)

MAX_FPS = 30

_PLACEHOLDER = Gdk.RGBA()
_PLACEHOLDER.parse("#2a2c33")

_FAST = ("pipewiresrc fd={fd} path={node} do-timestamp=true keepalive-time=1000 "
         "! video/x-raw,format=(string){{BGRx,BGRA}} "
         "! appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false")
_SLOW = ("pipewiresrc fd={fd} path={node} do-timestamp=true keepalive-time=1000 "
         "! videoconvert ! video/x-raw,format=BGRA "
         "! appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false")

_GDK_FORMAT = {
    GstVideo.VideoFormat.BGRX: Gdk.MemoryFormat.B8G8R8X8,
    GstVideo.VideoFormat.BGRA: Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
}


def pixbuf_grey(pb) -> list[int]:
    """Greyscale values of a small pixbuf, row by row."""
    w, h, n, rs = pb.get_width(), pb.get_height(), pb.get_n_channels(), pb.get_rowstride()
    px = pb.get_pixels()
    return [(px[y * rs + x * n] * 3 + px[y * rs + x * n + 1] * 6 + px[y * rs + x * n + 2]) // 10
            for y in range(h) for x in range(w)]


class LivePaintable(GObject.Object, Gdk.Paintable):
    def __init__(self) -> None:
        super().__init__()
        self.tex: Gdk.Texture | None = None

    def do_snapshot(self, snapshot, width, height):
        if self.tex is not None:
            self.tex.snapshot(snapshot, width, height)
        else:
            r = Graphene.Rect()
            r.init(0, 0, width, height)
            snapshot.append_color(_PLACEHOLDER, r)

    def do_get_intrinsic_width(self):
        return self.tex.get_width() if self.tex else 0

    def do_get_intrinsic_height(self):
        return self.tex.get_height() if self.tex else 0

    def do_get_intrinsic_aspect_ratio(self):
        return self.tex.get_width() / self.tex.get_height() if self.tex else 0.0

    def do_get_flags(self):
        return 0

    def aspect(self) -> float:
        return self.do_get_intrinsic_aspect_ratio() or 16 / 9

    def set_texture(self, tex: Gdk.Texture) -> None:
        old = self.tex
        self.tex = tex
        if old is None or old.get_width() != tex.get_width() or old.get_height() != tex.get_height():
            self.invalidate_size()
        self.invalidate_contents()


class Stream(GObject.Object):
    """Emits 'frame' on the main thread for every new frame, 'ended' when the window goes."""

    __gsignals__ = {
        "frame": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "ended": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, src_id: str, fd: int, node_id: int) -> None:
        super().__init__()
        self.src_id = src_id
        self.paintable = LivePaintable()
        self.alive = True
        self.active = True        # on the stage: full rate. off: paused, occasional snapshot
        self._one_shot = False
        self._pending: Gdk.Texture | None = None
        self._scheduled = False
        self._caps = None
        self._info = None
        self._fmt = None
        self._last = 0.0
        self._got_frame = False
        self._node = node_id
        self._spare_fd = os.dup(fd)  # kept for one rebuild with videoconvert, if needed
        self.pipeline = None
        self._build(_FAST, os.dup(fd))

    def _build(self, template: str, fd: int) -> None:
        self.pipeline = Gst.parse_launch(template.format(fd=fd, node=self._node))
        self.pipeline.get_by_name("sink").connect("new-sample", self._on_sample)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        bus.connect("message::eos", self._on_end)
        self.pipeline.set_state(Gst.State.PLAYING if (self.active or self._one_shot) else Gst.State.PAUSED)

    # ---- streaming thread ----
    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        now = time.monotonic()
        if now - self._last < 1 / MAX_FPS and not self._one_shot:
            return Gst.FlowReturn.OK  # over the frame cap: drop before copying anything
        self._last = now
        caps = sample.get_caps()
        if self._caps is None or not caps.is_equal(self._caps):
            info = GstVideo.VideoInfo.new_from_caps(caps)
            self._caps, self._info = caps, info
            self._fmt = _GDK_FORMAT.get(info.finfo.format, Gdk.MemoryFormat.B8G8R8A8)
        info, buf = self._info, sample.get_buffer()
        tex = Gdk.MemoryTexture.new(info.width, info.height, self._fmt,
                                    GLib.Bytes.new(buf.extract_dup(0, buf.get_size())), info.stride[0])
        self._pending = tex
        if not self._scheduled:
            self._scheduled = True
            GLib.idle_add(self._flush)
        return Gst.FlowReturn.OK

    # ---- main thread ----
    def _flush(self):
        self._scheduled = False
        tex, self._pending = self._pending, None
        if tex is not None and self.alive:
            self._got_frame = True
            self.paintable.set_texture(tex)
            self.emit("frame")
            if self._one_shot and not self.active:
                self._one_shot = False
                self.pipeline.set_state(Gst.State.PAUSED)
        return GLib.SOURCE_REMOVE

    def set_active(self, on: bool) -> None:
        if not self.alive or on == self.active:
            return
        self.active = on
        if not on and not self._got_frame:
            self._one_shot = True  # keep going until the first frame, then pause
            return
        self._one_shot = False
        self.pipeline.set_state(Gst.State.PLAYING if on else Gst.State.PAUSED)

    def grey_thumb(self, w: int, h: int) -> list[int] | None:
        """Current frame squashed to w x h greyscale (for matching against window thumbnails)."""
        tex = self.paintable.tex
        if tex is None:
            return None
        from gi.repository import GdkPixbuf
        dl = Gdk.TextureDownloader.new(tex)
        dl.set_format(Gdk.MemoryFormat.R8G8B8A8)
        data, stride = dl.download_bytes()
        pb = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, True, 8,
                                             tex.get_width(), tex.get_height(), stride)
        return pixbuf_grey(pb.scale_simple(w, h, GdkPixbuf.InterpType.HYPER))

    def snapshot(self) -> None:
        """Grab a single fresh frame for a paused (off-stage) window's thumbnail."""
        if self.alive and not self.active and not self._one_shot:
            self._one_shot = True
            self.pipeline.set_state(Gst.State.PLAYING)

    def _teardown(self) -> None:
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.get_bus().remove_signal_watch()

    def _on_error(self, _bus, msg):
        # compositor offered a format we didn't ask for: retry once with videoconvert
        if self.alive and not self._got_frame and self._spare_fd is not None:
            fd, self._spare_fd = self._spare_fd, None
            self._teardown()
            self._build(_SLOW, fd)
            return
        self._on_end()

    def _on_end(self, *_):
        if self.alive:
            self.stop()
            self.emit("ended")

    def stop(self) -> None:
        self.alive = False
        self._teardown()
        if self._spare_fd is not None:
            os.close(self._spare_fd)
            self._spare_fd = None
