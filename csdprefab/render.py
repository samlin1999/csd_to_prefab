# -*- coding: utf-8 -*-
"""Rasterises a generated .prefab the way Cocos Creator would, for verification only.

Labels are deliberately not drawn: glyph metrics differ from Cocos Studio's, and csdview
classifies those regions as 'text' in its own report anyway.
"""
import glob
import io
import json
import math
import os

from PIL import Image, ImageChops


def creator_sliced(img, width, height, insets):
    """Port of Cocos Creator 3.8's sliced assembler. insets = (left, top, right, bottom).

    Creator clamps the middle span to zero and scales the caps up when left+right exceeds
    the width - it does NOT leave a hole - but the caps then get badly distorted, which is
    why images.resolve_border avoids that situation in the first place.
    """
    sw, sh = img.size
    left, top, right, bottom = [float(v) for v in insets]
    sizable_w = max(0.0, width - left - right)
    sizable_h = max(0.0, height - top - bottom)
    x_scale = min(1.0, width / (left + right)) if (left + right) else 1.0
    y_scale = min(1.0, height / (top + bottom)) if (top + bottom) else 1.0
    lw, rw = left * x_scale, right * x_scale
    th, bh = top * y_scale, bottom * y_scale

    col = [0.0, lw, lw + sizable_w, float(width)]
    row = [0.0, bh, bh + sizable_h, float(height)]
    src_col = [0.0, left, sw - right, float(sw)]
    src_row = [0.0, top, sh - bottom, float(sh)]

    out = Image.new('RGBA', (max(1, int(round(width))), max(1, int(round(height)))),
                    (0, 0, 0, 0))
    for r in range(3):
        for c in range(3):
            dw, dh = col[c + 1] - col[c], row[r + 1] - row[r]
            sx0, sx1 = src_col[c], src_col[c + 1]
            sy0, sy1 = src_row[2 - r], src_row[3 - r]     # dest row 0 is the bottom
            if dw <= 0 or dh <= 0 or sx1 - sx0 <= 0 or sy1 - sy0 <= 0:
                continue
            piece = img.crop((int(sx0), int(sy0), int(sx1), int(sy1)))
            piece = piece.resize((max(1, int(round(dw))), max(1, int(round(dh)))),
                                 Image.BILINEAR)
            out.alpha_composite(piece, (int(round(col[c])), int(round(height - row[r + 1]))))
    return out


def build_frame_index(assets_root, subdirs):
    """spriteFrame uuid -> (image path, spriteFrame userData) for the folders given."""
    index = {}
    for sub in subdirs:
        pattern = os.path.join(assets_root, sub, '**', '*.meta')
        for meta in glob.glob(pattern, recursive=True):
            if not meta.lower().endswith(('.png.meta', '.jpg.meta')):
                continue
            try:
                with io.open(meta, encoding='utf-8') as fh:
                    data = json.load(fh)
            except ValueError:
                continue
            sub_meta = (data.get('subMetas') or {}).get('f9941')
            if sub_meta:
                index[sub_meta['uuid']] = (meta[:-5], sub_meta['userData'])
    return index


class Renderer(object):
    def __init__(self, project_root, frame_index, prefab_by_uuid):
        self.root = project_root
        self.frames = frame_index
        self.prefabs = prefab_by_uuid          # prefab uuid -> loaded object list

    def render(self, objs, canvas_size, origin):
        canvas = Image.new('RGBA', canvas_size, (0, 0, 0, 255))
        self._draw(canvas, objs, 1, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, origin)
        return canvas

    def _draw(self, canvas, objs, nid, ox, oy, sx, sy, rot, alpha, origin):
        n = objs[nid]
        if n.get('_name') is None:
            self._draw_nested(canvas, objs, n, ox, oy, sx, sy, rot, alpha, origin)
            return
        if not n.get('_active', True):
            return
        lp, ls = n['_lpos'], n['_lscale']
        cos, sin = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        wx = ox + cos * sx * lp['x'] - sin * sy * lp['y']
        wy = oy + sin * sx * lp['x'] + cos * sy * lp['y']
        crot = rot + n['_euler']['z']
        csx, csy = sx * ls['x'], sy * ls['y']
        state = self._read_components(objs, n, alpha)
        if state['sprite'] and state['size']:
            self._paste(canvas, state, wx, wy, csx, csy, crot, origin)
        for ref in n['_children']:
            self._draw(canvas, objs, ref['__id__'], wx, wy, csx, csy, crot,
                       state['alpha'], origin)

    def _draw_nested(self, canvas, objs, node, ox, oy, sx, sy, rot, alpha, origin):
        info = objs[node['_prefab']['__id__']]
        child = self.prefabs.get(info['asset']['__uuid__'])
        if child is None:
            return
        overrides = {}
        for ref in objs[info['instance']['__id__']]['propertyOverrides']:
            o = objs[ref['__id__']]
            overrides[o['propertyPath'][0]] = o['value']
        if overrides.get('_active') is False:
            return
        lp = overrides.get('_lpos', {'x': 0, 'y': 0})
        ls = overrides.get('_lscale', {'x': 1, 'y': 1})
        euler = overrides.get('_euler', {'z': 0})
        cos, sin = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        self._draw(canvas, child, 1,
                   ox + cos * sx * lp['x'] - sin * sy * lp['y'],
                   oy + sin * sx * lp['x'] + cos * sy * lp['y'],
                   sx * ls['x'], sy * ls['y'], rot + euler['z'], alpha, origin)

    @staticmethod
    def _read_components(objs, node, alpha):
        state = {'size': None, 'anchor': None, 'sprite': None, 'alpha': alpha}
        for ref in node['_components']:
            comp = objs[ref['__id__']]
            kind = comp['__type__']
            if kind == 'cc.UITransform':
                state['size'] = (comp['_contentSize']['width'], comp['_contentSize']['height'])
                state['anchor'] = (comp['_anchorPoint']['x'], comp['_anchorPoint']['y'])
            elif kind == 'cc.Sprite' and comp.get('_spriteFrame'):
                state['sprite'] = comp
            elif kind == 'cc.UIOpacity':
                state['alpha'] = alpha * comp['_opacity'] / 255.0
        return state

    def _paste(self, canvas, state, wx, wy, csx, csy, rot, origin):
        hit = self.frames.get(state['sprite']['_spriteFrame']['__uuid__'])
        if not hit:
            return
        path, user_data = hit
        img = Image.open(path).convert('RGBA')
        w, h = abs(csx * state['size'][0]), abs(csy * state['size'][1])
        if state['sprite'].get('_type') == 1:
            insets = (user_data.get('borderLeft', 0), user_data.get('borderTop', 0),
                      user_data.get('borderRight', 0), user_data.get('borderBottom', 0))
            img = creator_sliced(img, w, h, insets)
        else:
            img = img.resize((max(1, int(round(w))), max(1, int(round(h)))), Image.BILINEAR)
        img = self._tint(img, state)
        if rot:
            # A node rotates about its anchor point, not about the image centre, so the
            # content box centre has to be rotated around the anchor before placing the
            # expanded bitmap. Skipping that rotation biases any off-centre anchor.
            img = img.rotate(rot, resample=Image.BICUBIC, expand=True)
            cx = (0.5 - state['anchor'][0]) * csx * state['size'][0]
            cy = (0.5 - state['anchor'][1]) * csy * state['size'][1]
            cos, sin = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            px = wx + cos * cx - sin * cy - img.size[0] / 2.0
            py = wy + sin * cx + cos * cy - img.size[1] / 2.0
        else:
            px = wx - state['anchor'][0] * csx * state['size'][0]
            py = wy - state['anchor'][1] * csy * state['size'][1]
        layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        layer.paste(img, (int(round(px - origin[0])),
                          int(round(origin[1] - py - img.size[1]))))
        canvas.alpha_composite(layer)

    @staticmethod
    def _tint(img, state):
        col = state['sprite']['_color']
        if (col['r'], col['g'], col['b']) != (255, 255, 255):
            img = ImageChops.multiply(img, Image.new('RGBA', img.size,
                                                     (col['r'], col['g'], col['b'], 255)))
        if state['alpha'] < 1.0:
            img.putalpha(img.getchannel('A').point(lambda v: int(v * state['alpha'])))
        return img
