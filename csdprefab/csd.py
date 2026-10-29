# -*- coding: utf-8 -*-
"""Parsing of Cocos Studio .csd files.

The .csd files are UTF-8 with no XML declaration, so ElementTree reads them correctly;
printing their text to a cp950 console is what mangles Chinese, not the parse.
"""
import os
import xml.etree.ElementTree as ET

# Element order inside AbstractNodeData is Size, Children, AnchorPoint, Position, Scale,
# CColor, PrePosition, PreSize, FileData - so anchors live *after* the children block.
RESOURCE_TAGS = ('FileData', 'NormalFileData', 'PressedFileData', 'DisabledFileData',
                 'LabelBMFontFile_CNB', 'FontResource')


def fnum(el, attr, default=0.0):
    if el is None:
        return default
    v = el.get(attr)
    return float(v) if v is not None else default


class Node(object):
    """One AbstractNodeData / ObjectData, with the fields the emitter needs."""

    __slots__ = ('name', 'ctype', 'size', 'pos', 'anchor', 'scale', 'rot', 'color', 'alpha',
                 'visible', 'children', 'res', 'text', 'font_size', 'action_tag', 'raw',
                 'scale9', 'edges', 'blend', 'clip', 'percent_size', 'path')

    def __init__(self):
        self.children = []
        self.res = {}


def _read_transform(el, n):
    sz = el.find('Size')
    n.size = (fnum(sz, 'X'), fnum(sz, 'Y'))
    ap = el.find('AnchorPoint')
    # An absent AnchorPoint element means (0, 0); Cocos Studio omits zero attributes.
    n.anchor = (fnum(ap, 'ScaleX'), fnum(ap, 'ScaleY'))
    po = el.find('Position')
    n.pos = (fnum(po, 'X'), fnum(po, 'Y'))
    sc = el.find('Scale')
    n.scale = (fnum(sc, 'ScaleX', 1.0), fnum(sc, 'ScaleY', 1.0)) if sc is not None else (1.0, 1.0)
    n.rot = (fnum(el, 'RotationSkewX'), fnum(el, 'RotationSkewY'))


def _read_appearance(el, n):
    cc = el.find('CColor')
    n.color = (int(fnum(cc, 'R', 255)), int(fnum(cc, 'G', 255)), int(fnum(cc, 'B', 255)))
    n.alpha = int(fnum(el, 'Alpha', 255))
    n.visible = el.get('VisibleForFrame') != 'False'
    bf = el.find('BlendFunc')
    n.blend = (int(fnum(bf, 'Src', 770)), int(fnum(bf, 'Dst', 771))) if bf is not None else None


def _read_widget(el, n):
    n.font_size = int(fnum(el, 'FontSize', 20))
    n.text = el.get('LabelText')
    n.scale9 = el.get('Scale9Enable') == 'True'
    # Cocos Studio order is Left, Bottom, Right, Top
    n.edges = (int(fnum(el, 'LeftEage')), int(fnum(el, 'BottomEage')),
               int(fnum(el, 'RightEage')), int(fnum(el, 'TopEage')))
    n.clip = el.get('ClipAble') == 'True'
    n.percent_size = (el.get('PercentWidthEnable') == 'True',
                      el.get('PercentHeightEnable') == 'True')


def read_node(el):
    n = Node()
    n.name = el.get('Name') or 'Node'
    n.ctype = el.get('ctype')
    n.action_tag = el.get('ActionTag')
    n.raw = el
    _read_transform(el, n)
    _read_appearance(el, n)
    _read_widget(el, n)
    for tag in RESOURCE_TAGS:
        fd = el.find(tag)
        if fd is not None and fd.get('Path'):
            n.res[tag] = fd.get('Path').replace('\\', '/')
    return n


def parse(path):
    """Return (root Node, <Animation> element or None, canvas size)."""
    doc = ET.parse(path).getroot()
    obj = doc.find('./Content/Content/ObjectData')
    if obj is None:
        raise ValueError('no ObjectData in %s' % path)

    def walk(el, parent_path):
        n = read_node(el)
        n.path = n.name if not parent_path else parent_path + '/' + n.name
        kids = el.find('Children')
        if kids is not None:
            for k in kids.findall('AbstractNodeData'):
                n.children.append(walk(k, n.path))
        return n

    root = walk(obj, '')
    anim = doc.find('./Content/Content/Animation')
    prop = doc.find('./PropertyGroup')
    canvas = (0.0, 0.0)
    if root.size != (0.0, 0.0):
        canvas = root.size
    return root, anim, canvas


def iter_nodes(node):
    yield node
    for c in node.children:
        for x in iter_nodes(c):
            yield x


def scan_resources(csd_paths):
    """Collect referenced images, their Scale9 edges, the node sizes they are drawn at,
    and the bitmap fonts, across a batch of .csd files."""
    images, edges, sizes, fonts = set(), {}, {}, set()
    for p in csd_paths:
        doc = ET.parse(p).getroot()
        for el in doc.iter('AbstractNodeData'):
            n = read_node(el)
            for tag in ('FileData', 'NormalFileData', 'PressedFileData', 'DisabledFileData'):
                res = n.res.get(tag)
                if not res or not res.lower().endswith('.png'):
                    continue
                images.add(res)
                if n.scale9:
                    edges[res] = n.edges
                    sizes.setdefault(res, []).append(n.size)
            fnt = n.res.get('LabelBMFontFile_CNB')
            if fnt:
                fonts.add(fnt)
        for tf in doc.iter('TextureFile'):          # sprite swaps inside timelines
            res = (tf.get('Path') or '').replace('\\', '/')
            if res.lower().endswith('.png'):
                images.add(res)
    return images, edges, sizes, fonts


def find_csd_files(folder):
    """Every .csd under the folder, recursively - modules such as exchange/ keep theirs in
    a Csd/ sub-folder. Returned as paths relative to `folder`, using forward slashes so
    they can be joined onto the .csd resource paths directly."""
    out = []
    for dirpath, _, names in os.walk(folder):
        for name in names:
            if name.lower().endswith('.csd'):
                rel = os.path.relpath(os.path.join(dirpath, name), folder)
                out.append(rel.replace(os.sep, '/'))
    return sorted(out)
