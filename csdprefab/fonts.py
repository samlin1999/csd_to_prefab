# -*- coding: utf-8 -*-
"""Bitmap font (.fnt) parsing and .meta authoring."""
import re

from .ids import asset_uuid, db_path

# BMFont writes `char id= 48   x=0 ...` - the space after '=' is why the value pattern
# allows surrounding whitespace. Without it every glyph parses as id 0 and collapses.
_KV = re.compile(r'(\w+)\s*=\s*("[^"]*"|-?\d+)')


def normalise(text):
    """Tighten `key = value` to `key=value` throughout a BMFont file.

    Cocos Studio exports glyph lines as `char id= 48   x=0 ...`. Cocos Creator's own .fnt
    importer cannot read the space after '=': every glyph ends up keyed 'undefined', they
    overwrite each other, and the label renders nothing while the console reports
    "Can't find letter definition in texture atlas ... for letter:0".

    Authoring a correct _fntConfig in the .meta is not enough, because Creator re-parses
    the .fnt on import and overwrites it. The file itself has to be readable.
    """
    return _KV_SPACING.sub(r'\1=', text)


_KV_SPACING = re.compile(r'(\w+)\s*=\s*(?=("|-?\d))')


def parse_fnt(path):
    cfg = {"commonHeight": 0, "fontSize": 0, "atlasName": "",
           "fontDefDictionary": {}, "kerningDict": {}}
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            _parse_fnt_line(line.strip(), cfg)
    if not cfg["commonHeight"]:
        cfg["commonHeight"] = cfg["fontSize"]
    return cfg


def _parse_fnt_line(line, cfg):
    if not line:
        return
    kind, _, rest = line.partition(' ')
    kv = dict(_KV.findall(rest))

    def num(key, default=0):
        v = kv.get(key)
        return int(v) if v is not None and v.lstrip('-').isdigit() else default

    if kind == 'info':
        cfg["fontSize"] = abs(num('size'))
    elif kind == 'common':
        cfg["commonHeight"] = num('lineHeight')
    elif kind == 'page':
        cfg["atlasName"] = kv.get('file', '""').strip('"')
    elif kind == 'char':
        cfg["fontDefDictionary"][str(num('id'))] = {
            "rect": {"x": num('x'), "y": num('y'),
                     "width": num('width'), "height": num('height')},
            "xOffset": num('xoffset'), "yOffset": num('yoffset'),
            "xAdvance": num('xadvance')}
    elif kind == 'kerning':
        cfg["kerningDict"][str((num('first') << 16) | num('second'))] = num('amount')


def fnt_meta(fnt_abs, atlas_image_uuid):
    """textureUuid is the atlas png's top-level image uuid, not its @6c48a sub-asset."""
    cfg = parse_fnt(fnt_abs)
    return {"ver": "1.0.6", "importer": "bitmap-font", "imported": True,
            "uuid": asset_uuid(db_path(fnt_abs)), "files": [".json"], "subMetas": {},
            "userData": {"_fntConfig": cfg, "fontSize": cfg["fontSize"],
                         "textureUuid": atlas_image_uuid}}
