# mosaic

tile live app windows onto one 1920×1080 stage, flip between saved layouts, and
screenshare just that stage. a small, single-purpose take on what OBS scenes do,
for GNOME on Wayland.

- **pool**: add windows through GNOME's picker; each becomes a live, named feed
- **layouts**: which window goes where and how big; switch between them with one click
- **swap**: drag a different window onto a tile to replace it, keeping the slot
- **output**: a clean window with nothing but the stage. park it on another workspace,
  press F11, and share it in Meet / Zoom / Discord
- remembers your windows between launches (portal restore token), so no re-picking
  while they stay open

## run

needs GTK 4, libadwaita, PyGObject and GStreamer with the PipeWire plugin. on
Ubuntu 24.04 / Debian:

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
  gir1.2-gst-plugins-base-1.0 gstreamer1.0-pipewire gstreamer1.0-plugins-base
./install.sh     # puts `mosaic` on PATH and in the app grid
mosaic
```

or without installing: `python3 -m mosaic` from the repo.

**window names:** GNOME's picker never tells apps which window you chose (on GNOME 46
even the size it reports is just the monitor's). `install.sh` also installs a tiny shell
extension (`extension/`) that lists open windows with a small thumbnail of each over
D-Bus, and mosaic names each new capture by matching its first frame against those
thumbnails. On Wayland a new or updated extension only loads after you log out and back
in once. Without it, windows are "window 1, 2, …" and you rename them in the pool.

## use

1. open the apps you want to show, then **add windows** and tick them all (the
   picker allows several at once)
2. drag windows from the pool onto the stage. drag to move, pull the bottom-right
   corner to resize. tiles snap to edges, thirds, the centre and each other
3. make more layouts (new / duplicate) and click between them
4. pick an output size in the header (1920×1080 or 1280×720, in real screen pixels),
   drag the output window to another workspace and share it. it has no title bar, so
   the share is only the stage: drag anywhere on it to move it, double-click or F11 for
   fullscreen

windows that aren't on the current layout pause (their pool thumbnails refresh every
few seconds); the ones on stage capture at up to 30fps.

state lives in `~/.config/mosaic/state.json`.

## tests

```
python3 -m unittest
```

## licence

MIT
