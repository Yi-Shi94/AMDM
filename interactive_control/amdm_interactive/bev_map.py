"""Bird's-eye maps for the viewer: BEVMap (left-click places the target) and PathSketchMap (draw a path).

Camera-aligned (screen up = the MuJoCo camera's view direction), centred on the character, 1 m grid.
Positions are viewer world (x, y) in metres. Mouse wheel zooms.
"""
import math
from collections import deque
import numpy as np


class BEVMap:
    def __init__(self, size=520, scale=25.):
        import pygame
        self.pg = pygame
        pygame.display.init(); pygame.font.init()
        self.screen = pygame.display.set_mode((size, size))
        pygame.display.set_caption('Target map: left-click to place the target, wheel to zoom')
        self.font = pygame.font.SysFont(None, 20)
        self.size, self.scale = size, scale
        self.trail = deque(maxlen=900)
        self.arrived = False

    def _axes(self, azimuth):
        az = math.radians(azimuth)
        return np.array([math.cos(az), math.sin(az)]), np.array([math.sin(az), -math.cos(az)])

    def update(self, pos, body_yaw, azimuth, target_env, radius):
        """Draw; return the clicked point in viewer world (x, y), or None."""
        pg, c = self.pg, self.size / 2
        fwd, right = self._axes(azimuth)
        pos = np.asarray(pos, float)
        self.trail.append(pos.copy())
        to_px = lambda w: (int(c + (w - pos) @ right * self.scale), int(c - (w - pos) @ fwd * self.scale))
        click = None
        for e in pg.event.get():
            if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
                sx, sy = e.pos[0] - c, e.pos[1] - c
                click = pos + (sx / self.scale) * right + (-sy / self.scale) * fwd
            elif e.type == pg.MOUSEWHEEL:
                self.scale = float(np.clip(self.scale * (1.15 ** e.y), 5., 120.))
        s = self.screen
        s.fill((24, 26, 30))
        half = self.size / 2 / self.scale + 1
        lo = np.floor(pos - half * 1.5); hi = np.ceil(pos + half * 1.5)
        for gx in np.arange(lo[0], hi[0] + 1):
            pg.draw.line(s, (48, 52, 58), to_px(np.array([gx, lo[1]])), to_px(np.array([gx, hi[1]])), 1)
        for gy in np.arange(lo[1], hi[1] + 1):
            pg.draw.line(s, (48, 52, 58), to_px(np.array([lo[0], gy])), to_px(np.array([hi[0], gy])), 1)
        if len(self.trail) > 1:
            pg.draw.lines(s, (90, 140, 220), False, [to_px(p) for p in self.trail], 2)
        target = np.array([target_env[0], -target_env[1]])
        pg.draw.circle(s, (230, 70, 70), to_px(target), max(2, int(radius * self.scale)), 2)
        pg.draw.circle(s, (230, 70, 70), to_px(target), 4)
        tip = pos + .6 * np.array([math.cos(body_yaw), math.sin(body_yaw)])
        pg.draw.line(s, (250, 215, 60), to_px(pos), to_px(tip), 3)
        pg.draw.circle(s, (250, 215, 60), to_px(pos), 6)
        d = float(np.linalg.norm(target - pos))
        msg = f'target {d:.2f} m{"  reached" if self.arrived else ""}   |   {self.scale:.0f} px/m'
        s.blit(self.font.render(msg, True, (220, 220, 220)), (10, 8))
        pg.display.flip()
        return click


SPEEDS = (.5, 1., 1.5, 2.5, 3.5)                    # keys 1-5, m/s
FACINGS = ((0., 'forward'), (math.pi / 2, 'left'), (math.pi, 'backward'), (-math.pi / 2, 'right'))  # viewer CCW


class PathSketchMap(BEVMap):
    """Bird's-eye map for the path task: left-drag draws a path; on release it is handed to the viewer.

    Keys (map window focused): 1-5 speed presets, Up/Down speed +-0.25 m/s, Left/Right turn the facing offset
    by 15 deg, F jump to the next of forward / left / backward / right of travel, G random path (training
    generator), right-click stop here. Speed and facing
    changes also re-time the path being followed. The map stays still while a stroke is being drawn.
    """
    def __init__(self, size=620, scale=20., allow_facing=True):
        super().__init__(size, scale)
        self.pg.display.set_caption('Path map: drag draw | 1-5/Up/Down speed | Left/Right/F facing | G random | right-click stop')
        self.speed, self.facing_offset, self.allow_facing = SPEEDS[1], 0., allow_facing
        self.stroke, self.frozen = None, None

    @property
    def facing(self):
        """(offset from the walking direction in rad, viewer counter-clockwise; label)."""
        if not self.allow_facing:
            return 0., 'forward'
        deg = (math.degrees(self.facing_offset) + 180.) % 360. - 180.
        names = {0: 'forward', 90: 'left', -180: 'backward', 180: 'backward', -90: 'right'}
        name = names.get(int(round(deg)), 'left' if deg > 0 else 'right')
        return self.facing_offset, f'{name} {deg:+.0f} deg' if int(round(deg)) not in names else name

    def update(self, pos, body_yaw, azimuth, path_xy, path_speed, t):
        """Draw; return ('path', [viewer xy points]) on stroke release, ('stop', None) on right-click,
        ('random', None) on G, ('retime', None) after a speed/facing change, else None."""
        pg, c = self.pg, self.size / 2
        fwd, right = self._axes(azimuth)
        pos = np.asarray(pos, float)
        self.trail.append(pos.copy())
        centre = self.frozen if self.frozen is not None else pos
        to_px = lambda w: (int(c + (w - centre) @ right * self.scale), int(c - (w - centre) @ fwd * self.scale))
        to_world = lambda p: centre + ((p[0] - c) / self.scale) * right + (-(p[1] - c) / self.scale) * fwd
        out = None
        for e in pg.event.get():
            if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
                self.frozen = pos.copy(); centre = self.frozen
                self.stroke = [to_world(e.pos)]
            elif e.type == pg.MOUSEMOTION and self.stroke is not None:
                w = to_world(e.pos)
                if np.linalg.norm(w - self.stroke[-1]) > .05:self.stroke.append(w)
            elif e.type == pg.MOUSEBUTTONUP and e.button == 1 and self.stroke is not None:
                if len(self.stroke) > 1 or np.linalg.norm(self.stroke[0] - pos) > .3:out = ('path', self.stroke)
                self.stroke, self.frozen = None, None
            elif e.type == pg.MOUSEBUTTONDOWN and e.button == 3:
                out = ('stop', None)
            elif e.type == pg.MOUSEWHEEL:
                self.scale = float(np.clip(self.scale * (1.15 ** e.y), 4., 120.))
            elif e.type == pg.KEYDOWN:
                if pg.K_1 <= e.key <= pg.K_5:self.speed = SPEEDS[e.key - pg.K_1];out = out or ('retime', None)
                elif e.key in (pg.K_UP, pg.K_DOWN):
                    self.speed = float(np.clip(self.speed + (.25 if e.key == pg.K_UP else -.25), .25, 4.));out = out or ('retime', None)
                elif e.key in (pg.K_LEFT, pg.K_RIGHT) and self.allow_facing:  # left = counter-clockwise
                    step = math.radians(15.) * (1 if e.key == pg.K_LEFT else -1)
                    self.facing_offset = (self.facing_offset + step + math.pi) % (2 * math.pi) - math.pi
                    out = out or ('retime', None)
                elif e.key == pg.K_f and self.allow_facing:  # next preset after the current offset
                    presets = [f for f, _ in FACINGS]
                    now = (self.facing_offset % (2 * math.pi))
                    later = [f for f in presets if (f % (2 * math.pi)) > now + 1e-6]
                    nxt = min(later, key=lambda f: f % (2 * math.pi)) if later else presets[0]
                    self.facing_offset = (nxt + math.pi) % (2 * math.pi) - math.pi
                    out = out or ('retime', None)
                elif e.key == pg.K_g:out = ('random', None)
        s = self.screen
        s.fill((24, 26, 30))
        half = self.size / 2 / self.scale + 1
        lo = np.floor(centre - half * 1.5); hi = np.ceil(centre + half * 1.5)
        for gx in np.arange(lo[0], hi[0] + 1):
            pg.draw.line(s, (48, 52, 58), to_px(np.array([gx, lo[1]])), to_px(np.array([gx, hi[1]])), 1)
        for gy in np.arange(lo[1], hi[1] + 1):
            pg.draw.line(s, (48, 52, 58), to_px(np.array([lo[0], gy])), to_px(np.array([hi[0], gy])), 1)
        if len(self.trail) > 1:
            pg.draw.lines(s, (90, 140, 220), False, [to_px(p) for p in self.trail], 2)
        # Active path ahead of the current waypoint, coloured by commanded speed (blue slow -> red fast).
        for k in range(t, len(path_xy) - 1, 2):
            v = min(float(path_speed[k]) / 4., 1.)
            pg.draw.line(s, (int(60 + 195 * v), 80, int(255 - 195 * v)), to_px(path_xy[k]), to_px(path_xy[min(k + 2, len(path_xy) - 1)]), 3)
        pg.draw.circle(s, (230, 70, 70), to_px(path_xy[t]), 5)
        if self.stroke is not None and len(self.stroke) > 1:
            pg.draw.lines(s, (240, 240, 240), False, [to_px(p) for p in self.stroke], 2)
        tip = pos + .6 * np.array([math.cos(body_yaw), math.sin(body_yaw)])
        pg.draw.line(s, (250, 215, 60), to_px(pos), to_px(tip), 3)
        pg.draw.circle(s, (250, 215, 60), to_px(pos), 6)
        face = self.facing[1] + ('' if self.allow_facing else ' (policy is forward-only)')
        msg = f'speed {self.speed:.2f} m/s [1-5, Up/Down]   facing {face} [Left/Right, F]   random [G]   |   {self.scale:.0f} px/m'
        s.blit(self.font.render(msg, True, (220, 220, 220)), (10, 8))
        pg.display.flip()
        return out
