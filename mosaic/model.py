"""State that survives restarts: capture sessions, window names, layouts.

Pure python (no GTK) so it can be tested headless.
Canvas coordinates are always 1920x1080; the widgets scale them to fit.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field

CANVAS_W, CANVAS_H = 1920, 1080
MIN_TILE = 80
SNAP = 16  # canvas px


def _id() -> str:
    return uuid.uuid4().hex[:8]


def config_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "mosaic", "state.json")


@dataclass
class Session:
    """One xdg ScreenCast portal session = one pick of one or more windows."""
    id: str = field(default_factory=_id)
    token: str = ""                      # portal restore token, refreshed on every start
    names: list[str] = field(default_factory=list)
    hidden: list[int] = field(default_factory=list)  # stream indices the user forgot

    def src_id(self, i: int) -> str:
        return f"{self.id}:{i}"


@dataclass
class Tile:
    src: str      # "<session id>:<stream index>"
    x: float
    y: float
    w: float
    h: float

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@dataclass
class Layout:
    id: str = field(default_factory=_id)
    name: str = "layout"
    tiles: list[Tile] = field(default_factory=list)

    def hit(self, px: float, py: float) -> int:
        """Index of the topmost tile under a canvas point, or -1."""
        for i in range(len(self.tiles) - 1, -1, -1):
            if self.tiles[i].contains(px, py):
                return i
        return -1


@dataclass
class State:
    sessions: list[Session] = field(default_factory=list)
    layouts: list[Layout] = field(default_factory=lambda: [Layout(name="layout 1")])
    current: str = ""
    output: str = "1080"   # output window size: "1080", "720" or "full"

    # ---- lookup ----
    def layout(self) -> Layout:
        for l in self.layouts:
            if l.id == self.current:
                return l
        self.current = self.layouts[0].id
        return self.layouts[0]

    def session(self, sid: str) -> Session | None:
        return next((s for s in self.sessions if s.id == sid), None)

    def name_of(self, src: str) -> str:
        sid, _, i = src.partition(":")
        s = self.session(sid)
        if s and i.isdigit() and int(i) < len(s.names):
            return s.names[int(i)]
        return "window"

    def rename(self, src: str, name: str) -> None:
        sid, _, i = src.partition(":")
        s = self.session(sid)
        if s and i.isdigit():
            i = int(i)
            while len(s.names) <= i:
                s.names.append(f"window {len(s.names) + 1}")
            s.names[i] = name

    def next_window_number(self) -> int:
        return sum(len(s.names) for s in self.sessions) + 1

    # ---- layouts ----
    def add_layout(self, copy_from: Layout | None = None) -> Layout:
        n = len(self.layouts) + 1
        if copy_from:
            l = Layout(name=f"{copy_from.name} copy", tiles=[Tile(**asdict(t)) for t in copy_from.tiles])
        else:
            l = Layout(name=f"layout {n}")
        self.layouts.append(l)
        self.current = l.id
        return l

    def delete_layout(self, lid: str) -> None:
        if len(self.layouts) < 2:
            return
        self.layouts = [l for l in self.layouts if l.id != lid]
        if self.current == lid:
            self.current = self.layouts[0].id

    # ---- persistence ----
    def save(self, path: str | None = None) -> None:
        path = path or config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self), f, indent=1)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str | None = None) -> "State":
        path = path or config_path()
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, ValueError):
            st = cls()
            st.current = st.layouts[0].id
            return st
        st = cls(
            sessions=[Session(**s) for s in d.get("sessions", [])],
            layouts=[Layout(id=l["id"], name=l["name"], tiles=[Tile(**t) for t in l["tiles"]])
                     for l in d.get("layouts", [])] or [Layout(name="layout 1")],
            current=d.get("current", ""),
            output=d.get("output", "1080"),
        )
        st.layout()  # fixes a dangling current id
        return st


# ---- geometry helpers ----

def place_new(aspect: float, cx: float | None = None, cy: float | None = None) -> tuple[float, float, float, float]:
    """A fresh tile: half the canvas wide, centred on (cx, cy), kept on the canvas."""
    aspect = aspect if aspect > 0 else 16 / 9
    w = CANVAS_W / 2
    h = w / aspect
    if h > CANVAS_H * 0.9:
        h = CANVAS_H * 0.9
        w = h * aspect
    cx = CANVAS_W / 2 if cx is None else cx
    cy = CANVAS_H / 2 if cy is None else cy
    x = min(max(cx - w / 2, 0), CANVAS_W - w)
    y = min(max(cy - h / 2, 0), CANVAS_H - h)
    return x, y, w, h


def _snap_lines(total: float, others: list[tuple[float, float]]) -> list[float]:
    lines = [0, total / 3, total / 2, 2 * total / 3, total]
    for a, b in others:
        lines += [a, b]
    return lines


def _snap1(lo: float, size: float, lines: list[float], thr: float) -> float:
    """Snap a span [lo, lo+size] so either edge (or its centre) meets a line."""
    best, best_d = lo, thr + 1
    for edge_off in (0, size, size / 2):
        for ln in lines:
            d = abs(lo + edge_off - ln)
            if d < best_d:
                best, best_d = ln - edge_off, d
    return best if best_d <= thr else lo


def snap_move(layout: Layout, idx: int, x: float, y: float, thr: float = SNAP) -> tuple[float, float]:
    t = layout.tiles[idx]
    others = [o for i, o in enumerate(layout.tiles) if i != idx]
    x = _snap1(x, t.w, _snap_lines(CANVAS_W, [(o.x, o.x + o.w) for o in others]), thr)
    y = _snap1(y, t.h, _snap_lines(CANVAS_H, [(o.y, o.y + o.h) for o in others]), thr)
    return x, y


def snap_resize(layout: Layout, idx: int, w: float, aspect: float, thr: float = SNAP) -> tuple[float, float]:
    """Resize from the bottom-right corner keeping aspect; snap the right or bottom edge."""
    t = layout.tiles[idx]
    others = [o for i, o in enumerate(layout.tiles) if i != idx]
    w = max(MIN_TILE, w)
    right = t.x + w
    for ln in _snap_lines(CANVAS_W, [(o.x, o.x + o.w) for o in others]):
        if abs(right - ln) <= thr and ln - t.x >= MIN_TILE:
            w = ln - t.x
            break
    else:
        bottom = t.y + w / aspect
        for ln in _snap_lines(CANVAS_H, [(o.y, o.y + o.h) for o in others]):
            if abs(bottom - ln) <= thr and ln - t.y >= MIN_TILE:
                w = (ln - t.y) * aspect
                break
    return w, w / aspect


def fit_contain(pw: float, ph: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Largest pw:ph box inside w x h, centred. Returns (dx, dy, dw, dh)."""
    if pw <= 0 or ph <= 0:
        return 0, 0, w, h
    k = min(w / pw, h / ph)
    dw, dh = pw * k, ph * k
    return (w - dw) / 2, (h - dh) / 2, dw, dh


THUMB_W, THUMB_H = 64, 40


def match_by_look(frames: dict[str, list[int]], thumbs: list[tuple[str, list[int]]],
                  max_diff: float = 40.0, margin: float = 4.0) -> dict[str, str]:
    """Name captures by comparing their first frame with each open window's thumbnail.

    frames: src id -> THUMB_W*THUMB_H greyscale values; thumbs: (window name, same).
    Greedy one-to-one on mean absolute difference; a capture only gets a name when
    its best match is close (< max_diff) and clearly ahead of the runner-up (> margin)."""
    def diff(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))

    scored = []
    for src, f in frames.items():
        ds = sorted((diff(f, t), i) for i, (_n, t) in enumerate(thumbs) if len(t) == len(f))
        if not ds or ds[0][0] > max_diff:
            continue
        if len(ds) > 1 and ds[1][0] - ds[0][0] < margin:
            continue
        scored.append((ds[0][0], src, ds[0][1]))
    out, used = {}, set()
    for _d, src, i in sorted(scored):
        if i not in used and src not in out:
            out[src] = thumbs[i][0]
            used.add(i)
    return out
