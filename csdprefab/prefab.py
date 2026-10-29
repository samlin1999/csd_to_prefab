# -*- coding: utf-8 -*-
"""Builds the .prefab object graph from a parsed .csd tree."""
import json

from . import components as C
from .csd import fnum
from .ids import asset_uuid, file_id


class Prefab(object):
    """Flat list of serialised objects; index 0 is cc.Prefab, index 1 the root node."""

    def __init__(self, name, db):
        self.name = name
        self.db = db
        self.uuid = asset_uuid(db)
        self.root_file_id = file_id(db + '#__root__')
        self.objs = []
        self.nested_roots = []

    def alloc(self):
        self.objs.append(None)
        return len(self.objs) - 1

    def put(self, index, obj):
        self.objs[index] = obj
        return index

    def add(self, obj):
        self.objs.append(obj)
        return len(self.objs) - 1

    def comp(self, node_id, seed, body):
        cid = self.alloc()
        pid = self.add({"__type__": "cc.CompPrefabInfo", "fileId": file_id(seed)})
        base = {"__type__": body.pop('__type__'), "_name": "", "_objFlags": 0,
                "__editorExtras__": {}, "node": {"__id__": node_id}, "_enabled": True,
                "__prefab": {"__id__": pid}}
        base.update(body)
        base["_id"] = ""
        self.put(cid, base)
        return {"__id__": cid}

    def info(self, seed, is_root=False):
        return {"__id__": self.add({
            "__type__": "cc.PrefabInfo", "root": {"__id__": 1}, "asset": {"__id__": 0},
            "fileId": self.root_file_id if is_root else file_id(seed),
            "instance": None, "targetOverrides": None,
            "nestedPrefabInstanceRoots": ([{"__id__": i} for i in self.nested_roots] or None)
            if is_root else None})}

    def dump(self):
        return json.dumps(self.objs, ensure_ascii=False, indent=2)


class Context(object):
    def __init__(self, prefab, images, fonts, child_prefabs, white_frame):
        self.pf = prefab
        self.images = images                 # csd resource path -> spriteFrame uuid
        self.fonts = fonts                   # csd .fnt path -> font uuid
        self.child_prefabs = child_prefabs   # csd path -> (prefab uuid, root fileId)
        self.white = white_frame             # solid frame used for Panel background colour
        self.by_tag = {}                     # ActionTag -> hierarchy path, for animation
        self.notes = []


def local_pos(node, parent_anchor, parent_size):
    return (node.pos[0] - parent_anchor[0] * parent_size[0],
            node.pos[1] - parent_anchor[1] * parent_size[1])


def emit(ctx, n, parent_id, p_anchor, p_size, path):
    """Emit one .csd node and its subtree; returns the new node's object index."""
    if n.ctype == 'ProjectNodeObjectData':
        return _emit_nested(ctx, n, parent_id, p_anchor, p_size, path)

    pf = ctx.pf
    nid = pf.alloc()
    obj = C.node(n.name, parent_id, local_pos(n, p_anchor, p_size), n.scale,
                 -n.rot[0], active=n.visible)
    pf.put(nid, obj)
    if n.action_tag:
        ctx.by_tag[n.action_tag] = path
    seed = pf.db + '#' + path

    if n.ctype == 'ScrollViewObjectData':
        return _emit_scroll_view(ctx, n, nid, obj, path, seed)

    for child in n.children:
        # emit() returns None for a ProjectNode whose target prefab is not configured;
        # appending that would write {"__id__": null} and corrupt the file.
        cid = emit(ctx, child, nid, n.anchor, n.size, path + '/' + child.name)
        if cid is not None:
            obj["_children"].append({"__id__": cid})
    obj["_components"] = _components_for(ctx, n, nid, seed, path)
    obj["_prefab"] = pf.info(seed)
    return nid


# Cocos Studio types that legitimately become a plain container node.
CONTAINER_TYPES = ('GameNodeObjectData', 'GameLayerObjectData', 'SingleNodeObjectData')

def _components_for(ctx, n, nid, seed, path):
    pf = ctx.pf
    comps = [pf.comp(nid, seed + '#ut', C.ui_transform(n.size, n.anchor))]
    handler = {
        'ImageViewObjectData': _image_comps,
        'SpriteObjectData': _image_comps,
        'ButtonObjectData': _button_comps,
        'TextObjectData': _text_comps,
        'TextBMFontObjectData': _bmfont_comps,
        'PanelObjectData': _panel_comps,
    }.get(n.ctype)
    if handler:
        comps.extend(handler(ctx, n, nid, seed, path))
    elif n.ctype not in CONTAINER_TYPES:
        # Particle / CheckBox / ListView / LoadingBar / PageView / TextField / Slider have
        # no conversion yet; they keep their transform but draw nothing. Say so rather than
        # letting the node quietly go missing from the view.
        ctx.notes.append('%s: %s is not converted - emitted as an empty node'
                         % (path, n.ctype))
    if n.alpha != 255 and n.ctype != 'PanelObjectData':
        comps.append(pf.comp(nid, seed + '#opacity', C.opacity(n.alpha)))
    return comps


def _sprite_from(ctx, n, nid, seed, path, tag):
    src = n.res.get(tag)
    frame = ctx.images.get(src) if src else None
    if src and frame is None:
        ctx.notes.append('%s: no art for %s' % (path, src))
    return ctx.pf.comp(nid, seed + '#sprite', C.sprite(frame, n.color, n.blend, n.scale9))


def _image_comps(ctx, n, nid, seed, path):
    return [_sprite_from(ctx, n, nid, seed, path, 'FileData')]


def _button_comps(ctx, n, nid, seed, path):
    return [_sprite_from(ctx, n, nid, seed, path, 'NormalFileData'),
            ctx.pf.comp(nid, seed + '#button', C.button())]


def _text_comps(ctx, n, nid, seed, path):
    wrap = n.raw.get('IsCustomSize') == 'True'
    return [ctx.pf.comp(nid, seed + '#label',
                        C.label(n.text or '', n.font_size, n.color, wrap=wrap))]


def _bmfont_comps(ctx, n, nid, seed, path):
    """A bitmap-font Label still needs a font size: cc.Label draws nothing at size 0.
    The project's convention is the .fnt's own native size, with any further scaling left
    to the node's scale (which is what Cocos Studio does too)."""
    fnt = n.res.get('LabelBMFontFile_CNB')
    entry = ctx.fonts.get(fnt)
    if fnt and entry is None:
        ctx.notes.append('%s: no bitmap font for %s' % (path, fnt))
    uuid_, size = entry if entry else (None, 0)
    return [ctx.pf.comp(nid, seed + '#label',
                        C.label(n.text or '', size, n.color, font_uuid=uuid_))]


def _panel_comps(ctx, n, nid, seed, path):
    """Panel background: ComboBoxIndex 1 is a solid SingleColor at BackColorAlpha."""
    pf, out = ctx.pf, []
    alpha = int(fnum(n.raw, 'BackColorAlpha', 255))
    if n.raw.get('ComboBoxIndex') == '1' and alpha > 0:
        sc = n.raw.find('SingleColor')
        rgb = ((int(fnum(sc, 'R', 255)), int(fnum(sc, 'G', 255)), int(fnum(sc, 'B', 255)))
               if sc is not None else (255, 255, 255))
        out.append(pf.comp(nid, seed + '#bg', C.sprite(ctx.white, rgb, None, False)))
        if alpha != 255:
            out.append(pf.comp(nid, seed + '#bgop', C.opacity(alpha)))
    if n.clip:
        out.append(pf.comp(nid, seed + '#mask', C.mask()))
    if n.percent_size[0] and n.percent_size[1]:
        out.append(pf.comp(nid, seed + '#widget', C.widget(n.size[0], n.size[1])))
    return out


def _emit_scroll_view(ctx, n, nid, obj, path, seed):
    """Cocos Studio keeps one inner container; Creator needs ScrollView -> masked view ->
    content. The inner container is top-aligned with the window, matching the engine's
    initial scroll position (csdview draws it at the origin instead, so a vertical
    difference of innerHeight - viewHeight against csdview is expected)."""
    pf = ctx.pf
    inner = n.raw.find('InnerNodeSize')
    iw = float(inner.get('Width')) if inner is not None else n.size[0]
    ih = float(inner.get('Height')) if inner is not None else n.size[1]

    view_id = pf.alloc()
    view = C.node('view', nid, (-n.anchor[0] * n.size[0], -n.anchor[1] * n.size[1]),
                  (1, 1), 0)
    pf.put(view_id, view)
    content_id = pf.alloc()
    content = C.node('content', view_id, (0, n.size[1] - ih), (1, 1), 0)
    pf.put(content_id, content)

    for child in n.children:
        cid = emit(ctx, child, content_id, (0.0, 0.0), (0.0, 0.0),
                   path + '/view/content/' + child.name)
        if cid is not None:
            content["_children"].append({"__id__": cid})
    content["_components"] = [pf.comp(content_id, seed + '/content#ut',
                                      C.ui_transform((iw, ih), (0, 0)))]
    content["_prefab"] = pf.info(seed + '/content')

    view["_children"] = [{"__id__": content_id}]
    view["_components"] = [pf.comp(view_id, seed + '/view#ut', C.ui_transform(n.size, (0, 0))),
                           pf.comp(view_id, seed + '/view#mask', C.mask())]
    view["_prefab"] = pf.info(seed + '/view')
    obj["_children"].append({"__id__": view_id})

    direction = n.raw.get('ScrollDirectionType') or 'Vertical'
    obj["_components"] = [
        pf.comp(nid, seed + '#ut', C.ui_transform(n.size, n.anchor)),
        pf.comp(nid, seed + '#scroll', C.scroll_view(
            content_id, direction, n.raw.get('IsBounceEnabled') == 'True')),
    ]
    obj["_prefab"] = pf.info(seed)
    return nid


def _emit_nested(ctx, n, parent_id, p_anchor, p_size, path):
    """A .csd ProjectNode becomes a nested prefab instance whose transform and name are
    property overrides on the referenced prefab's root."""
    ref = n.res.get('FileData')
    target = ctx.child_prefabs.get(ref)
    if target is None:
        ctx.notes.append('%s: unresolved ProjectNode %s' % (path, ref))
        return None
    child_uuid, child_root_fid = target
    pf = ctx.pf
    nid, pi, inst = pf.alloc(), pf.alloc(), pf.alloc()
    tinfo = pf.add({"__type__": "cc.TargetInfo", "localID": [child_root_fid]})

    overrides = []

    def override(prop, value):
        overrides.append({"__id__": pf.add({
            "__type__": "CCPropertyOverrideInfo", "targetInfo": {"__id__": tinfo},
            "propertyPath": [prop], "value": value})})

    lpos = local_pos(n, p_anchor, p_size)
    override('_name', n.name)
    override('_lpos', C.vec3(lpos[0], lpos[1]))
    override('_lrot', C.quat_z(-n.rot[0]))
    override('_euler', C.vec3(0, 0, -n.rot[0]))
    if n.scale != (1.0, 1.0):
        override('_lscale', C.vec3(n.scale[0], n.scale[1], 1))
    if not n.visible:
        override('_active', False)

    pf.put(nid, {"__type__": "cc.Node", "_objFlags": 0, "_parent": {"__id__": parent_id},
                 "_prefab": {"__id__": pi}, "__editorExtras__": {}})
    pf.put(pi, {"__type__": "cc.PrefabInfo", "root": {"__id__": nid},
                "asset": {"__uuid__": child_uuid, "__expectedType__": "cc.Prefab"},
                "fileId": child_root_fid, "instance": {"__id__": inst},
                "targetOverrides": None})
    pf.put(inst, {"__type__": "cc.PrefabInstance", "fileId": file_id(pf.db + '#' + path),
                  "prefabRootNode": {"__id__": 1}, "mountedChildren": [],
                  "mountedComponents": [], "propertyOverrides": overrides,
                  "removedComponents": []})
    pf.nested_roots.append(nid)
    if n.action_tag:
        ctx.by_tag[n.action_tag] = path
    return nid
