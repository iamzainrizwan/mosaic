# mosaic

tile live app windows onto one 1920×1080 stage, flip between saved layouts, and
screenshare just that stage. a small, single-purpose take on what OBS scenes do,
for GNOME on Wayland.

- **pool**: pick several windows at once in GNOME's picker; each becomes a live feed
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

## use

1. open the apps you want to show, then **add windows** and tick them all
2. drag windows from the pool onto the stage. drag to move, pull the bottom-right
   corner to resize. tiles snap to edges, thirds, the centre and each other
3. make more layouts (new / duplicate) and click between them
4. send **mosaic output** to another workspace, F11, share that window

state lives in `~/.config/mosaic/state.json`.

## tests

```
python3 -m unittest
```

## licence

MIT
