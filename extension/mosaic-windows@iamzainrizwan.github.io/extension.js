// mosaic windows: the screencast portal never tells mosaic which window you
// picked (on GNOME 46 even its "size" is just the monitor size). This exposes
// the open windows (title, app, sizes, a tiny thumbnail) on the session bus,
// and mosaic matches each new capture's first frame against the thumbnails.
//
//   gdbus call --session --dest org.gnome.Shell \
//     --object-path /io/github/iamzainrizwan/Mosaic \
//     --method io.github.iamzainrizwan.Mosaic.GetWindows
import Cairo from 'cairo';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const THUMB_W = 64, THUMB_H = 40;

// Window contents squashed to THUMB_W x THUMB_H, saved as a png in the user's
// runtime dir. Returns the path, or '' if mutter can't render that window.
function thumbnail(actor, i) {
    try {
        const img = actor.get_image(null);
        if (!img)
            return '';
        const dir = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'mosaic-thumbs']);
        GLib.mkdir_with_parents(dir, 0o700);
        const out = new Cairo.ImageSurface(Cairo.Format.ARGB32, THUMB_W, THUMB_H);
        const cr = new Cairo.Context(out);
        cr.scale(THUMB_W / img.getWidth(), THUMB_H / img.getHeight());
        cr.setSourceSurface(img, 0, 0);
        cr.paint();
        const path = GLib.build_filenamev([dir, `${i}.png`]);
        out.writeToPNG(path);
        cr.$dispose();
        return path;
    } catch (e) {
        return '';
    }
}

const IFACE = `
<node>
  <interface name="io.github.iamzainrizwan.Mosaic">
    <method name="GetWindows">
      <arg type="s" direction="out" name="windows_json"/>
    </method>
    <method name="GetWindowsWithThumbs">
      <arg type="s" direction="out" name="windows_json"/>
    </method>
  </interface>
</node>`;

export default class MosaicWindows extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/io/github/iamzainrizwan/Mosaic');
    }

    disable() {
        this._dbus?.flush();
        this._dbus?.unexport();
        this._dbus = null;
    }

    GetWindows() {
        return this._list(false);
    }

    GetWindowsWithThumbs() {
        return this._list(true);
    }

    _list(withThumbs) {
        const tracker = Shell.WindowTracker.get_default();
        const out = [];
        let i = 0;
        for (const actor of global.get_window_actors()) {
            const w = actor.get_meta_window();
            if (!w || w.is_skip_taskbar())
                continue;
            const app = tracker.get_window_app(w);
            const f = w.get_frame_rect();
            const b = w.get_buffer_rect();
            out.push({
                id: w.get_id(),
                thumb: withThumbs ? thumbnail(actor, i++) : '',
                title: w.get_title() ?? '',
                app: app?.get_name() ?? '',
                app_id: app?.get_id() ?? '',
                frame: [f.width, f.height],
                buffer: [b.width, b.height],
                scale: global.display.get_monitor_scale(w.get_monitor()),
                minimized: w.minimized,
            });
        }
        return JSON.stringify(out);
    }
}
