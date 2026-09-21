"""
Realistic Animated Avatar Engine for MARK-54 JARVIS HUD.

Renders a high-fidelity photorealistic human avatar with:
  - Natural biological eyelid blinking
  - Real-time mouth articulation & viseme-synchronized speech
  - Eye gaze saccades & tracking
  - Organic breathing & micro-sway motion
  - Futuristic holographic segmented neon HUD rings
  - Dynamic audio frequency spectrum / equalizer
  - Real-time conversation state visualizer
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient,
)


def _rate(dt: float, tau: float) -> float:
    """Frame-rate independent exponential interpolation factor."""
    return 1.0 - math.exp(-max(0.0001, dt) / max(0.001, tau))


class RealisticAvatar:
    """High-fidelity photorealistic animated avatar with real-time lip sync and HUD rings."""

    SPAN = 1.95

    def __init__(self) -> None:
        self.face_path = Path(__file__).resolve().parent / "avatar_face.png"
        self._pixmap = QPixmap(str(self.face_path)) if self.face_path.exists() else QPixmap()

        self._t = 0.0
        self._dt = 0.016

        # State and energy
        self._state = "LISTENING"
        self._amp = 0.0
        self._amp_smooth = 0.0
        self._speaking = False
        self._muted = False

        # Blinking mechanics
        self._blink = 0.0          # 0 = open, 1 = closed
        self._blink_target = 0.0
        self._blink_next = time.time() + random.uniform(2.5, 4.5)
        self._blink_speed = 18.0

        # Gaze / Saccades mechanics
        self._gaze_x = 0.0
        self._gaze_y = 0.0
        self._gaze_tx = 0.0
        self._gaze_ty = 0.0
        self._gaze_next = time.time() + 1.5

        # Mouth & Viseme mechanics
        self._mouth_open = 0.0     # 0..1 opening
        self._mouth_target = 0.0
        self._mouth_wide = 0.0     # -1..+1 spread
        self._v_open = 0.0
        self._v_wide = 0.0
        self._v_level = 0.0
        self._closure = 0.0

        # Motion & Sway
        self._sway_x = 0.0
        self._sway_y = 0.0
        self._sway_rot = 0.0

        # Neon HUD Ring rotation
        self._ring_angle1 = 0.0
        self._ring_angle2 = 0.0

        # Equalizer bands (32 symmetrical frequency bars)
        self._eq_bands = [0.0] * 32

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Direct the avatar gaze toward a relative target."""
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
        """Advance avatar animation frame."""
        self._dt = dt
        self._t += dt
        self._amp = max(0.0, min(1.0, amp))
        self._amp_smooth += (self._amp - self._amp_smooth) * _rate(dt, 0.05)
        self._speaking = speaking
        self._muted = muted
        if state:
            self._state = state.upper()

        now = time.time()

        # ── 1. Blinking Logic ──
        if now >= self._blink_next:
            self._blink_target = 1.0
            self._blink_next = now + random.uniform(2.8, 5.2)

        if self._blink_target > 0.5:
            self._blink += self._blink_speed * dt
            if self._blink >= 1.0:
                self._blink = 1.0
                self._blink_target = 0.0
        else:
            self._blink -= (self._blink_speed * 0.85) * dt
            if self._blink <= 0.0:
                self._blink = 0.0

        # Low lids when muted/sleeping
        if self._muted:
            self._blink = max(self._blink, 0.7)

        # ── 2. Gaze Saccades ──
        if now >= self._gaze_next:
            if "THINK" in self._state:
                self._gaze_tx = random.choice([-0.8, 0.8])
                self._gaze_ty = -0.4
            elif self._speaking:
                self._gaze_tx = random.uniform(-0.3, 0.3)
                self._gaze_ty = random.uniform(-0.2, 0.2)
            else:
                self._gaze_tx = random.uniform(-0.15, 0.15)
                self._gaze_ty = random.uniform(-0.1, 0.1)
            self._gaze_next = now + random.uniform(1.2, 3.0)

        self._gaze_x += (self._gaze_tx - self._gaze_x) * _rate(dt, 0.08)
        self._gaze_y += (self._gaze_ty - self._gaze_y) * _rate(dt, 0.08)

        # ── 3. Mouth & Visemes ──
        if speaking:
            shape = v_open if v_open is not None else 1.0
            level = v_level if v_level is not None else self._amp
            drive = max(0.0, min(1.0, (level ** 0.75) * 1.8)) * (shape ** 0.8)
            self._mouth_target = drive
            self._mouth_wide += (v_wide - self._mouth_wide) * _rate(dt, 0.03)
        else:
            self._mouth_target = 0.0
            self._mouth_wide += (0.0 - self._mouth_wide) * _rate(dt, 0.08)

        tau = 0.02 if self._mouth_target > self._mouth_open else 0.04
        self._mouth_open += (self._mouth_target - self._mouth_open) * _rate(dt, tau)
        if self._mouth_open < 0.005:
            self._mouth_open = 0.0

        # ── 4. Sway & Breathing ──
        self._sway_x = math.sin(self._t * 0.8) * 2.5 + (self._gaze_x * 3.0)
        self._sway_y = math.sin(self._t * 1.4) * 3.0 + (0.5 if speaking else 0.0)
        self._sway_rot = math.sin(self._t * 0.6) * 0.8

        # ── 5. Ring Rotation ──
        speed = 45.0 if speaking else (25.0 if "THINK" in self._state else 12.0)
        self._ring_angle1 = (self._ring_angle1 + speed * dt) % 360.0
        self._ring_angle2 = (self._ring_angle2 - (speed * 0.7) * dt) % 360.0

        # ── 6. Equalizer Simulation ──
        for i in range(16):
            freq_bias = math.sin((i / 16.0) * math.pi)
            target_h = self._amp_smooth * freq_bias * (0.8 + 0.4 * math.sin(self._t * 14.0 + i))
            if not speaking and self._amp < 0.05:
                target_h = 0.02 * math.sin(self._t * 2.0 + i)
            self._eq_bands[i] += (target_h - self._eq_bands[i]) * _rate(dt, 0.06)
            self._eq_bands[31 - i] = self._eq_bands[i]

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
        """Render the complete realistic avatar, HUD rings, equalizer, and state."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # ── 1. Aura Glow Behind Head ──
        aura_r = r * 1.35
        glow_grad = QRadialGradient(cx, cy - 20, aura_r)
        glow_alpha = int(45 + self._amp_smooth * 80 + (40 if self._speaking else 0))
        glow_col = QColor(primary)
        glow_col.setAlpha(min(200, glow_alpha))
        glow_grad.setColorAt(0.0, glow_col)
        glow_grad.setColorAt(0.65, QColor(primary.red(), primary.green(), primary.blue(), 15))
        glow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(cx - aura_r, cy - 20 - aura_r, aura_r * 2, aura_r * 2), QBrush(glow_grad))

        # ── 2. Segmented Neon HUD Rings ──
        self._draw_hud_rings(p, cx, cy - 20, r * 1.18, primary)

        # ── 3. Draw Photorealistic Head ──
        head_w = r * 1.95
        head_h = head_w * (400.0 / 360.0)
        head_rect = QRectF(
            cx - head_w / 2.0 + self._sway_x,
            cy - head_h / 2.0 - 25.0 + self._sway_y,
            head_w,
            head_h,
        )

        p.save()
        p.translate(head_rect.center())
        p.rotate(self._sway_rot)
        p.translate(-head_rect.center())

        if not self._pixmap.isNull():
            p.drawPixmap(head_rect.toRect(), self._pixmap)

            # Draw Real-time Eyelid Blinking
            self._draw_eyelids(p, head_rect)

            # Draw Real-time Lip-Sync Talking & Mouth Deformation
            if self._mouth_open > 0.01:
                self._draw_mouth_articulation(p, head_rect)

        p.restore()

        # ── 4. Symmetrical Audio Equalizer ──
        self._draw_equalizer(p, cx, cy + r * 0.82, r * 1.2, primary)

        # ── 5. Status Text (LISTENING / THINKING / SPEAKING) ──
        self._draw_status_text(p, cx, cy + r * 1.04, primary)

        p.restore()

    def _draw_hud_rings(self, p: QPainter, cx: float, cy: float, r: float, color: QColor) -> None:
        """Draw futuristic glowing cyan HUD arc segments."""
        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        # Outer Ring Arc 1
        pen.setColor(QColor(color.red(), color.green(), color.blue(), 190))
        pen.setWidthF(3.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        arc_span = 85.0
        p.drawArc(
            QRectF(cx - r, cy - r, r * 2, r * 2),
            int((self._ring_angle1 + 35) * 16),
            int(arc_span * 16),
        )
        p.drawArc(
            QRectF(cx - r, cy - r, r * 2, r * 2),
            int((self._ring_angle1 + 215) * 16),
            int(arc_span * 16),
        )

        # Segmented tick marks
        pen.setColor(QColor(color.red(), color.green(), color.blue(), 140))
        pen.setWidthF(2.0)
        p.setPen(pen)
        for i in range(12):
            ang = math.radians(self._ring_angle2 + i * 30.0)
            r1 = r * 0.94
            r2 = r * 0.98
            p.drawLine(
                QPointF(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1),
                QPointF(cx + math.cos(ang) * r2, cy + math.sin(ang) * r2),
            )

        # Inner Accent Arcs
        r_in = r * 0.88
        pen.setColor(QColor(color.red(), color.green(), color.blue(), 80))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.drawArc(
            QRectF(cx - r_in, cy - r_in, r_in * 2, r_in * 2),
            int((-self._ring_angle1 + 10) * 16),
            int(45 * 16),
        )
        p.drawArc(
            QRectF(cx - r_in, cy - r_in, r_in * 2, r_in * 2),
            int((-self._ring_angle1 + 190) * 16),
            int(45 * 16),
        )

    def _draw_eyelids(self, p: QPainter, hr: QRectF) -> None:
        """Render natural curved eyelid blinks over left and right eye regions."""
        if self._blink < 0.01:
            return

        # Relative landmarks on 360x400 source image
        # Left eye: x ≈ 0.375, y ≈ 0.450, w ≈ 0.14, h ≈ 0.08
        # Right eye: x ≈ 0.625, y ≈ 0.450, w ≈ 0.14, h ≈ 0.08
        eyes = [
            (hr.left() + hr.width() * 0.305, hr.top() + hr.height() * 0.415, hr.width() * 0.145, hr.height() * 0.075),
            (hr.left() + hr.width() * 0.550, hr.top() + hr.height() * 0.415, hr.width() * 0.145, hr.height() * 0.075),
        ]

        lid_prog = min(1.0, max(0.0, self._blink))

        for ex, ey, ew, eh in eyes:
            p.save()
            clip_path = QPainterPath()
            clip_path.addEllipse(QRectF(ex - 2, ey - 2, ew + 4, eh + 4))
            p.setClipPath(clip_path)

            # Eyelid skin tone & depth shading
            lid_h = eh * lid_prog
            grad = QLinearGradient(ex, ey, ex, ey + lid_h)
            grad.setColorAt(0.0, QColor(48, 38, 34, int(255 * lid_prog)))
            grad.setColorAt(0.7, QColor(72, 54, 46, int(255 * lid_prog)))
            grad.setColorAt(1.0, QColor(25, 18, 15, int(255 * lid_prog)))

            lid_path = QPainterPath()
            lid_path.moveTo(ex, ey)
            lid_path.quadTo(ex + ew / 2.0, ey + lid_h * 1.15, ex + ew, ey)
            lid_path.lineTo(ex + ew, ey + lid_h)
            lid_path.quadTo(ex + ew / 2.0, ey + lid_h * 1.05, ex, ey + lid_h)
            lid_path.closeSubpath()

            p.fillPath(lid_path, QBrush(grad))

            # Upper lash line
            lash_pen = QPen(QColor(15, 10, 8, int(240 * lid_prog)), 1.8)
            p.setPen(lash_pen)
            lash_path = QPainterPath()
            lash_path.moveTo(ex, ey + lid_h * 0.95)
            lash_path.quadTo(ex + ew / 2.0, ey + lid_h * 1.1, ex + ew, ey + lid_h * 0.95)
            p.drawPath(lash_path)

            p.restore()

    def _draw_mouth_articulation(self, p: QPainter, hr: QRectF) -> None:
        """Render realistic mouth opening, teeth, and lip shape when speaking."""
        mx = hr.left() + hr.width() * 0.50
        my = hr.top() + hr.height() * 0.687
        mw = hr.width() * (0.17 + self._mouth_wide * 0.02)
        open_px = self._mouth_open * (hr.height() * 0.035)

        p.save()

        # 1. Inner Oral Cavity (Dark Depth with soft alpha edge)
        mouth_path = QPainterPath()
        mouth_path.moveTo(mx - mw / 2.0, my)
        mouth_path.quadTo(mx, my - open_px * 0.20, mx + mw / 2.0, my)
        mouth_path.quadTo(mx, my + open_px * 1.05, mx - mw / 2.0, my)
        mouth_path.closeSubpath()

        mouth_grad = QLinearGradient(mx, my - open_px * 0.2, mx, my + open_px)
        mouth_grad.setColorAt(0.0, QColor(12, 4, 4, 240))
        mouth_grad.setColorAt(0.5, QColor(38, 12, 14, 240))
        mouth_grad.setColorAt(1.0, QColor(18, 6, 7, 240))
        p.fillPath(mouth_path, QBrush(mouth_grad))

        # 2. Subtle Natural Upper Teeth
        if open_px > 2.5:
            teeth_path = QPainterPath()
            tw = mw * 0.58
            th = min(open_px * 0.35, 4.5)
            teeth_path.moveTo(mx - tw / 2.0, my)
            teeth_path.lineTo(mx + tw / 2.0, my)
            teeth_path.lineTo(mx + tw / 2.0, my + th)
            teeth_path.quadTo(mx, my + th * 1.05, mx - tw / 2.0, my + th)
            teeth_path.closeSubpath()

            teeth_grad = QLinearGradient(mx, my, mx, my + th)
            teeth_grad.setColorAt(0.0, QColor(200, 195, 190, 220))
            teeth_grad.setColorAt(1.0, QColor(120, 110, 105, 180))
            p.fillPath(teeth_path, QBrush(teeth_grad))

        # 3. Soft Upper & Lower Lip Contours
        upper_lip_pen = QPen(QColor(110, 60, 52, 160), 1.6)
        p.setPen(upper_lip_pen)
        upper_lip = QPainterPath()
        upper_lip.moveTo(mx - mw / 2.0, my)
        upper_lip.quadTo(mx, my - open_px * 0.20, mx + mw / 2.0, my)
        p.drawPath(upper_lip)

        lower_lip_pen = QPen(QColor(125, 68, 60, 180), 1.8)
        p.setPen(lower_lip_pen)
        lower_lip = QPainterPath()
        lower_lip.moveTo(mx - mw / 2.0, my)
        lower_lip.quadTo(mx, my + open_px * 1.05, mx + mw / 2.0, my)
        p.drawPath(lower_lip)

        # 4. Subtle Chin Shadow under lower lip
        if open_px > 1.0:
            shadow_pen = QPen(QColor(15, 8, 6, int(100 * self._mouth_open)), 2.0)
            p.setPen(shadow_pen)
            chin_shadow = QPainterPath()
            chin_shadow.moveTo(mx - mw * 0.4, my + open_px * 1.15)
            chin_shadow.quadTo(mx, my + open_px * 1.35, mx + mw * 0.4, my + open_px * 1.15)
            p.drawPath(chin_shadow)

        p.restore()

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

            # Center bar glow
            bar_grad = QLinearGradient(bx, cy - bar_h / 2.0, bx, cy + bar_h / 2.0)
            alpha = int(120 + val * 135)
            bar_grad.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), int(alpha * 0.4)))
            bar_grad.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), alpha))
            bar_grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), int(alpha * 0.4)))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(bar_grad))
            p.drawRoundedRect(
                QRectF(bx, cy - bar_h / 2.0, bar_w, bar_h),
                bar_w / 2.0,
                bar_w / 2.0,
            )

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
