"""Simple graphics library for Agent OS.

A compact, dependency-free vector-graphics library that renders to inline SVG.
It covers the six *تکرار* (iteration) tasks the board enumerates:

  تکرار ۱ - UI creation        : Graphic dataclass + kind/state enums
  تکرار ۲ - 3D                 : parametric 3D wireframes (cube, pyramid,
                                   sphere) projected to 2D via rotation
                                   matrices + orthographic projection
  تکرار ۳ - editing            : Graphic.apply_patch merges a config delta
  تکرار ۴ - deletion           : Graphic.delete soft-deletes (state flag,
                                   never a physical row removal)
  تکرار ۵ - export/import      : Graphic.export_settings / from_export
  تکرار ۶ - features            : render_graphic -> SVG markup

The renderer is pure-Python and produces inline SVG so the result is usable
directly from the Agent OS web UI without a browser-side canvas dependency.
"""

from __future__ import annotations

import html
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# تکرار ۱ : مدل و شمارش‌گرها (UI creation)
# --------------------------------------------------------------------------- #


class GraphicKind(str, Enum):
    """The broad category of a graphic; selects its renderer."""

    SHAPE_2D = "shape_2d"
    SHAPE_3D = "shape_3d"
    CHART = "chart"
    DIAGRAM = "diagram"


class GraphicState(str, Enum):
    """Lifecycle state. Deletion is always soft (see تکرار ۴)."""

    ACTIVE = "active"
    DELETED = "deleted"
    ARCHIVED = "archived"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def _new_gfx_id() -> str:
    """Mint a fresh graphic id with the ``gfx-`` prefix."""
    return f"gfx-{uuid.uuid4().hex[:12]}"


@dataclass
class Graphic:
    """A single vector graphic stored in Agent OS.

    ``config`` is an opaque, schema-free dict owned by the renderer for this
    graphic *kind*. Keeping it unstructured lets each iteration add new
    parameters without a database migration - mirroring how workflow nodes
    carry a free-form ``metadata`` dict.
    """

    id: str
    title: str
    kind: str
    config: dict[str, Any] = field(default_factory=dict)
    state: str = GraphicState.ACTIVE.value
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        # Normalise: accept enum members passed as kind/state.
        if isinstance(self.kind, GraphicKind):
            self.kind = self.kind.value
        if isinstance(self.state, GraphicState):
            self.state = self.state.value
        if not isinstance(self.config, dict):
            raise TypeError("config must be a dict")
        # Validate kind is a known member so renderers stay bounded.
        if self.kind not in {k.value for k in GraphicKind}:
            raise ValueError(f"unsupported graphic kind: {self.kind!r}")

    # ------------------------------------------------------------------ #
    # تکرار ۳ : ویرایش گرافیکی
    # ------------------------------------------------------------------ #
    def apply_patch(self, patch: dict[str, Any]) -> "Graphic":
        """Shallow-merge ``patch`` into config and bump ``updated_at``.

        Only top-level keys are merged; nested structures (e.g. a 3D rotation
        triple) replace wholesale rather than being diff-merged, which is what
        a user editing one handle expects. Returns self for chaining.
        """
        if not isinstance(patch, dict):
            raise TypeError("patch must be a dict")
        self.config.update(patch)
        self.updated_at = iso(utc_now())
        return self

    # ------------------------------------------------------------------ #
    # تکرار ۴ : حذف گرافیکی (soft delete)
    # ------------------------------------------------------------------ #
    def delete(self) -> "Graphic":
        """Soft-delete: the store honours the DELETED flag instead of
        physically removing the row, so history and audit remain intact."""
        self.state = GraphicState.DELETED.value
        self.updated_at = iso(utc_now())
        return self

    # ------------------------------------------------------------------ #
    # تکرار ۵ : export / import تنظیمات
    # ------------------------------------------------------------------ #
    def export_settings(self) -> dict[str, Any]:
        """JSON-serializable, identity-free settings snapshot.

        The id/timestamps are deliberately omitted: an exported bundle is
        portable and must be re-created with fresh identity on import.
        """
        return {
            "title": self.title,
            "kind": self.kind,
            "config": self.config,
            "state": self.state,
        }

    @classmethod
    def from_export(
        cls, data: dict[str, Any], graphic_id: Optional[str] = None
    ) -> "Graphic":
        """Reconstruct a Graphic from an exported settings dict.

        A None ``graphic_id`` mints a fresh id so imported copies never
        collide with the source; a provided id re-creates an exact twin.
        """
        now = iso(utc_now())
        return cls(
            id=graphic_id or _new_gfx_id(),
            title=data.get("title", "Graphic"),
            kind=data.get("kind", GraphicKind.SHAPE_2D.value),
            config=dict(data.get("config", {})),
            state=data.get("state", GraphicState.ACTIVE.value),
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "config": self.config,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --------------------------------------------------------------------------- #
# تکرار ۶ : عملکرد — رندر به SVG
# --------------------------------------------------------------------------- #


def render_graphic(graphic: "Graphic") -> str:
    """Render *graphic* to an inline SVG document (string).

    Raises ``ValueError`` for an unknown kind. Callers should never reach
    this path because the model validates kind at construction.
    """
    if graphic.kind == GraphicKind.SHAPE_3D.value:
        return _render_3d(graphic)
    if graphic.kind == GraphicKind.SHAPE_2D.value:
        return _render_2d(graphic)
    if graphic.kind == GraphicKind.CHART.value:
        return _render_chart(graphic)
    if graphic.kind == GraphicKind.DIAGRAM.value:
        return _render_diagram(graphic)
    raise ValueError(f"unsupported graphic kind: {graphic.kind!r}")


def _svg_root(content: str, w: float, h: float, title: str) -> str:
    t = html.escape(title or "Graphic")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f"<title>{t}</title>"
        f"{content}</svg>\n"
    )


# --- 2D --------------------------------------------------------------------


def _render_2d(g: "Graphic") -> str:
    cfg = g.config
    W = float(cfg.get("width", 200))
    H = float(cfg.get("height", 200))
    shape = str(cfg.get("shape", "rect"))
    fill = html.escape(str(cfg.get("fill", "#3b82f6")))
    stroke = html.escape(str(cfg.get("stroke", "#1e293b")))
    sw = cfg.get("stroke_width", 1)
    if shape == "rect":
        x, y = cfg.get("x", 5), cfg.get("y", 5)
        w, h = cfg.get("width", 100), cfg.get("height", 60)
        inner = (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
        )
    elif shape == "circle":
        cx, cy, r = cfg.get("cx", 50), cfg.get("cy", 50), cfg.get("r", 40)
        inner = (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
        )
    elif shape == "polygon":
        pts = cfg.get("points", [[0, 0], [50, 0], [50, 50], [0, 50]])
        ps = " ".join(f"{x},{y}" for x, y in pts)
        inner = (
            f'<polygon points="{ps}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}"/>'
        )
    elif shape == "line":
        x1, y1 = cfg.get("x1", 0), cfg.get("y1", 0)
        x2, y2 = cfg.get("x2", W), cfg.get("y2", H)
        inner = (
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{fill}" stroke-width="{sw}"/>'
        )
    else:
        inner = (
            f'<text x="10" y="20" font-family="monospace" fill="{fill}">'
            f"Unknown 2D shape: {html.escape(shape)}</text>"
        )
    return _svg_root(inner, W, H, g.title)


# --- 3D --------------------------------------------------------------------

_V3 = tuple[float, float, float]


def _rot_x(v: _V3, a: float) -> _V3:
    c, s = math.cos(a), math.sin(a)
    return (v[0], v[1] * c - v[2] * s, v[1] * s + v[2] * c)


def _rot_y(v: _V3, a: float) -> _V3:
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c)


def _rot_z(v: _V3, a: float) -> _V3:
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2])


def _project(v: _V3, scale: float, cx: float, cy: float) -> tuple[float, float]:
    """Orthographic projection: drop z, scale, centre, flip Y for SVG."""
    return (cx + v[0] * scale, cy - v[1] * scale)


def _cube(size: float) -> tuple[list[_V3], list[tuple[int, int]], list[tuple[int, ...]]]:
    s = size / 2.0
    verts = [
        (s, s, s), (s, s, -s), (s, -s, s), (s, -s, -s),
        (-s, s, s), (-s, s, -s), (-s, -s, s), (-s, -s, -s),
    ]
    edges = [
        (0, 1), (0, 2), (1, 3), (2, 3),
        (4, 5), (4, 6), (5, 7), (6, 7),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    # quads with outward-facing vertex order (CCW when seen from outside)
    faces = [
        (0, 2, 3, 1), (4, 5, 7, 6),
        (0, 1, 5, 4), (2, 3, 7, 6),
        (0, 4, 6, 2), (1, 3, 7, 5),
    ]
    return verts, edges, faces


def _pyramid(size: float) -> tuple[list[_V3], list[tuple[int, int]], list[tuple[int, ...]]]:
    s = size / 2.0
    apex = (0.0, s, 0.0)
    base = [(-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s)]
    verts = [apex] + base
    edges = [
        (0, 1), (0, 2), (0, 3), (0, 4),
        (1, 2), (2, 3), (3, 4), (4, 1),
    ]
    # 4 side triangles (apex + 2 adjacent base verts) + base quad
    faces = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1), (1, 2, 3, 4)]
    return verts, edges, faces


def _uv_sphere(
    radius: float, segs_lat: int = 8, segs_lon: int = 12
) -> tuple[list[_V3], list[tuple[int, int]], list[tuple[int, ...]]]:
    """UV-sphere wireframe. No solid faces are emitted (sphere stays wireframe)."""
    verts: list[_V3] = [(0.0, radius, 0.0)]  # north pole
    for i in range(1, segs_lat):
        phi = math.pi * i / segs_lat
        r = radius * math.sin(phi)
        y = radius * math.cos(phi)
        for j in range(segs_lon):
            theta = 2 * math.pi * j / segs_lon
            verts.append((r * math.cos(theta), y, r * math.sin(theta)))
    verts.append((0.0, -radius, 0.0))  # south pole
    north, south = 0, len(verts) - 1
    edges: list[tuple[int, int]] = []
    # meridians: north -> each ring vertex -> south
    for j in range(segs_lon):
        for i in range(segs_lat):
            a = north if i == 0 else 1 + (i - 1) * segs_lon + j
            b = south if i == segs_lat - 1 else 1 + i * segs_lon + j
            edges.append((a, b))
    # parallels: connect consecutive vertices on each ring
    for i in range(1, segs_lat - 1):
        base = 1 + (i - 1) * segs_lon
        for j in range(segs_lon):
            edges.append((base + j, base + ((j + 1) % segs_lon)))
    return verts, edges, []


def _shape_3d(
    kind: str, size: float, cfg: dict[str, Any]
) -> tuple[list[_V3], list[tuple[int, int]], list[tuple[int, ...]]]:
    if kind == "pyramid":
        return _pyramid(size)
    if kind == "sphere":
        return _uv_sphere(
            size / 2.0,
            int(cfg.get("segs_lat", 8)),
            int(cfg.get("segs_lon", 12)),
        )
    return _cube(size)


def _face_normal(v: list[_V3], face: tuple[int, ...]) -> _V3:
    """Outward normal of a face via the cross product of two edges."""
    a, b, c = v[face[0]], v[face[1]], v[face[2]]
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return (
        e1[1] * e2[2] - e1[2] * e2[1],
        e1[2] * e2[0] - e1[0] * e2[2],
        e1[0] * e2[1] - e1[1] * e2[0],
    )


def _render_3d(g: "Graphic") -> str:
    cfg = g.config
    kind3d = str(cfg.get("shape", "cube"))
    size = float(cfg.get("size", 100))
    ax, ay, az = (float(x) for x in cfg.get("rotation", [0.0, 0.0, 0.0]))
    scale = float(cfg.get("scale", 1.0))
    cx = float(cfg.get("center_x", 160))
    cy = float(cfg.get("center_y", 160))
    fill = html.escape(str(cfg.get("fill", "#3b82f6")))
    stroke = html.escape(str(cfg.get("stroke", "#1e293b")))
    sw = cfg.get("stroke_width", 1.5)
    wireframe = bool(cfg.get("wireframe", True))
    face_fill = html.escape(str(cfg.get("face_fill", "#3b82f6")))
    face_fill_2 = html.escape(str(cfg.get("face_fill_2", "#2563eb")))

    verts, edges, faces = _shape_3d(kind3d, size, cfg)
    rotated = [_rot_z(_rot_y(_rot_x(v, ax), ay), az) for v in verts]
    projected = [_project(v, scale, cx, cy) for v in rotated]

    # viewBox from projected bounding box + padding
    xs = [p[0] for p in projected]
    ys = [p[1] for p in projected]
    pad = 16
    bx0, by0 = min(xs) - pad, min(ys) - pad
    bx1, by1 = max(xs) + pad, max(ys) + pad
    W, H = bx1 - bx0, by1 - by0

    parts: list[str] = []
    if not wireframe and faces:
        # Solid render with backface culling. Camera looks down -Z, so a face
        # whose outward normal has z >= 0 faces the viewer.
        visible = []
        for fi, face in enumerate(faces):
            n = _face_normal(rotated, face)
            if n[2] >= 0:
                visible.append((fi, face, n[2]))
        # Paint back-to-front by average projected depth so nearer faces overlap.
        visible.sort(
            key=lambda item: -sum(rotated[v][2] for v in item[1]) / len(item[1])
        )
        for fi, face, _nz in visible:
            pts = " ".join(f"{projected[v][0]:.2f},{projected[v][1]:.2f}" for v in face)
            mid = sum(rotated[v][2] for v in face) / len(face)
            fillcol = face_fill if mid < 0 else face_fill_2
            parts.append(
                f'<polygon points="{pts}" fill="{fillcol}" '
                f'stroke="{stroke}" stroke-width="{sw}"/>'
            )
    # Edges always drawn (wireframe overlay in solid mode, wire-only otherwise).
    for i, j in edges:
        ex1, ey1 = projected[i]
        ex2, ey2 = projected[j]
        parts.append(
            f'<line x1="{ex1:.2f}" y1="{ey1:.2f}" x2="{ex2:.2f}" '
            f'y2="{ey2:.2f}" stroke="{fill}" stroke-width="{sw}"/>'
        )
    inner = "".join(parts)
    return _svg_root(inner, round(W, 2), round(H, 2), g.title)


# --- charts ----------------------------------------------------------------


def _render_chart(g: "Graphic") -> str:
    cfg = g.config
    W = float(cfg.get("width", 400))
    H = float(cfg.get("height", 300))
    data = list(cfg.get("data", [10, 20, 30, 40]))
    ckind = str(cfg.get("chart_type", "bar"))
    fill = html.escape(str(cfg.get("fill", "#3b82f6")))
    axis = html.escape(str(cfg.get("axis_color", "#64748a")))
    sw = cfg.get("stroke_width", 1)
    if not data:
        data = [0]
    vmax = max(v for v in data) if data else 1
    if vmax <= 0:
        vmax = 1
    n = len(data)
    parts = [
        f'<line x1="0" y1="{H}" x2="{W}" y2="{H}" stroke="{axis}" stroke-width="{sw}"/>',
        f'<line x1="0" y1="0" x2="0" y2="{H}" stroke="{axis}" stroke-width="{sw}"/>',
    ]
    if ckind == "bar":
        bw = W / (n * 2)
        step = W / max(n, 1)
        for i, v in enumerate(data):
            x = step * i + (step - bw) / 2
            h = (v / vmax) * (H - 24)
            y = H - h
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bw:.2f}" height="{h:.2f}" '
                f'fill="{fill}"/>'
            )
    elif ckind == "line":
        pts = []
        for i, v in enumerate(data):
            x = (i / max(n - 1, 1)) * W
            y = H - (v / vmax) * (H - 24)
            pts.append(f"{x:.2f},{y:.2f}")
        pts_str = html.escape(" ".join(pts))
        parts.append(
            f'<polyline points="{pts_str}" fill="none" stroke="{fill}" '
            f'stroke-width="{sw}"/>'
        )
    else:
        parts.append(
            f'<text x="10" y="20" font-family="monospace" fill="{fill}">'
            f"Unknown chart type: {html.escape(ckind)}</text>"
        )
    return _svg_root("".join(parts), W, H, g.title)


# --- diagrams --------------------------------------------------------------


def _render_diagram(g: "Graphic") -> str:
    cfg = g.config
    W = float(cfg.get("width", 400))
    H = float(cfg.get("height", 300))
    nodes = cfg.get("nodes", [])
    edges = cfg.get("edges", [])
    stroke = html.escape(str(cfg.get("stroke", "#334159")))
    node_fill = html.escape(str(cfg.get("node_fill", "#f8fafc")))
    text_color = html.escape(str(cfg.get("text_color", "#0f172a")))
    sw = cfg.get("stroke_width", 1)
    parts: list[str] = []
    # Edges first so they sit under the nodes.
    lookup = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = lookup.get(e.get("from"))
        dst = lookup.get(e.get("to"))
        if not (src and dst):
            continue
        sx = float(src.get("x", 0)) + float(src.get("w", 60)) / 2
        sy = float(src.get("y", 0)) + float(src.get("h", 40)) / 2
        dx = float(dst.get("x", 0)) + float(dst.get("w", 60)) / 2
        dy = float(dst.get("y", 0)) + float(dst.get("h", 40)) / 2
        parts.append(
            f'<line x1="{sx:.2f}" y1="{sy:.2f}" x2="{dx:.2f}" y2="{dy:.2f}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>'
        )
        parts.append(
            f'<polygon points="{dx:.2f},{dy:.2f} '
            f'{dx - 6:.2f},{dy - 4:.2f} {dx - 6:.2f},{dy + 4:.2f}" '
            f'fill="{stroke}"/>'
        )
    for n in nodes:
        if not isinstance(n, dict):
            continue
        x = float(n.get("x", 0))
        y = float(n.get("y", 0))
        w = float(n.get("w", 120))
        h = float(n.get("h", 40))
        label = html.escape(str(n.get("label", n.get("id", ""))))
        fillcol = html.escape(str(n.get("fill", node_fill)))
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
            f'fill="{fillcol}" stroke="{stroke}" stroke-width="{sw}"/>'
        )
        parts.append(
            f'<text x="{x + w / 2:.2f}" y="{y + h / 2 + 4:.2f}" font-size="11" '
            f'text-anchor="middle" fill="{text_color}">{label}</text>'
        )
    return _svg_root("".join(parts), W, H, g.title)
