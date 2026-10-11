# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Tests for the simple graphics library (تکرارهای گرافیکی بکر).

Covers all six iterations:
- تکرار ۱: Graphic model + create/list (model + service + api)
- تکرار ۲: 3D wireframes (cube / pyramid / sphere) projected to 2D
- تکرار ۳: editing via apply_patch
- تکرار ۴: soft deletion
- تکرار ۵: export/import of settings
- تکرار ۶: SVG rendering (render_graphic) for every kind
"""

from __future__ import annotations

import math
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_os.graphics import (
    Graphic,
    GraphicKind,
    GraphicState,
    render_graphic,
)
from agent_os.service import ControlService

T0 = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
TMP = Path(__file__).resolve().parent.parent / ".testtmp"


def _g(**kw) -> Graphic:
    base = dict(id="gfx-1", title="T", kind="shape_2d", config={},
                created_at="2026-10-03T10:00:00+00:00")
    base.update(kw)
    return Graphic(**base)


# --------------------------------------------------------------------------- #
# تکرار ۱ : مدل و ساخت (UI creation)
# --------------------------------------------------------------------------- #


class GraphicModelTest(unittest.TestCase):
    def test_graphic_kind_values(self):
        self.assertEqual(GraphicKind.SHAPE_2D.value, "shape_2d")
        self.assertEqual(GraphicKind.SHAPE_3D.value, "shape_3d")
        self.assertEqual(GraphicKind.CHART.value, "chart")
        self.assertEqual(GraphicKind.DIAGRAM.value, "diagram")

    def test_graphic_state_values(self):
        self.assertEqual(GraphicState.ACTIVE.value, "active")
        self.assertEqual(GraphicState.DELETED.value, "deleted")
        self.assertEqual(GraphicState.ARCHIVED.value, "archived")

    def test_graphic_construction(self):
        g = _g(kind="shape_2d", config={"shape": "rect"})
        self.assertEqual(g.id, "gfx-1")
        self.assertEqual(g.kind, "shape_2d")
        self.assertEqual(g.config, {"shape": "rect"})
        self.assertEqual(g.state, "active")

    def test_enum_kind_accepted(self):
        g = Graphic(id="x", title="T", kind=GraphicKind.SHAPE_2D, config={})
        self.assertEqual(g.kind, "shape_2d")

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ValueError):
            Graphic(id="x", title="T", kind="shape_99", config={})

    def test_config_must_be_dict(self):
        with self.assertRaises(TypeError):
            Graphic(id="x", title="T", kind="shape_2d", config=[1, 2])

    def test_to_dict_round_trip(self):
        g = Graphic(id="gfx-1", title="T", kind="shape_2d", config={"a": 1},
                    created_at="2026-10-03T10:00:00+00:00",
                    updated_at="2026-10-03T10:00:00+00:00")
        g2 = Graphic(**g.to_dict())
        self.assertEqual(g2.id, "gfx-1")
        self.assertEqual(g2.config, {"a": 1})


# --------------------------------------------------------------------------- #
# تکرار ۳ : ویرایش + تکرار ۴ : حذف
# --------------------------------------------------------------------------- #


class GraphicEditDeleteTest(unittest.TestCase):
    def test_apply_patch_merges_config(self):
        g = _g(config={"shape": "rect", "x": 5})
        result = g.apply_patch({"x": 99, "fill": "#ef4444"})
        self.assertIs(result, g)
        self.assertEqual(g.config["x"], 99)
        self.assertEqual(g.config["shape"], "rect")  # untouched key preserved
        self.assertEqual(g.config["fill"], "#ef4444")
        self.assertNotEqual(g.updated_at, "2026-10-03T10:00:00+00:00")

    def test_delete_soft(self):
        g = _g()
        g.delete()
        self.assertEqual(g.state, "deleted")

    def test_patch_preserves_deleted_state(self):
        g = _g()
        g.delete()
        g.apply_patch({"fill": "#fff"})
        self.assertEqual(g.state, "deleted")

    def test_apply_patch_rejects_non_dict(self):
        with self.assertRaises(TypeError):
            _g().apply_patch("nope")


# --------------------------------------------------------------------------- #
# تکرار ۵ : export / import
# --------------------------------------------------------------------------- #


class GraphicExportImportTest(unittest.TestCase):
    def test_export_omits_identity(self):
        g = _g(kind="shape_3d", config={"shape": "cube", "size": 80},
               created_at="2026-10-03T10:00:00+00:00")
        exported = g.export_settings()
        self.assertNotIn("id", exported)
        self.assertNotIn("created_at", exported)
        self.assertNotIn("updated_at", exported)
        self.assertEqual(exported["title"], "T")
        self.assertEqual(exported["kind"], "shape_3d")
        self.assertEqual(exported["config"], {"shape": "cube", "size": 80})

    def test_import_mints_new_id(self):
        exported = _g(kind="shape_3d", config={"shape": "cube"}).export_settings()
        imported = Graphic.from_export(exported)
        self.assertNotEqual(imported.id, "gfx-1")
        self.assertTrue(imported.id.startswith("gfx-"))
        self.assertEqual(imported.title, "T")
        self.assertEqual(imported.kind, "shape_3d")

    def test_import_with_explicit_id(self):
        exported = _g().export_settings()
        imported = Graphic.from_export(exported, graphic_id="gfx-clone")
        self.assertEqual(imported.id, "gfx-clone")
        self.assertEqual(imported.config, {})

    def test_round_trip_preserves_config(self):
        cfg = {"shape": "cube", "size": 80, "rotation": [0, 1.5, 0]}
        exported = _g(kind="shape_3d", config=cfg,
                      created_at="2026-10-03T10:00:00+00:00").export_settings()
        imported = Graphic.from_export(exported)
        self.assertEqual(imported.config, cfg)


# --------------------------------------------------------------------------- #
# تکرار ۲ + تکرار ۶ : رندر (3D wireframes + SVG)
# --------------------------------------------------------------------------- #


class GraphicRenderTest(unittest.TestCase):
    def test_render_2d_rect(self):
        svg = render_graphic(_g(kind="shape_2d", config={"shape": "rect"}))
        self.assertIn("<svg", svg)
        self.assertIn("<rect", svg)
        self.assertIn("</svg>", svg)

    def test_render_2d_circle(self):
        svg = render_graphic(_g(kind="shape_2d", config={"shape": "circle", "r": 30}))
        self.assertIn("<circle", svg)

    def test_render_2d_polygon(self):
        svg = render_graphic(_g(kind="shape_2d",
                                 config={"shape": "polygon",
                                         "points": [[0, 0], [50, 0], [25, 40]]}))
        self.assertIn("<polygon", svg)

    def test_render_chart_bar(self):
        svg = render_graphic(_g(kind="chart",
                                config={"chart_type": "bar", "data": [10, 20, 30]}))
        self.assertIn("<rect", svg)

    def test_render_chart_line(self):
        svg = render_graphic(_g(kind="chart",
                                config={"chart_type": "line", "data": [10, 20, 30]}))
        self.assertIn("<polyline", svg)

    def test_render_diagram(self):
        svg = render_graphic(_g(kind="diagram",
                                config={"nodes": [{"id": "a", "x": 0, "y": 0, "label": "A"}],
                                        "edges": [{"from": "a", "to": "a"}]}))
        self.assertIn("<svg", svg)
        self.assertIn("<rect", svg)
        self.assertIn("<line", svg)

    # --- 3D wireframes (تکرار ۲) ---
    def test_render_3d_cube_edge_count(self):
        svg = render_graphic(_g(kind="shape_3d", config={"shape": "cube", "size": 100}))
        self.assertEqual(svg.count("<line"), 12)  # a cube has 12 edges

    def test_render_3d_pyramid_edge_count(self):
        svg = render_graphic(_g(kind="shape_3d", config={"shape": "pyramid", "size": 100}))
        self.assertEqual(svg.count("<line"), 8)  # a pyramid has 8 edges

    def test_render_3d_sphere_edge_count(self):
        svg = render_graphic(_g(kind="shape_3d",
                                config={"shape": "sphere", "size": 100,
                                        "segs_lat": 5, "segs_lon": 8}))
        # 8 meridians * 5 = 40, 3 parallels * 8 = 24 -> 64
        self.assertEqual(svg.count("<line"), 64)

    def test_3d_solid_emits_faces_plus_edges(self):
        g = _g(kind="shape_3d", config={"shape": "cube", "size": 100, "wireframe": False})
        svg = render_graphic(g)
        self.assertIn("<polygon", svg)   # solid faces
        self.assertEqual(svg.count("<line"), 12)  # wire overlay

    def test_3d_rotation_changes_output(self):
        g0 = _g(kind="shape_3d", config={"shape": "cube", "size": 100, "rotation": [0, 0, 0]})
        g1 = _g(kind="shape_3d", config={"shape": "cube", "size": 100,
                                         "rotation": [0, math.pi / 4, 0]})
        self.assertNotEqual(render_graphic(g0), render_graphic(g1))

    def test_render_unknown_kind_raises(self):
        g = Graphic.__new__(Graphic)
        g.id = "x"; g.title = "T"; g.kind = "bogus"; g.config = {}
        g.state = "active"; g.created_at = ""; g.updated_at = ""
        with self.assertRaises(ValueError):
            render_graphic(g)


# --------------------------------------------------------------------------- #
# تکرار ۱/۳/۴/۵/۶ at the SERVICE layer (persistence + rendering)
# --------------------------------------------------------------------------- #


class GraphicServiceTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db_path = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.svc = ControlService(self.db_path)

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(TMP, ignore_errors=True)

    def test_create_and_get(self):
        g = self.svc.create_graphic(title="Box", kind="shape_2d", config={"shape": "rect"})
        self.assertTrue(g["id"].startswith("gfx-"))
        self.assertEqual(g["title"], "Box")
        self.assertEqual(g["state"], "active")
        fetched = self.svc.get_graphic(g["id"])
        self.assertEqual(fetched["title"], "Box")

    def test_create_invalid_kind(self):
        with self.assertRaises(ValueError):
            self.svc.create_graphic(title="X", kind="bogus", config={})

    def test_list_excludes_deleted_by_default(self):
        a = self.svc.create_graphic("A", "shape_2d", {})
        b = self.svc.create_graphic("B", "shape_2d", {})
        self.svc.delete_graphic(b["id"])
        self.assertEqual(len(self.svc.list_graphics()), 1)
        self.assertEqual(self.svc.list_graphics()[0]["id"], a["id"])
        self.assertEqual(len(self.svc.list_graphics(include_deleted=True)), 2)

    def test_update_config(self):
        g = self.svc.create_graphic("A", "shape_2d", {"x": 5})
        updated = self.svc.update_graphic(g["id"], {"x": 42})
        self.assertEqual(updated["config"]["x"], 42)

    def test_update_missing(self):
        with self.assertRaises(KeyError):
            self.svc.update_graphic("no-such", {"x": 1})

    def test_delete_soft(self):
        g = self.svc.create_graphic("A", "shape_2d", {})
        self.svc.delete_graphic(g["id"])
        self.assertEqual(self.svc.get_graphic(g["id"])["state"], "deleted")

    def test_delete_missing(self):
        with self.assertRaises(KeyError):
            self.svc.delete_graphic("no-such")

    def test_render(self):
        g = self.svc.create_graphic("Box", "shape_2d", {"shape": "rect"})
        svg = self.svc.render_graphic(g["id"])
        self.assertIn("<svg", svg)

    def test_render_deleted_blocked(self):
        g = self.svc.create_graphic("Box", "shape_2d", {"shape": "rect"})
        self.svc.delete_graphic(g["id"])
        with self.assertRaises(ValueError):
            self.svc.render_graphic(g["id"])

    def test_export_import(self):
        g = self.svc.create_graphic("Cube", "shape_3d", {"shape": "cube", "size": 80})
        exported = self.svc.export_graphic_settings(g["id"])
        self.assertEqual(exported["title"], "Cube")
        self.assertNotIn("id", exported)
        imported = self.svc.import_graphic_settings(exported)
        self.assertTrue(imported["id"].startswith("gfx-"))
        self.assertNotEqual(imported["id"], g["id"])
        self.assertEqual(imported["config"]["shape"], "cube")
        self.assertEqual(imported["state"], "active")


# --------------------------------------------------------------------------- #
# API layer (end-to-end through AgentOSApi.handle)
# --------------------------------------------------------------------------- #


class GraphicApiTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)
        from agent_os.api import AgentOSApi
        self.api = AgentOSApi(self.svc, token="secret")

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(TMP, ignore_errors=True)

    def _call(self, method, path, body=None):
        return self.api.handle(method, path, body)

    def test_create_and_get(self):
        status, payload = self._call("POST", "/api/graphics", {
            "title": "Box", "kind": "shape_2d",
            "config": {"shape": "rect", "fill": "#3b82f6"}})
        self.assertEqual(status, 201)
        self.assertTrue(payload["id"].startswith("gfx-"))
        gid = payload["id"]
        status, payload = self._call("GET", f"/api/graphics/{gid}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["title"], "Box")

    def test_create_invalid_kind(self):
        status, payload = self._call("POST", "/api/graphics", {
            "title": "X", "kind": "bogus", "config": {}})
        self.assertEqual(status, 400)

    def test_create_missing_title(self):
        status, _ = self._call("POST", "/api/graphics", {"kind": "shape_2d"})
        self.assertEqual(status, 400)

    def test_list(self):
        self._call("POST", "/api/graphics", {"title": "A", "kind": "shape_2d", "config": {}})
        status, payload = self._call("GET", "/api/graphics")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["graphics"]), 1)

    def test_get_not_found(self):
        status, _ = self._call("GET", "/api/graphics/no-such-id")
        self.assertEqual(status, 404)

    def test_render(self):
        _, created = self._call("POST", "/api/graphics", {
            "title": "C", "kind": "shape_3d",
            "config": {"shape": "cube", "size": 100}})
        status, payload = self._call("POST", f"/api/graphics/{created['id']}/render")
        self.assertEqual(status, 200)
        self.assertIn("<svg", payload["svg"])

    def test_export_import(self):
        _, created = self._call("POST", "/api/graphics", {
            "title": "Cube", "kind": "shape_3d",
            "config": {"shape": "cube", "size": 80}})
        gid = created["id"]
        status, exported = self._call("POST", f"/api/graphics/{gid}/export")
        self.assertEqual(status, 200)
        self.assertEqual(exported["title"], "Cube")
        status, imported = self._call("POST", "/api/graphics/import", exported)
        self.assertEqual(status, 201)
        self.assertNotEqual(imported["id"], gid)

    def test_update(self):
        _, created = self._call("POST", "/api/graphics", {
            "title": "A", "kind": "shape_2d", "config": {"x": 5}})
        status, updated = self._call(
            "POST", f"/api/graphics/{created['id']}/update", {"config": {"x": 42}})
        self.assertEqual(status, 200)
        self.assertEqual(updated["config"]["x"], 42)

    def test_delete_soft(self):
        _, created = self._call("POST", "/api/graphics", {
            "title": "A", "kind": "shape_2d", "config": {}})
        status, payload = self._call("DELETE", f"/api/graphics/{created['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["deleted"], created["id"])
        # soft delete: still retrievable
        status, _ = self._call("GET", f"/api/graphics/{created['id']}")
        self.assertEqual(status, 200)

    def test_delete_not_found(self):
        status, _ = self._call("DELETE", "/api/graphics/no-such-id")
        self.assertEqual(status, 404)

    def test_render_not_found(self):
        status, _ = self._call("POST", "/api/graphics/no-such-id/render")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
