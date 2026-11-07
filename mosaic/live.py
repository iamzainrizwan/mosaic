"""One captured window: a pipewiresrc pipeline feeding a shared Gdk.Paintable.

The same paintable is drawn by the pool thumbnail, the preview and the output,
so each frame is decoded once and only re-drawn by GTK.
"""
from __future__ import annotations

import os

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Graphene, Gst, GstVideo  # noqa: E402

Gst.init(None)

_PLACEHOLDER = Gdk.RGBA()
_PLACEHOLDER.parse("#2a2c33")


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
        self._pending: Gdk.Texture | None = None
        self._scheduled = False
        self._caps = None
        self._info = None
        # each pipewiresrc gets its own dup of the remote fd: it closes it on teardown
        self.pipeline = Gst.parse_launch(
            f"pipewiresrc fd={os.dup(fd)} path={node_id} do-timestamp=true keepalive-time=1000 "
            "! videoconvert ! video/x-raw,format=BGRA "
            "! appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false")
        sink = self.pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_sample)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_end)
        bus.connect("message::eos", self._on_end)
        self.pipeline.set_state(Gst.State.PLAYING)

    # streaming thread
    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        caps = sample.get_caps()
        if self._caps is None or not caps.is_equal(self._caps):
            self._caps, self._info = caps, GstVideo.VideoInfo.new_from_caps(caps)
        info, buf = self._info, sample.get_buffer()
        data = buf.extract_dup(0, buf.get_size())
        tex = Gdk.MemoryTexture.new(info.width, info.height, Gdk.MemoryFormat.B8G8R8A8,
                                    GLib.Bytes.new(data), info.stride[0])
        self._pending = tex
        if not self._scheduled:
            self._scheduled = True
            GLib.idle_add(self._flush)
        return Gst.FlowReturn.OK

    # main thread
    def _flush(self):
        self._scheduled = False
        tex, self._pending = self._pending, None
        if tex is not None and self.alive:
            self.paintable.set_texture(tex)
            self.emit("frame")
        return GLib.SOURCE_REMOVE

    def _on_end(self, *_):
        if self.alive:
            self.stop()
            self.emit("ended")

    def stop(self) -> None:
        self.alive = False
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.get_bus().remove_signal_watch()
