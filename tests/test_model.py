"""Headless tests for layout maths and persistence: python3 -m unittest"""
import os
import tempfile
import unittest

from mosaic import model
from mosaic.model import CANVAS_H, CANVAS_W, Layout, Session, State, Tile


class Geometry(unittest.TestCase):
    def test_place_new_fits_and_keeps_aspect(self):
        x, y, w, h = model.place_new(16 / 9)
        self.assertAlmostEqual(w / h, 16 / 9)
        self.assertTrue(0 <= x and x + w <= CANVAS_W and 0 <= y and y + h <= CANVAS_H)
        x, y, w, h = model.place_new(0.5, 1900, 1070)  # tall window dropped in a corner
        self.assertAlmostEqual(w / h, 0.5)
        self.assertLessEqual(h, CANVAS_H * 0.9 + 1e-9)
        self.assertAlmostEqual(x + w, CANVAS_W)
        self.assertAlmostEqual(y + h, CANVAS_H)

    def test_snap_move_to_edges_and_neighbours(self):
        lay = Layout(tiles=[Tile("a:0", 0, 0, 500, 300), Tile("a:1", 900, 400, 400, 300)])
        x, y = model.snap_move(lay, 1, 507, 9)
        self.assertEqual((x, y), (500, 0))      # left edge onto neighbour, top onto stage
        x, y = model.snap_move(lay, 1, 700, 600)
        self.assertEqual((x, y), (700, 600))    # nothing near: untouched

    def test_snap_resize_keeps_aspect(self):
        lay = Layout(tiles=[Tile("a:0", 0, 0, 800, 450)])
        w, h = model.snap_resize(lay, 0, 955, 16 / 9)
        self.assertEqual(w, CANVAS_W / 2)        # right edge snapped to the centre line
        self.assertAlmostEqual(w / h, 16 / 9)
        w, h = model.snap_resize(lay, 0, 5, 16 / 9)
        self.assertEqual(w, model.MIN_TILE)

    def test_fit_contain(self):
        self.assertEqual(model.fit_contain(1000, 500, 400, 400), (0, 100, 400, 200))
        self.assertEqual(model.fit_contain(0, 0, 10, 20), (0, 0, 10, 20))

    def test_hit_is_topmost(self):
        lay = Layout(tiles=[Tile("a:0", 0, 0, 500, 500), Tile("a:1", 100, 100, 100, 100)])
        self.assertEqual(lay.hit(150, 150), 1)
        self.assertEqual(lay.hit(400, 400), 0)
        self.assertEqual(lay.hit(1500, 900), -1)


class Persistence(unittest.TestCase):
    def test_roundtrip_and_layout_ops(self):
        st = State()
        s = Session(names=["desmos"])
        st.sessions.append(s)
        st.rename(s.src_id(2), "paper")
        self.assertEqual(s.names, ["desmos", "window 2", "paper"])
        st.layout().tiles.append(Tile(s.src_id(0), 1, 2, 3, 4))
        dup = st.add_layout(copy_from=st.layout())
        self.assertEqual(st.current, dup.id)
        dup.tiles[0].x = 99
        self.assertEqual(st.layouts[0].tiles[0].x, 1)  # deep copy
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mosaic", "state.json")
            st.save(p)
            back = State.load(p)
        self.assertEqual(back.current, dup.id)
        self.assertEqual(back.name_of(s.src_id(0)), "desmos")
        self.assertEqual(back.layouts[1].tiles[0].x, 99)
        back.delete_layout(dup.id)
        self.assertEqual(back.current, back.layouts[0].id)
        back.delete_layout(back.current)                 # never deletes the last one
        self.assertEqual(len(back.layouts), 1)

    def test_missing_or_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            self.assertEqual(len(State.load(p).layouts), 1)
            with open(p, "w") as f:
                f.write("{nope")
            self.assertEqual(State.load(p).layout().name, "layout 1")


if __name__ == "__main__":
    unittest.main()
