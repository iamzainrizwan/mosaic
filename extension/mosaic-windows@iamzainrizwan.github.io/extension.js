// mosaic windows: the screencast portal tells mosaic each captured window's
// size but not its name. This exposes the open windows (title, app, sizes) on
// the session bus so mosaic can match them up by size.
//
//   gdbus call --session --dest org.gnome.Shell \
//     --object-path /io/github/iamzainrizwan/Mosaic \
//     --method io.github.iamzainrizwan.Mosaic.GetWindows
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="io.github.iamzainrizwan.Mosaic">
    <method name="GetWindows">
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
        const tracker = Shell.WindowTracker.get_default();
        const out = [];
        for (const actor of global.get_window_actors()) {
            const w = actor.get_meta_window();
            if (!w || w.is_skip_taskbar())
                continue;
            const app = tracker.get_window_app(w);
            const f = w.get_frame_rect();
            const b = w.get_buffer_rect();
            out.push({
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
