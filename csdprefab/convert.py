# -*- coding: utf-8 -*-
"""The conversion pipeline: assets first, then prefabs in config order."""
import glob
import io
import json
import os
import tempfile
import time

from . import anim, csd, fonts, images
from . import components as C
from .ids import asset_uuid, db_path
from .prefab import Context, Prefab, emit


REPLACE_ATTEMPTS = 5
REPLACE_PAUSE = 0.04

# Files that had to be written in place because the rename kept being refused. Writes are
# sequential, so a plain counter is enough; run() reports it so the degradation is visible.
in_place_writes = []


def _write_tmp(folder, text):
    handle, tmp = tempfile.mkstemp(dir=folder, prefix='.csd2prefab-', suffix='.tmp')
    os.close(handle)
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    return tmp


def write_text(path, text):
    """Write via a sibling temp file and rename, so the file never exists half-written.

    Cocos Creator watches these folders and re-imports on change. Truncating in place lets
    it read a partial .prefab or .meta - measured at roughly one read in five under load.

    Windows refuses to rename over a file another process has open, and Creator opens
    these constantly. The lock is normally momentary, so retry briefly; if it will not
    clear, write in place rather than abandoning the conversion. That is what the tool did
    before, so the fallback is never worse than not trying - it is just recorded.
    """
    folder = os.path.dirname(path) or '.'
    tmp = _write_tmp(folder, text)
    try:
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt < REPLACE_ATTEMPTS - 1:
                    time.sleep(REPLACE_PAUSE)
        with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        in_place_writes.append(path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def ensure_dir(project_root, abs_dir):
    """Create the folder and every missing parent under assets/, each with its .meta."""
    assets = os.path.join(project_root, 'assets')
    current = assets
    for part in os.path.relpath(abs_dir, assets).split(os.sep):
        current = os.path.join(current, part)
        if not os.path.isdir(current):
            os.makedirs(current)
        if not os.path.exists(current + '.meta'):
            write_json(current + '.meta', images.directory_meta(current))


# ------------------------------------------------------------------ asset stage
class AssetResult(object):
    def __init__(self):
        self.images = {}        # csd resource path -> spriteFrame uuid (None when absent)
        self.fonts = {}         # csd .fnt path -> (font uuid, native font size)
        self.copied = []
        self.reused = []
        self.missing = []


def convert_assets(cfg, project_root, log, write=True):
    """write=False resolves the uuid maps without touching disk, so a drift check can
    rebuild a prefab in memory. uuids are derived from the destination path, so they are
    the same either way."""
    csd_paths = [os.path.join(cfg.csd_dir, e['csd']) for e in cfg.entries()]
    wanted, edges, sizes, font_paths = csd.scan_resources(csd_paths)
    if cfg.copyAllModuleImages:
        for png in sorted(glob.glob(os.path.join(cfg.csd_dir, 'img', '*.png'))):
            wanted.add('%s/img/%s' % (cfg.csdDir, os.path.basename(png)))

    img_dir = os.path.join(project_root, cfg.imagesOut.replace('/', os.sep))
    if write:
        ensure_dir(project_root, img_dir)
    result = AssetResult()
    for res in sorted(wanted):
        _handle_image(cfg, project_root, img_dir, res, edges, sizes, result, write)

    if cfg.fontsOut and font_paths:
        fnt_dir = os.path.join(project_root, cfg.fontsOut.replace('/', os.sep))
        if write:
            ensure_dir(project_root, fnt_dir)
        _copy_fonts(cfg, fnt_dir, result, write)

    log('assets: %d copied, %d reused, %d unavailable'
        % (len(result.copied), len(result.reused), len(result.missing)))
    for res in result.missing:
        log('  unavailable: %s' % res)
    return result


def _handle_image(cfg, project_root, img_dir, res, edges, sizes, result, write=True):
    if res in cfg.placeholders:
        result.images[res] = None
        result.missing.append(res)
        return
    if res in cfg.reuse:
        meta = os.path.join(project_root, cfg.reuse[res].replace('/', os.sep)) + '.meta'
        if os.path.exists(meta):
            with io.open(meta, encoding='utf-8') as fh:
                result.images[res] = json.load(fh)['uuid'] + '@f9941'
            result.reused.append(res)
        else:
            result.images[res] = None
            result.missing.append(res)
        return
    src = os.path.join(cfg.csd_root, res.replace('/', os.sep))
    if not os.path.exists(src):
        result.images[res] = None
        result.missing.append(res)
        return
    dst = os.path.join(img_dir, os.path.basename(res))
    if not write:
        result.images[res] = asset_uuid(db_path(dst)) + '@f9941'
        return
    im = images.copy_image(src, dst)
    border = images.resolve_border(dst, edges.get(res, (0, 0, 0, 0)), sizes.get(res, []))
    meta = images.image_meta(dst, border=border, im=im)
    write_json(dst + '.meta', meta)
    result.images[res] = meta['uuid'] + '@f9941'
    result.copied.append(res)


def _copy_fonts(cfg, fnt_dir, result, write=True):
    """Copy each FNT_* folder's .fnt plus the atlas page it names."""
    for folder in sorted(glob.glob(os.path.join(cfg.csd_dir, 'FNT_*'))):
        found = glob.glob(os.path.join(folder, '*.fnt'))
        if not found:
            continue
        fnt_src = found[0]
        atlas_src = os.path.join(folder, fonts.parse_fnt(fnt_src)['atlasName'])
        if not os.path.exists(atlas_src):
            result.missing.append(os.path.basename(atlas_src))
            continue
        atlas_dst = os.path.join(fnt_dir, os.path.basename(atlas_src))
        fnt_dst = os.path.join(fnt_dir, os.path.basename(fnt_src))
        key = '%s/%s/%s' % (cfg.csdDir, os.path.basename(folder), os.path.basename(fnt_src))
        if not write:
            result.fonts[key] = (asset_uuid(db_path(fnt_dst)),
                                 fonts.parse_fnt(fnt_src)['fontSize'])
            continue
        atlas = images.copy_image(atlas_src, atlas_dst)
        atlas_meta = images.image_meta(atlas_dst, trim=False, im=atlas)
        write_json(atlas_dst + '.meta', atlas_meta)
        with io.open(fnt_src, encoding='utf-8', errors='replace', newline='') as fh:
            write_text(fnt_dst, fonts.normalise(fh.read()))
        meta = fonts.fnt_meta(fnt_dst, atlas_meta['uuid'])
        write_json(fnt_dst + '.meta', meta)
        result.fonts[key] = (asset_uuid(db_path(fnt_dst)), meta['userData']['fontSize'])
        result.copied.append(key)


# ----------------------------------------------------------------- prefab stage
def _root_setup(entry, canvas):
    """A 'view' root is re-anchored onto its centre so it matches this project's existing
    view prefabs (MainView / AntitheftView are 0.5/0.5 with a stretch Widget). That makes
    every child sit at csdPos - anchor*canvas, which is a deliberate, uniform offset from
    the .csd's bottom-left origin."""
    if entry['root'] == 'view' and canvas != (0.0, 0.0):
        return canvas, (0.5, 0.5), True
    return (0.0, 0.0), (0.5, 0.5), False


def convert_prefab(cfg, project_root, entry, assets, child_prefabs, log, write=True):
    csd_path = os.path.join(cfg.csd_dir, entry['csd'])
    root, anim_el, canvas = csd.parse(csd_path)
    out_abs = os.path.join(project_root, entry['out'].replace('/', os.sep))
    if write:
        ensure_dir(project_root, os.path.dirname(out_abs))

    pf = Prefab(entry['name'], db_path(out_abs))
    pf.add({"__type__": "cc.Prefab", "_name": entry['name'], "_objFlags": 0,
            "__editorExtras__": {}, "_native": "", "data": {"__id__": 1},
            "optimizationPolicy": 0, "persistent": False})
    root_id = pf.alloc()
    root_obj = C.node(entry['name'], None, (0, 0), (1, 1), 0)
    pf.put(root_id, root_obj)

    r_size, r_anchor, with_widget = _root_setup(entry, canvas)
    ctx = Context(pf, assets.images, assets.fonts, child_prefabs, cfg.white_frame)
    for child in root.children:
        cid = emit(ctx, child, root_id, r_anchor, r_size, child.name)
        if cid is not None:
            root_obj["_children"].append({"__id__": cid})

    seed = pf.db + '#__root__'
    comps = [pf.comp(root_id, seed + '#ut', C.ui_transform(r_size, r_anchor))]
    if with_widget:
        comps.append(pf.comp(root_id, seed + '#widget', C.widget(r_size[0], r_size[1])))
    clip_uuid = _write_animation(cfg, out_abs, entry, anim_el, ctx, assets, write)
    if clip_uuid:
        comps.append(pf.comp(root_id, seed + '#anim', C.animation(clip_uuid)))
    root_obj["_components"] = comps
    root_obj["_prefab"] = pf.info(seed, is_root=True)

    if write:
        write_text(out_abs, pf.dump())
        write_json(out_abs + '.meta',
                   {"ver": "1.1.50", "importer": "prefab", "imported": True,
                    "uuid": pf.uuid, "files": [".json"], "subMetas": {},
                    "userData": {"syncNodeName": entry['name']}})
        for note in ctx.notes:
            log('  note: %s' % note)
    return pf, (-r_anchor[0] * r_size[0], -r_anchor[1] * r_size[1])


def _write_animation(cfg, out_abs, entry, anim_el, ctx, assets, write=True):
    if anim_el is None or float(anim_el.get('Duration') or 0) <= 0:
        return None
    clip_name = entry['name'] + '_animation0'
    clip_path = out_abs.replace('.prefab', '_animation0.anim')
    clip_uuid = asset_uuid(db_path(clip_path))
    if not write:
        return clip_uuid
    clip, duration = anim.build(anim_el, ctx.by_tag, clip_name, assets.images, ctx.notes)
    write_text(clip_path, clip.dump(duration))
    write_json(clip_path + '.meta',
               {"ver": "2.0.4", "importer": "animation-clip", "imported": True,
                "uuid": clip_uuid, "files": [".bin"], "subMetas": {},
                "userData": {"name": clip_name}})
    return clip_uuid


def run(cfg, project_root, log):
    """Full conversion. Returns {csd name: (prefab, root offset)} for verification."""
    del in_place_writes[:]
    assets = convert_assets(cfg, project_root, log)
    child_prefabs = {}
    for csd_path, prefab_rel in cfg.external_prefabs.items():
        child_prefabs[csd_path] = _existing_prefab_ref(project_root, prefab_rel)
    built = {}
    for entry in cfg.entries():
        pf, offset = convert_prefab(cfg, project_root, entry, assets, child_prefabs, log)
        key = '%s/%s' % (cfg.csdDir, entry['csd'])
        child_prefabs[key] = (pf.uuid, pf.root_file_id)
        built[entry['csd']] = (entry, pf, offset)
        log('built %s' % entry['out'])
    if in_place_writes:
        log('note: %d file(s) could not be replaced atomically and were written in place '
            '- Cocos Creator was holding them open, so it may have read a partial file. '
            'Close the prefab in Creator and re-run if anything looks wrong.'
            % len(in_place_writes))
    return assets, built


def _existing_prefab_ref(project_root, rel):
    """(uuid, root fileId) of a prefab that is already in the project."""
    abs_path = os.path.join(project_root, rel.replace('/', os.sep))
    with io.open(abs_path + '.meta', encoding='utf-8') as fh:
        uuid_ = json.load(fh)['uuid']
    with io.open(abs_path, encoding='utf-8') as fh:
        objs = json.load(fh)
    return uuid_, objs[objs[1]['_prefab']['__id__']]['fileId']


# ------------------------------------------------------------------------ drift
def drift(cfg, project_root, log):
    """Rebuild every prefab in memory and report where the file on disk disagrees.

    Generated prefabs are deterministic, so any difference means the file was edited
    outside this tool. The common source is saving a view prefab from the Cocos Creator
    prefab editor: the stretch cc.Widget on the view root resizes the root to whatever
    the editor canvas is, and the save bakes that in - which silently turns a 640x1400
    portrait view into 1400x640. Labels also get their contentSize recomputed to the
    measured glyph box, which is normal and is restored on the next convert.
    """
    assets = convert_assets(cfg, project_root, lambda _: None, write=False)
    child_prefabs = {}
    for csd_path, prefab_rel in cfg.external_prefabs.items():
        child_prefabs[csd_path] = _existing_prefab_ref(project_root, prefab_rel)
    drifted = []
    for entry in cfg.entries():
        pf, _ = convert_prefab(cfg, project_root, entry, assets, child_prefabs,
                               lambda _: None, write=False)
        child_prefabs['%s/%s' % (cfg.csdDir, entry['csd'])] = (pf.uuid, pf.root_file_id)
        out_abs = os.path.join(project_root, entry['out'].replace('/', os.sep))
        if not os.path.exists(out_abs):
            drifted.append((entry, ['file is missing']))
            continue
        with io.open(out_abs, encoding='utf-8') as fh:
            current = fh.read()
        expected = pf.dump()
        if current == expected:
            continue
        drifted.append((entry, _describe_drift(json.loads(current), json.loads(expected))))
    for entry, reasons in drifted:
        log('DRIFT %s' % entry['out'])
        for reason in reasons[:8]:
            log('        %s' % reason)
        if len(reasons) > 8:
            log('        ... and %d more' % (len(reasons) - 8))
    if not drifted:
        log('every generated prefab matches its .csd')
    return drifted


def _describe_drift(current, expected):
    """Node-level summary of how two serialised prefabs differ."""
    def index(objs):
        out = {}
        for i, o in enumerate(objs):
            if isinstance(o, dict) and o.get('__type__') == 'cc.Node' and o.get('_name'):
                transform = next((objs[c['__id__']] for c in o.get('_components', [])
                                  if objs[c['__id__']]['__type__'] == 'cc.UITransform'), None)
                size = ((transform['_contentSize']['width'],
                         transform['_contentSize']['height']) if transform else None)
                out.setdefault(o['_name'], []).append(
                    ((round(o['_lpos']['x'], 2), round(o['_lpos']['y'], 2)), size))
        return out

    a, b = index(current), index(expected)
    reasons = []
    for name in sorted(set(a) | set(b)):
        if a.get(name) != b.get(name):
            reasons.append('%s: on disk %s, from the .csd %s'
                           % (name, a.get(name), b.get(name)))
    return reasons or ['content differs but no node transform changed']
