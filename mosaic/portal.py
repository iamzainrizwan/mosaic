"""xdg-desktop-portal ScreenCast client (window capture on Wayland).

One ScreenCast object = one portal session. The portal shows GNOME's picker
(multi-select allowed) unless a restore token brings back the same windows.
Everything is async on the GLib main loop; results come back via callbacks.
"""
from __future__ import annotations

import random

from gi.repository import Gio, GLib

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.ScreenCast"

SOURCE_WINDOW = 2
CURSOR_HIDDEN = 1
PERSIST_UNTIL_REVOKED = 2


def _token() -> str:
    return f"mosaic{random.randrange(1 << 30)}"


class ScreenCast:
    def __init__(self) -> None:
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.session_handle: str | None = None

    # ---- plumbing ----
    def _prop(self, name: str):
        try:
            v = self.bus.call_sync(BUS, PATH, "org.freedesktop.DBus.Properties", "Get",
                                   GLib.Variant("(ss)", (IFACE, name)), GLib.VariantType("(v)"),
                                   Gio.DBusCallFlags.NONE, 2000, None)
            return v.unpack()[0]
        except GLib.Error:
            return None

    def _request(self, method: str, make_args, cb) -> None:
        """Call a portal method that answers through a Request object's Response signal.

        make_args(handle_token) -> GLib.Variant; cb(ok: bool, results: dict)."""
        token = _token()
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        sub = 0

        def on_response(_conn, _sender, _obj, _iface, _sig, params):
            self.bus.signal_unsubscribe(sub)
            code, results = params.unpack()
            cb(code == 0, results)

        sub = self.bus.signal_subscribe(None, "org.freedesktop.portal.Request", "Response", path,
                                        None, Gio.DBusSignalFlags.NONE, on_response)

        def on_called(conn, res):
            try:
                conn.call_finish(res)
            except GLib.Error as e:
                self.bus.signal_unsubscribe(sub)
                cb(False, {"error": e.message})

        self.bus.call(BUS, PATH, IFACE, method, make_args(token), None,
                      Gio.DBusCallFlags.NONE, -1, None, on_called)

    # ---- the flow: CreateSession -> SelectSources -> Start -> OpenPipeWireRemote ----
    def start(self, restore_token: str, on_ready, on_fail) -> None:
        """on_ready(streams: list[(node_id, props)], fd: int, new_token: str); on_fail(msg)."""

        def created(ok, res):
            if not ok:
                return on_fail(res.get("error", "couldn't create a capture session"))
            self.session_handle = res["session_handle"]
            opts = {
                "types": GLib.Variant("u", SOURCE_WINDOW),
                "multiple": GLib.Variant("b", True),
                "persist_mode": GLib.Variant("u", PERSIST_UNTIL_REVOKED),
            }
            modes = self._prop("AvailableCursorModes")
            if modes and modes & CURSOR_HIDDEN:
                opts["cursor_mode"] = GLib.Variant("u", CURSOR_HIDDEN)
            if restore_token:
                opts["restore_token"] = GLib.Variant("s", restore_token)
            self._request("SelectSources", lambda t: GLib.Variant(
                "(oa{sv})", (self.session_handle, {**opts, "handle_token": GLib.Variant("s", t)})), selected)

        def selected(ok, res):
            if not ok:
                return on_fail(res.get("error", "window picking was cancelled"))
            self._request("Start", lambda t: GLib.Variant(
                "(osa{sv})", (self.session_handle, "", {"handle_token": GLib.Variant("s", t)})), started)

        def started(ok, res):
            if not ok:
                return on_fail(res.get("error", "window picking was cancelled"))
            streams = res.get("streams", [])
            try:
                fd = self._open_remote()
            except GLib.Error as e:
                return on_fail(e.message)
            on_ready(streams, fd, res.get("restore_token", ""))

        self._request("CreateSession", lambda t: GLib.Variant("(a{sv})", ({
            "handle_token": GLib.Variant("s", t),
            "session_handle_token": GLib.Variant("s", _token()),
        },)), created)

    def _open_remote(self) -> int:
        ret, fds = self.bus.call_with_unix_fd_list_sync(
            BUS, PATH, IFACE, "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (self.session_handle, {})), GLib.VariantType("(h)"),
            Gio.DBusCallFlags.NONE, -1, None, None)
        return fds.get(ret.unpack()[0])

    def close(self) -> None:
        if not self.session_handle:
            return
        self.bus.call(BUS, self.session_handle, "org.freedesktop.portal.Session", "Close",
                      None, None, Gio.DBusCallFlags.NONE, -1, None, None)
        self.session_handle = None
