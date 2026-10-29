# -*- coding: utf-8 -*-
"""Checks that catch the mistakes this converter has actually made before.

Every one of these exists because it found a real bug: geometry (anchor conversion),
sliced insets (invisible / distorted frames), label strings (encoding), and referential
integrity (dangling __id__ / uuid collisions).
"""
import collections
import glob
import io
import json
import math
import os
import subprocess
import time
import xml.etree.ElementTree as ET

TOLERANCE_PX = 0.6


def load(path, attempts=3):
    """Read a generated file, tolerating a write that is in flight.

    Cocos Creator rewrites .meta and .prefab files as it re-imports, so a read can land
    mid-write. Retry briefly rather than failing with a bare JSONDecodeError.
    """
    last = None
    for attempt in range(attempts):
        try:
            with io.open(path, encoding='utf-8') as fh:
                return json.load(fh)
        except ValueError as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    raise ValueError('%s is not valid JSON - another process may be writing it (%s)'
                     % (path, last))


# --------------------------------------------------------------------- geometry
def prefab_rects(objs):
    """node path -> (left, bottom, w, h, is_label) as rotated AABBs in root space."""
    out, scroll_shift = {}, {}

    def walk(nid, ox, oy, sx, sy, rot, prefix):
        n = objs[nid]
        if n.get('_name') is None:
            return                                    # nested prefab instance: opaque here
        path = n['_name'] if not prefix else prefix + '/' + n['_name']
        lp, ls = n['_lpos'], n['_lscale']
        cos, sin = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        wx = ox + cos * sx * lp['x'] - sin * sy * lp['y']
        wy = oy + sin * sx * lp['x'] + cos * sy * lp['y']
        crot = rot + n['_euler']['z']
        csx, csy = sx * ls['x'], sy * ls['y']
        node_size = anchor = None
        is_label = False
        for ref in n['_components']:
            comp = objs[ref['__id__']]
            if comp['__type__'] == 'cc.UITransform':
                node_size = (comp['_contentSize']['width'], comp['_contentSize']['height'])
                anchor = (comp['_anchorPoint']['x'], comp['_anchorPoint']['y'])
            elif comp['__type__'] == 'cc.Label':
                is_label = True
        if node_size is not None:
            out[path] = _aabb(wx, wy, csx * node_size[0], csy * node_size[1], anchor, crot) \
                        + (is_label,)
        if n['_name'] == 'content' and prefix.endswith('/view'):
            scroll_shift[prefix[:-5]] = -lp['y']
        for ref in n['_children']:
            walk(ref['__id__'], wx, wy, csx, csy, crot, path)

    walk(1, 0.0, 0.0, 1.0, 1.0, 0.0, '')
    root = objs[1]['_name']
    trimmed = dict((k[len(root) + 1:], v) for k, v in out.items() if k != root)
    shifts = dict((k[len(root) + 1:], v) for k, v in scroll_shift.items())
    return trimmed, shifts


def _aabb(wx, wy, w, h, anchor, rot):
    x0, y0 = -anchor[0] * w, -anchor[1] * h
    cos, sin = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    xs, ys = [], []
    for dx, dy in ((x0, y0), (x0 + w, y0), (x0, y0 + h), (x0 + w, y0 + h)):
        xs.append(wx + cos * dx - sin * dy)
        ys.append(wy + sin * dx + cos * dy)
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def csdview_rects(csd_path):
    """Node rects from csdview, relative to the .csd root, y up. None if csdview is absent.

    csdview reports screenRect as [left, top, w, h] in a y-down canvas. The .csd root's
    own origin is its bottom-left, so the conversion needs the root's *bottom* edge
    (top + height) - using the top edge silently biases every node by the root's height
    whenever the root has a size, as a GameLayer with a canvas does.
    """
    try:
        raw = subprocess.check_output(['csdview', 'spec', csd_path, '--json'],
                                      stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    nodes = json.loads(raw.decode('utf-8'))['nodes']
    rx, ry, _, rh = nodes[0]['screenRect']
    origin_y = ry + rh
    out = {}
    for n in nodes[1:]:
        x, y, w, h = n['screenRect']
        out['/'.join(n['path'].split('/')[1:])] = (x - rx, origin_y - (y + h), w, h)
    return out


def compare_geometry(objs, csd_path, root_offset=(0.0, 0.0), rects=None):
    """Max deviation of every non-label node from the .csd, in pixels.

    root_offset is the deliberate re-anchoring of a view root onto its centre; pass the
    value the conversion used so a correct re-anchor is not reported as drift.
    `rects` accepts an already-fetched csdview_rects result; each csdview call costs
    roughly half a second, so the caller fetches them all at once.
    """
    theirs = rects if rects is not None else csdview_rects(csd_path)
    if theirs is None:
        return None
    raw, shifts = prefab_rects(objs)
    worst_geo, worst_label, compared = (0.0, '-'), (0.0, '-'), 0
    for key, value in raw.items():
        name = key.replace('/view/content/', '/')
        if name not in theirs:
            continue
        shift = sum(off for sv, off in shifts.items()
                    if key.startswith(sv + '/view/content/'))
        mine = (value[0] + root_offset[0], value[1] + shift + root_offset[1],
                value[2], value[3])
        ref = theirs[name]
        err = max(abs(mine[0] - ref[0]), abs(mine[1] - ref[1]),
                  abs(mine[2] - ref[2]), abs(mine[3] - ref[3]))
        compared += 1
        if value[4]:
            worst_label = max(worst_label, (err, name))
        else:
            worst_geo = max(worst_geo, (err, name))
    return {'compared': compared, 'worst_geometry': worst_geo, 'worst_label': worst_label,
            'ok': worst_geo[0] < TOLERANCE_PX}


# ---------------------------------------------------------------- sliced insets
def check_sliced_insets(objs, frame_index):
    """A SLICED sprite whose insets exceed its node renders with squashed caps and no
    middle column. This is the check that would have caught the InfoPage_V frames."""
    problems = []
    for o in objs:
        if not (isinstance(o, dict) and o.get('__type__') == 'cc.Sprite'
                and o.get('_type') == 1 and isinstance(o.get('_spriteFrame'), dict)):
            continue
        node = objs[o['node']['__id__']]
        transform = next((objs[c['__id__']] for c in node['_components']
                          if objs[c['__id__']]['__type__'] == 'cc.UITransform'), None)
        if transform is None:
            continue
        w = transform['_contentSize']['width']
        h = transform['_contentSize']['height']
        hit = frame_index.get(o['_spriteFrame']['__uuid__'])
        if not hit:
            problems.append((node['_name'], 'spriteFrame not found'))
            continue
        ud = hit[1]
        left, right = ud.get('borderLeft', 0), ud.get('borderRight', 0)
        top, bottom = ud.get('borderTop', 0), ud.get('borderBottom', 0)
        if left + right > w:
            problems.append((node['_name'], 'L+R %d > width %g' % (left + right, w)))
        if top + bottom > h:
            problems.append((node['_name'], 'T+B %d > height %g' % (top + bottom, h)))
    return problems


def check_trim_mode(objs, frame_index):
    """_isTrimmedMode on a sprite whose frame really is trimmed moves and rescales the art.

    Creator stretches the trimmed region over the whole node in that mode, discarding the
    frame's trim offset. Harmless on tightly-cropped art (rect == originalSize), wrong for
    anything with transparent margins - and very visible on an animated sprite-frame
    sequence whose bounding box changes per frame.
    """
    problems = []
    for o in objs:
        if not (isinstance(o, dict) and o.get('__type__') == 'cc.Sprite'
                and o.get('_isTrimmedMode') and isinstance(o.get('_spriteFrame'), dict)):
            continue
        hit = frame_index.get(o['_spriteFrame']['__uuid__'])
        if not hit:
            continue
        ud = hit[1]
        if ud.get('width') != ud.get('rawWidth') or ud.get('height') != ud.get('rawHeight'):
            node = objs[o['node']['__id__']]
            problems.append((node['_name'],
                             'trimmed frame %dx%d of %dx%d drawn with _isTrimmedMode'
                             % (ud['width'], ud['height'], ud['rawWidth'], ud['rawHeight'])))
    return problems


class FontIndex(dict):
    """bitmap-font uuid -> its .meta userData, read from disk so a re-import that mangles
    the config is visible to this check.

    Scanning the whole project for .fnt.meta costs a tree walk, so start with the folders
    this conversion touches and widen only when a font is not found there.
    """

    def __init__(self, assets_root, search_dirs=None):
        dict.__init__(self)
        self._assets_root = assets_root
        self._widened = False
        self._absorb(self._metas(search_dirs or []))

    @staticmethod
    def _metas(dirs):
        out = []
        for rel in dirs:
            out += glob.glob(os.path.join(rel, '**', '*.fnt.meta'), recursive=True)
        return out

    def _absorb(self, metas):
        for meta in metas:
            try:
                data = load(meta)
            except ValueError:
                continue
            self[data['uuid']] = data.get('userData') or {}

    def _widen(self):
        self._widened = True
        self._absorb(glob.glob(os.path.join(self._assets_root, '**', '*.fnt.meta'),
                               recursive=True))

    def get(self, key, default=None):
        if key not in self and not self._widened:
            self._widen()
        return dict.get(self, key, default)


def build_font_index(assets_root, search_dirs=None):
    return FontIndex(assets_root, search_dirs)


def check_labels(objs, font_index):
    """A cc.Label draws nothing at font size 0, and a bitmap-font Label needs a glyph for
    every character it shows.

    The glyph check reads the .fnt .meta as it currently is on disk. Cocos Creator
    re-parses the .fnt on import and overwrites _fntConfig, and its parser cannot read
    Cocos Studio's `char id= 48` spacing - every glyph then lands under the key
    'undefined' and the console reports "Can't find letter definition in texture atlas".
    """
    problems = []
    for o in objs:
        if not (isinstance(o, dict) and o.get('__type__') == 'cc.Label'):
            continue
        name = objs[o['node']['__id__']]['_name']
        if not o.get('_fontSize'):
            problems.append((name, 'font size is %r - the label will not render'
                             % o.get('_fontSize')))
        font = o.get('_font')
        if not isinstance(font, dict):
            continue
        user_data = font_index.get(font.get('__uuid__'))
        if user_data is None:
            problems.append((name, 'bitmap font %s has no .meta' % font.get('__uuid__')))
            continue
        problems.extend(_glyph_problems(name, o.get('_string') or '', user_data))
    return problems


def _glyph_problems(name, text, user_data):
    glyphs = (user_data.get('_fntConfig') or {}).get('fontDefDictionary') or {}
    bad_keys = [k for k in glyphs if not k.lstrip('-').isdigit()]
    if bad_keys:
        return [(name, 'bitmap font has non-numeric glyph keys %s - the .fnt could not be '
                       'parsed' % sorted(bad_keys)[:3])]
    missing = sorted({c for c in text if str(ord(c)) not in glyphs})
    if missing:
        return [(name, 'bitmap font has no glyph for %s' % ''.join(missing))]
    return []


def check_animated_frames(objs, clip_objs, frame_index):
    """Every frame in a spriteFrame track should share one original size, otherwise the
    sequence changes size mid-animation."""
    problems = []
    if clip_objs is None:
        return problems
    for ref in clip_objs[0]['_tracks']:
        track = clip_objs[ref['__id__']]
        if track['__type__'] != 'cc.animation.ObjectTrack':
            continue
        path = clip_objs[track['_binding']['path']['__id__']]['_paths']
        if path[-1] != 'spriteFrame':
            continue
        curve = clip_objs[clip_objs[track['_channel']['__id__']]['_curve']['__id__']]
        sizes = set()
        for value in curve['_values']:
            if not isinstance(value, dict):
                continue
            hit = frame_index.get(value.get('__uuid__'))
            if hit:
                sizes.add((hit[1].get('rawWidth'), hit[1].get('rawHeight')))
        if len(sizes) > 1:
            node = clip_objs[path[0]['__id__']]['path']
            problems.append((node, 'spriteFrame track mixes original sizes %s'
                             % sorted(sizes)))
    return problems


# --------------------------------------------------------------------- contents
def compare_labels(objs, csd_path):
    """Label strings must match the .csd exactly. Order differs (the emitter writes
    children before components) so compare as multisets."""
    want = collections.Counter()
    for el in ET.parse(csd_path).getroot().iter('AbstractNodeData'):
        if el.get('ctype') in ('TextObjectData', 'TextBMFontObjectData'):
            want[(el.get('Name'), el.get('LabelText') or '')] += 1
    got = collections.Counter(
        (objs[o['node']['__id__']]['_name'], o['_string'])
        for o in objs if isinstance(o, dict) and o.get('__type__') == 'cc.Label')
    return sum(got.values()), want == got


def check_integrity(objs):
    """Every __id__ in range, no unfilled slots."""
    refs = []

    def scan(x):
        if isinstance(x, dict):
            if '__id__' in x:
                refs.append(x['__id__'])
            for v in x.values():
                scan(v)
        elif isinstance(x, list):
            for v in x:
                scan(v)

    scan(objs)
    holes = sum(1 for o in objs if o is None)
    # a null __id__ is a real failure mode (an unresolved reference written out), so it
    # has to be reported rather than crash the comparison
    out_of_range = [r for r in refs
                    if not isinstance(r, int) or not (0 <= r < len(objs))]
    return holes, out_of_range


def referenced_uuids(paths):
    """Every __uuid__ the generated files point at, with the file that mentions it."""
    out = []
    for path in paths:
        for o in load(path):
            if not isinstance(o, dict):
                continue
            for value in o.values():
                if isinstance(value, dict) and '__uuid__' in value:
                    out.append((os.path.basename(path), value['__uuid__']))
    return out


def _uuids_in(meta_paths):
    known = set()
    for meta in meta_paths:
        try:
            data = load(meta)
        except ValueError:
            continue
        known.add(data.get('uuid'))
        for sub in (data.get('subMetas') or {}).values():
            known.add(sub.get('uuid'))
    return known


def check_references(paths, assets_root, search_dirs=None):
    """Every __uuid__ referenced by the generated files must exist in some .meta.

    A full scan of the project parses thousands of .meta files, so look in the folders
    this conversion actually writes to or reuses from first, and fall back to the whole
    tree only for uuids that are still unaccounted for.
    """
    wanted = referenced_uuids(paths)
    if not wanted:
        return []
    metas = []
    for rel in (search_dirs or []):
        metas += glob.glob(os.path.join(assets_root, '..', rel, '**', '*.meta'),
                           recursive=True)
    known = _uuids_in(metas)
    unresolved = [(name, u) for name, u in wanted if u not in known]
    if unresolved:
        known |= _uuids_in(glob.glob(os.path.join(assets_root, '**', '*.meta'),
                                     recursive=True))
        unresolved = [(name, u) for name, u in unresolved if u not in known]
    return unresolved
