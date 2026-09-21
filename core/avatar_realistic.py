"""
Pure 3D Procedural Human Avatar Renderer for MARK-54 JARVIS HUD.

Renders a full 3D human head with:
  - 3D MediaPipe Measured Anatomical Facial Mesh (468 vertices, 898 facets)
  - 3D Real Human Skin Shading with Subsurface Melanin Gradient
  - 3D Anatomical Eyes (Sclera, Multi-tone Iris, Dilated Pupil, Corneal Specular Glint)
  - 3D Biological Eyelid Blinking
  - 3D Articulated Mouth (Mandible Jaw Hinge, 3D Teeth Arch, Dynamic Viseme Lips)
  - 3D Anatomical Eyebrows & Cranial Hair Volume
  - 3D Gaze Saccades & Head Motion
  - Holographic Segmented Neon HUD Rings & Live Audio Equalizer
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter,
    QPainterPath, QPen, QPolygonF, QRadialGradient,
)

from core.avatar_mesh import JAW_MAX, JAW_PIVOT, get_head_mesh

_CAM_D = 4.6
_LUT_N = 256


def _rate(dt: float, tau: float) -> float:
    return 1.0 - math.exp(-max(0.0001, dt) / max(0.001, tau))


class RealisticAvatar:
    """True 3D procedural human avatar with real anatomical mesh and realistic rendering."""

    SPAN = 1.95

    def __init__(self) -> None:
        # Load 3D Face Mesh & Topology
        mesh = get_head_mesh()
        self._v0 = mesh["verts"]
        self._n0 = mesh["normals"]
        self._jaw = mesh["jaw"]
        self._brow_w = mesh["brow"]
        self._lips_w = mesh["lips"]
        self._lip_c = mesh["lip_centre"]
        self._fade = mesh["fade"]
        self._f = mesh["faces"]
        self._fgroup = mesh["face_group"]
        self._fa, self._fb, self._fc = (self._f[:, i] for i in range(3))
        self._e0 = mesh["edges"][:, 0]
        self._e1 = mesh["edges"][:, 1]
        self._lm = mesh["landmarks"]

        self.SPAN = mesh["span"][0] - mesh["span"][1]

        n = self._v0.shape[0]
        self._v = np.empty((n, 3), dtype=np.float32)

        # Realistic Human Skin Tone LUT
        self._skin_lut: list[QColor] = self._build_skin_lut()

        # Animation states
        self._t = 0.0
        self._dt = 0.016
        self._yaw = 0.0
        self._pitch = 0.0
        self._roll = 0.0
        self._sway_phase = 0.0

        self._amp = 0.0
        self._amp_smooth = 0.0
        self._speaking = False
        self._muted = False
        self._state = "LISTENING"

        # Blinking mechanics
        self._blink = 0.0
        self._blink_target = 0.0
        self._blink_next = time.time() + random.uniform(2.5, 4.5)
        self._blink_speed = 16.0

        # Gaze / Saccades mechanics
        self._gaze_x = 0.0
        self._gaze_y = 0.0
        self._gaze_tx = 0.0
        self._gaze_ty = 0.0
        self._gaze_next = time.time() + 1.5

        # Mouth & Visemes
        self._mouth = 0.0
        self._mouth_target = 0.0
        self._wide = 0.0
        self._v_open = 0.0
        self._v_wide = 0.0
        self._v_level = 0.0
        self._brow = 0.0

        # HUD Rings & Equalizer
        self._ring_angle1 = 0.0
        self._ring_angle2 = 0.0
        self._eq_bands = [0.0] * 32

    def _build_skin_lut(self) -> list[QColor]:
        """Generate a photorealistic 256-step human skin tone lookup table with subsurface warmth."""
        lut = []
        # Key tones: deep shadow -> warm subsurface -> melanin midtone -> bright specular highlight
        stops = [
            (0.00, QColor(14, 6, 6)),       # ambient cavity occlusion
            (0.18, QColor(48, 20, 16)),      # deep shadow
            (0.38, QColor(122, 60, 42)),     # subsurface red/warm shadow
            (0.60, QColor(185, 118, 86)),    # primary healthy skin midtone
            (0.82, QColor(228, 168, 134)),   # well-lit surface
            (1.00, QColor(255, 224, 202)),   # specular highlight glint
        ]
        for i in range(_LUT_N):
            f = i / (_LUT_N - 1.0)
            # Find surrounding stops
            for j in range(len(stops) - 1):
                f0, c0 = stops[j]
                f1, c1 = stops[j + 1]
                if f0 <= f <= f1:
                    t = (f - f0) / max(0.0001, (f1 - f0))
                    r = int(c0.red() + (c1.red() - c0.red()) * t)
                    g = int(c0.green() + (c1.green() - c0.green()) * t)
                    b = int(c0.blue() + (c1.blue() - c0.blue()) * t)
                    lut.append(QColor(r, g, b))
                    break
        return lut

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Direct 3D avatar gaze towards a coordinate."""
        self._gaze_tx = max(-1.0, min(1.0, dx))
        self._gaze_ty = max(-1.0, min(1.0, dy))
        self._gaze_next = time.time() + hold

    def step(
        self,
        dt: float,
        amp: float,
        speaking: bool = False,
        muted: bool = False,
        state: str = "",
        v_open: float | None = None,
        v_wide: float = 0.0,
        v_level: float | None = None,
        v_seq: list | None = None,
        v_hop: float = 0.02,
    ) -> None:
        """Advance the 3D human animation frame."""
        self._dt = dt
        self._t += dt
        self._amp = max(0.0, min(1.0, amp))
        self._amp_smooth += (self._amp - self._amp_smooth) * _rate(dt, 0.05)
        self._speaking = speaking
        self._muted = muted
        if state:
            self._state = state.upper()

        now = time.time()

        # ── 1. Biological Blinking ──
        if now >= self._blink_next:
            self._blink_target = 1.0
            self._blink_next = now + random.uniform(2.6, 4.8)

        if self._blink_target > 0.5:
            self._blink += self._blink_speed * dt
            if self._blink >= 1.0:
                self._blink = 1.0
                self._blink_target = 0.0
        else:
            self._blink -= (self._blink_speed * 0.85) * dt
            if self._blink <= 0.0:
                self._blink = 0.0

        if self._muted:
            self._blink = max(self._blink, 0.75)

        # ── 2. Eye Gaze Saccades ──
        if now >= self._gaze_next:
            if "THINK" in self._state:
                self._gaze_tx = random.choice([-0.7, 0.7])
                self._gaze_ty = -0.35
            elif self._speaking:
                self._gaze_tx = random.uniform(-0.35, 0.35)
                self._gaze_ty = random.uniform(-0.25, 0.25)
            else:
                self._gaze_tx = random.uniform(-0.15, 0.15)
                self._gaze_ty = random.uniform(-0.1, 0.1)
            self._gaze_next = now + random.uniform(1.2, 3.2)

        self._gaze_x += (self._gaze_tx - self._gaze_x) * _rate(dt, 0.09)
        self._gaze_y += (self._gaze_ty - self._gaze_y) * _rate(dt, 0.09)

        # ── 3. 3D Mouth & Viseme Articulation ──
        if speaking:
            shape = v_open if v_open is not None else 1.0
            level = v_level if v_level is not None else self._amp
            drive = max(0.0, min(1.0, (level ** 0.7) * 1.7)) * (shape ** 0.8)
            self._mouth_target = drive
            self._wide += (v_wide - self._wide) * _rate(dt, 0.03)
            self._brow += (0.25 * drive - self._brow) * _rate(dt, 0.08)
        else:
            self._mouth_target = 0.0
            self._wide += (0.0 - self._wide) * _rate(dt, 0.08)
            self._brow += (0.0 - self._brow) * _rate(dt, 0.08)

        tau = 0.02 if self._mouth_target > self._mouth else 0.045
        self._mouth += (self._mouth_target - self._mouth) * _rate(dt, tau)
        if self._mouth < 0.003:
            self._mouth = 0.0

        # ── 4. 3D Head Sway & Tilts ──
        self._yaw = math.sin(self._t * 0.7) * 0.04 + (self._gaze_x * 0.06)
        self._pitch = math.sin(self._t * 1.1) * 0.03 + (self._gaze_y * 0.04) + (-0.03 if "THINK" in self._state else 0.0)
        self._roll = math.sin(self._t * 0.5) * 0.02

        # ── 5. HUD Rings & Equalizer ──
        speed = 45.0 if speaking else (25.0 if "THINK" in self._state else 12.0)
        self._ring_angle1 = (self._ring_angle1 + speed * dt) % 360.0
        self._ring_angle2 = (self._ring_angle2 - (speed * 0.7) * dt) % 360.0

        for i in range(16):
            freq_bias = math.sin((i / 16.0) * math.pi)
            target_h = self._amp_smooth * freq_bias * (0.8 + 0.4 * math.sin(self._t * 14.0 + i))
            if not speaking and self._amp < 0.05:
                target_h = 0.02 * math.sin(self._t * 2.0 + i)
            self._eq_bands[i] += (target_h - self._eq_bands[i]) * _rate(dt, 0.06)
            self._eq_bands[31 - i] = self._eq_bands[i]

    def _transform_3d_mesh(self) -> tuple[np.ndarray, np.ndarray]:
        """Apply 3D jaw hinge, brow lift, lip spread, and head rotation matrix."""
        v = self._v0.copy()

        # 1. 3D Jaw Hinge Rotation
        if self._mouth > 0.001:
            jaw_angle = self._mouth * JAW_MAX
            cos_j, sin_j = math.cos(jaw_angle), math.sin(jaw_angle)
            px, py, pz = JAW_PIVOT
            y_rel = v[:, 1] - py
            z_rel = v[:, 2] - pz
            y_rot = py + y_rel * cos_j - z_rel * sin_j
            z_rot = pz + y_rel * sin_j + z_rel * cos_j
            w = self._jaw[:, None]
            v[:, 1] = v[:, 1] * (1.0 - w[:, 0]) + y_rot * w[:, 0]
            v[:, 2] = v[:, 2] * (1.0 - w[:, 0]) + z_rot * w[:, 0]

        # 2. 3D Lip Viseme Deformation (Spread & Rounding)
        if abs(self._wide) > 0.01:
            v[:, 0] += self._wide * self._lips_w * 0.04

        # 3. 3D Eyebrow Raise
        if abs(self._brow) > 0.01:
            v[:, 1] += self._brow * self._brow_w * 0.035

        # 4. 3D Head Rotation Matrix (Yaw, Pitch, Roll)
        cy, sy = math.cos(self._yaw), math.sin(self._yaw)
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)
        cr, sr = math.cos(self._roll), math.sin(self._roll)

        R = np.array([
            [cy * cr + sy * sp * sr, -cy * sr + sy * sp * cr, sy * cp],
            [cp * sr, cp * cr, -sp],
            [-sy * cr + cy * sp * sr, sy * sr + cy * sp * cr, cy * cp],
        ], dtype=np.float32)

        v_rot = np.dot(v, R.T)
        n_rot = np.dot(self._n0, R.T)
        return v_rot, n_rot

    def paint(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        r: float,
        primary: QColor,
        accent: QColor,
        bg: QColor,
    ) -> None:
        """Render the complete 3D realistic human head, 3D anatomical eyes, mouth, and HUD."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # ── 1. Holographic Aura ──
        aura_r = r * 1.35
        glow_grad = QRadialGradient(cx, cy - 20, aura_r)
        glow_alpha = int(40 + self._amp_smooth * 70 + (35 if self._speaking else 0))
        glow_col = QColor(primary.red(), primary.green(), primary.blue(), min(180, glow_alpha))
        glow_grad.setColorAt(0.0, glow_col)
        glow_grad.setColorAt(0.65, QColor(primary.red(), primary.green(), primary.blue(), 12))
        glow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(cx - aura_r, cy - 20 - aura_r, aura_r * 2, aura_r * 2), QBrush(glow_grad))

        # ── 2. Segmented Neon HUD Rings ──
        self._draw_hud_rings(p, cx, cy - 20, r * 1.18, primary)

        # ── 3. 3D Mesh Transformation & Camera Projection ──
        verts, norms = self._transform_3d_mesh()
        w = _CAM_D - verts[:, 2]
        np.maximum(w, 0.35, out=w)
        k = (_CAM_D / w) * (r * 0.95)
        xs = cx + verts[:, 0] * k
        ys = (cy - 20) - verts[:, 1] * k

        # ── 4. Paint 3D Realistic Human Skin Facets & Stubble ──
        self._paint_3d_skin_facets(p, xs, ys, norms, verts)

        # ── 5. Paint 3D Realistic Eyes ──
        self._paint_3d_eyes(p, xs, ys, verts, r)

        # ── 6. Paint 3D Lips & Teeth ──
        self._paint_3d_mouth(p, xs, ys, verts, r)

        # ── 7. Paint 3D Eyebrows & Hair ──
        self._paint_3d_brows_and_hair(p, xs, ys, verts, r)

        # ── 8. Symmetrical Audio Equalizer & Status ──
        self._draw_equalizer(p, cx, cy + r * 0.82, r * 1.2, primary)
        self._draw_status_text(p, cx, cy + r * 1.04, primary)

        p.restore()

    def _paint_3d_skin_facets(
        self,
        p: QPainter,
        xs: np.ndarray,
        ys: np.ndarray,
        norms: np.ndarray,
        verts: np.ndarray,
    ) -> None:
        """Rasterize 3D triangle facets with multi-light subsurface human skin shading."""
        a, b, c = self._fa, self._fb, self._fc

        # Per-facet 3D normal vectors
        fn = np.cross(verts[b] - verts[a], verts[c] - verts[a])
        fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
        ref = norms[a] + norms[b] + norms[c]
        fn *= np.sign((fn * ref).sum(1))[:, None]

        nz = fn[:, 2]
        area = np.abs((xs[b] - xs[a]) * (ys[c] - ys[a]) - (xs[c] - xs[a]) * (ys[b] - ys[a]))
        vis = np.flatnonzero((nz > 0.015) & (area > 2.0))
        if vis.size == 0:
            return

        fn = fn[vis]
        nz = nz[vis]
        ax, ay = xs[a][vis], ys[a][vis]
        bx, by = xs[b][vis], ys[b][vis]
        cxx, cyy = xs[c][vis], ys[c][vis]

        # Multi-light calculation (Key Light high-left, Soft Rim Light, Ambient Subsurface)
        lam_key = np.clip(fn[:, 0] * -0.50 + fn[:, 1] * 0.55 + nz * 0.55, 0.0, 1.0)
        rim_light = np.clip(1.0 - nz, 0.0, 1.0) ** 1.8
        bright = 0.22 + 0.65 * (lam_key ** 1.1) + 0.18 * rim_light
        bright *= (self._fade[a][vis] + self._fade[b][vis] + self._fade[c][vis]) / 3.0

        # Subtle beard / stubble darkening on lower face
        mid_y = (verts[a, 1][vis] + verts[b, 1][vis] + verts[c, 1][vis]) * (1.0 / 3.0)
        mid_x = (verts[a, 0][vis] + verts[b, 0][vis] + verts[c, 0][vis]) * (1.0 / 3.0)
        stubble = np.where((mid_y < -0.12) & (np.abs(mid_x) < 0.48), 0.82, 1.0)
        bright *= stubble

        idx = np.clip((bright * _LUT_N).astype(np.int32), 0, _LUT_N - 1)

        # Depth sorting (Back-to-Front Painter's Algorithm)
        fz = (verts[a, 2][vis] + verts[b, 2][vis] + verts[c, 2][vis]) * (1.0 / 3.0)
        order = np.argsort(self._fgroup[vis] * 1000.0 + fz, kind="stable")
        tris = np.stack([ax, ay, bx, by, cxx, cyy], axis=1)[order].tolist()
        shade = idx[order].tolist()

        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        for q, sh in zip(tris, shade):
            p.setBrush(self._skin_lut[sh])
            p.drawPolygon(QPolygonF([
                QPointF(q[0], q[1]),
                QPointF(q[2], q[3]),
                QPointF(q[4], q[5]),
            ]))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _paint_3d_eyes(
        self,
        p: QPainter,
        xs: np.ndarray,
        ys: np.ndarray,
        verts: np.ndarray,
        r: float,
    ) -> None:
        """Render 3D anatomical eyeballs with iris, pupil, specular highlights, and eyelid blinking."""
        for side, eye_ring in [("l", self._lm["eye_l"]), ("r", self._lm["eye_r"])]:
            ex = float(np.mean(xs[eye_ring]))
            ey = float(np.mean(ys[eye_ring]))
            ew = float(np.max(xs[eye_ring]) - np.min(xs[eye_ring])) * 1.05
            eh = float(np.max(ys[eye_ring]) - np.min(ys[eye_ring])) * 1.15
            if ew < 4.0 or eh < 3.0:
                continue

            eye_rect = QRectF(ex - ew / 2.0, ey - eh / 2.0, ew, eh)

            p.save()
            eye_clip = QPainterPath()
            eye_clip.addEllipse(eye_rect)
            p.setClipPath(eye_clip)

            # 1. 3D Eyeball Sclera (White with soft shadow)
            sclera_grad = QRadialGradient(ex, ey, ew * 0.6)
            sclera_grad.setColorAt(0.0, QColor(245, 248, 250))
            sclera_grad.setColorAt(0.85, QColor(210, 215, 220))
            sclera_grad.setColorAt(1.0, QColor(160, 165, 170))
            p.fillRect(eye_rect, QBrush(sclera_grad))

            # 2. 3D Iris with Colored Fibers (Deep Slate / Cyan-Amber)
            iris_r = ew * 0.28
            ix = ex + (self._gaze_x * ew * 0.22)
            iy = ey + (self._gaze_y * eh * 0.22)
            iris_rect = QRectF(ix - iris_r, iy - iris_r, iris_r * 2, iris_r * 2)

            iris_grad = QRadialGradient(ix, iy, iris_r)
            iris_grad.setColorAt(0.0, QColor(12, 10, 10))      # pupil boundary
            iris_grad.setColorAt(0.35, QColor(28, 64, 85))     # deep blue/cyan iris
            iris_grad.setColorAt(0.75, QColor(45, 110, 140))   # vibrant iris ring
            iris_grad.setColorAt(1.0, QColor(15, 30, 42))      # limbal ring
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(iris_grad))
            p.drawEllipse(iris_rect)

            # 3. 3D Black Pupil
            pupil_r = iris_r * 0.42
            p.setBrush(QBrush(QColor(8, 8, 10)))
            p.drawEllipse(QRectF(ix - pupil_r, iy - pupil_r, pupil_r * 2, pupil_r * 2))

            # 4. Sharp Corneal Specular Glint (Light Reflection)
            glint_x = ix - iris_r * 0.35
            glint_y = iy - iris_r * 0.35
            p.setBrush(QBrush(QColor(255, 255, 255, 240)))
            p.drawEllipse(QRectF(glint_x, glint_y, iris_r * 0.25, iris_r * 0.25))

            # 5. 3D Eyelid Blinking Closure
            if self._blink > 0.01:
                lid_h = eh * self._blink * 1.1
                lid_grad = QLinearGradient(ex, ey - eh / 2.0, ex, ey - eh / 2.0 + lid_h)
                lid_grad.setColorAt(0.0, QColor(75, 38, 28))
                lid_grad.setColorAt(0.7, QColor(140, 80, 58))
                lid_grad.setColorAt(1.0, QColor(50, 22, 16))

                lid_path = QPainterPath()
                lid_path.moveTo(ex - ew / 2.0, ey - eh / 2.0)
                lid_path.lineTo(ex + ew / 2.0, ey - eh / 2.0)
                lid_path.lineTo(ex + ew / 2.0, ey - eh / 2.0 + lid_h)
                lid_path.quadTo(ex, ey - eh / 2.0 + lid_h * 1.08, ex - ew / 2.0, ey - eh / 2.0 + lid_h)
                lid_path.closeSubpath()
                p.fillPath(lid_path, QBrush(lid_grad))

                # Upper Eyelash Line
                p.setPen(QPen(QColor(20, 10, 8, int(230 * self._blink)), 1.8))
                p.drawLine(
                    QPointF(ex - ew / 2.0, ey - eh / 2.0 + lid_h),
                    QPointF(ex + ew / 2.0, ey - eh / 2.0 + lid_h),
                )

            p.restore()

    def _paint_3d_mouth(
        self,
        p: QPainter,
        xs: np.ndarray,
        ys: np.ndarray,
        verts: np.ndarray,
        r: float,
    ) -> None:
        """Render 3D articulated lips, inner mouth depth, and upper teeth when speaking."""
        lips_out = self._lm["lips_out"]
        mx = float(np.mean(xs[lips_out]))
        my = float(np.mean(ys[lips_out]))
        mw = float(np.max(xs[lips_out]) - np.min(xs[lips_out])) * 1.05
        mh = float(np.max(ys[lips_out]) - np.min(ys[lips_out]))

        p.save()

        # 1. When mouth is open: render inner oral cavity and teeth arch
        if self._mouth > 0.02:
            open_px = self._mouth * (r * 0.14)
            mouth_path = QPainterPath()
            mouth_path.moveTo(mx - mw * 0.42, my)
            mouth_path.quadTo(mx, my - open_px * 0.25, mx + mw * 0.42, my)
            mouth_path.quadTo(mx, my + open_px * 1.15, mx - mw * 0.42, my)
            mouth_path.closeSubpath()

            oral_grad = QLinearGradient(mx, my - open_px * 0.2, mx, my + open_px)
            oral_grad.setColorAt(0.0, QColor(12, 4, 4, 250))
            oral_grad.setColorAt(0.6, QColor(48, 14, 16, 250))
            oral_grad.setColorAt(1.0, QColor(20, 6, 8, 250))
            p.fillPath(mouth_path, QBrush(oral_grad))

            # 3D Upper Teeth Row
            if open_px > 3.0:
                tw = mw * 0.55
                th = min(open_px * 0.4, 6.0)
                teeth_rect = QRectF(mx - tw / 2.0, my, tw, th)
                teeth_grad = QLinearGradient(mx, my, mx, my + th)
                teeth_grad.setColorAt(0.0, QColor(225, 220, 215))
                teeth_grad.setColorAt(1.0, QColor(135, 125, 120))
                p.fillRect(teeth_rect, QBrush(teeth_grad))

        # 2. 3D Fleshy Upper & Lower Lips
        lip_path = QPainterPath()
        lip_pts = [QPointF(xs[idx], ys[idx]) for idx in lips_out]
        lip_path.moveTo(lip_pts[0])
        for pt in lip_pts[1:]:
            lip_path.lineTo(pt)
        lip_path.closeSubpath()

        lip_col = QColor(155, 78, 68, 170)
        p.setPen(QPen(QColor(120, 52, 45, 190), 1.6))
        p.setBrush(QBrush(lip_col))
        p.drawPath(lip_path)

        p.restore()

    def _paint_3d_brows_and_hair(
        self,
        p: QPainter,
        xs: np.ndarray,
        ys: np.ndarray,
        verts: np.ndarray,
        r: float,
    ) -> None:
        """Render 3D anatomical eyebrows and volumetric styled hair."""
        p.save()

        # 1. Volumetric 3D Hair over Cranium & Crown
        # Find head top & forehead bounds
        hair_pts = np.flatnonzero((verts[:, 1] > 0.32) & (verts[:, 2] > -0.65))
        if hair_pts.size > 0:
            hx_min, hx_max = float(np.min(xs[hair_pts])), float(np.max(xs[hair_pts]))
            hy_min, hy_max = float(np.min(ys[hair_pts])), float(np.max(ys[hair_pts]))
            hw = (hx_max - hx_min) * 1.08
            hh = (hy_max - hy_min) * 1.15
            hcx = (hx_min + hx_max) / 2.0
            hcy = (hy_min + hy_max) / 2.0

            # Hair Volume Gradient (Dark Espresso Brown with warm highlights)
            hair_grad = QRadialGradient(hcx - hw * 0.15, hcy - hh * 0.25, hw * 0.65)
            hair_grad.setColorAt(0.0, QColor(48, 28, 22, 245))
            hair_grad.setColorAt(0.5, QColor(28, 15, 12, 250))
            hair_grad.setColorAt(1.0, QColor(14, 7, 6, 255))

            hair_path = QPainterPath()
            hair_path.moveTo(hcx - hw / 2.0, hcy + hh * 0.2)
            hair_path.quadTo(hcx - hw * 0.45, hcy - hh * 0.65, hcx, hcy - hh * 0.6)
            hair_path.quadTo(hcx + hw * 0.45, hcy - hh * 0.65, hcx + hw / 2.0, hcy + hh * 0.2)
            # Forehead hairline
            hair_path.quadTo(hcx + hw * 0.25, hcy - hh * 0.15, hcx, hcy - hh * 0.25)
            hair_path.quadTo(hcx - hw * 0.25, hcy - hh * 0.15, hcx - hw / 2.0, hcy + hh * 0.2)
            hair_path.closeSubpath()

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(hair_grad))
            p.fillPath(hair_path, QBrush(hair_grad))

            # Hair Strands & Styling Highlights
            strand_pen = QPen(QColor(70, 42, 34, 160), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(strand_pen)
            for s in range(5):
                so = (s - 2) * (hw * 0.12)
                sp = QPainterPath()
                sp.moveTo(hcx + so - hw * 0.1, hcy - hh * 0.5)
                sp.quadTo(hcx + so, hcy - hh * 0.35, hcx + so + hw * 0.08, hcy - hh * 0.15)
                p.drawPath(sp)

        # 2. 3D Anatomical Eyebrows
        brow_pen = QPen(QColor(32, 16, 12, 235), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(brow_pen)

        for brow_ring in [self._lm["brow_l"], self._lm["brow_r"]]:
            brow_path = QPainterPath()
            brow_path.moveTo(xs[brow_ring[0]], ys[brow_ring[0]])
            for idx in brow_ring[1:]:
                brow_path.lineTo(xs[idx], ys[idx])
            p.drawPath(brow_path)

        p.restore()

    def _draw_hud_rings(self, p: QPainter, cx: float, cy: float, r: float, color: QColor) -> None:
        """Draw futuristic glowing cyan HUD arc segments."""
        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        pen.setColor(QColor(color.red(), color.green(), color.blue(), 190))
        pen.setWidthF(3.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        arc_span = 85.0
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), int((self._ring_angle1 + 35) * 16), int(arc_span * 16))
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), int((self._ring_angle1 + 215) * 16), int(arc_span * 16))

        pen.setColor(QColor(color.red(), color.green(), color.blue(), 140))
        pen.setWidthF(2.0)
        p.setPen(pen)
        for i in range(12):
            ang = math.radians(self._ring_angle2 + i * 30.0)
            r1 = r * 0.94
            r2 = r * 0.98
            p.drawLine(QPointF(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1), QPointF(cx + math.cos(ang) * r2, cy + math.sin(ang) * r2))

        r_in = r * 0.88
        pen.setColor(QColor(color.red(), color.green(), color.blue(), 80))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.drawArc(QRectF(cx - r_in, cy - r_in, r_in * 2, r_in * 2), int((-self._ring_angle1 + 10) * 16), int(45 * 16))
        p.drawArc(QRectF(cx - r_in, cy - r_in, r_in * 2, r_in * 2), int((-self._ring_angle1 + 190) * 16), int(45 * 16))

    def _draw_equalizer(self, p: QPainter, cx: float, cy: float, total_w: float, color: QColor) -> None:
        """Render symmetrical glowing equalizer spectrum bars under the avatar."""
        p.save()
        num_bars = 32
        bar_gap = total_w / (num_bars * 1.25)
        bar_w = bar_gap * 0.65
        start_x = cx - (total_w / 2.0)

        for i in range(num_bars):
            val = self._eq_bands[i]
            bar_h = max(2.0, val * 48.0)
            bx = start_x + i * bar_gap

            bar_grad = QLinearGradient(bx, cy - bar_h / 2.0, bx, cy + bar_h / 2.0)
            alpha = int(120 + val * 135)
            bar_grad.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), int(alpha * 0.4)))
            bar_grad.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), alpha))
            bar_grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), int(alpha * 0.4)))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(bar_grad))
            p.drawRoundedRect(QRectF(bx, cy - bar_h / 2.0, bar_w, bar_h), bar_w / 2.0, bar_w / 2.0)

        p.restore()

    def _draw_status_text(self, p: QPainter, cx: float, cy: float, color: QColor) -> None:
        """Draw glowing futuristic status text (L I S T E N I N G)."""
        p.save()
        font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6.0)
        p.setFont(font)

        status_str = "L I S T E N I N G"
        if self._speaking:
            status_str = "S P E A K I N G"
        elif "THINK" in self._state:
            status_str = "T H I N K I N G"
        elif self._muted:
            status_str = "S T A N D B Y"

        p.setPen(QColor(color.red(), color.green(), color.blue(), 230))
        text_rect = QRectF(cx - 200, cy - 10, 400, 26)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, status_str)
        p.restore()
