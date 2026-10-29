# -*- coding: utf-8 -*-
"""Copying source art into the project and authoring the Cocos Creator image .meta."""
import bisect
import os

from PIL import Image, ImageChops

from .ids import asset_uuid, db_path


def clean_transparent(im):
    """Zero the RGB left behind in fully-transparent pixels.

    Cocos Studio's loose source PNGs keep the artwork's old background colour where
    alpha is 0. Its own atlas exporter strips that, and leaving it in makes the colour
    bleed into the sprite's edges once the texture is filtered. Verified byte-identical
    to the shipped res/*.plist atlas frames on every comparable frame.
    """
    r, g, b, a = im.split()
    if a.getextrema()[0] != 0:
        return im
    keep = a.point(lambda v: 255 if v > 0 else 0)
    black = Image.new('L', im.size, 0)
    return Image.merge('RGBA', (Image.composite(r, black, keep),
                                Image.composite(g, black, keep),
                                Image.composite(b, black, keep), a))


def copy_image(src, dst):
    """Returns the saved image so the caller can author the .meta without decoding again."""
    im = clean_transparent(Image.open(src).convert('RGBA'))
    im.save(dst)
    return im


def _changes(im, axis):
    """Indices i where line i differs from line i+1 along the axis."""
    w, h = im.size
    if axis == 'x':
        a, b = im.crop((0, 0, w - 1, h)), im.crop((1, 0, w, h))
    else:
        a, b = im.crop((0, 0, w, h - 1)), im.crop((0, 1, w, h))
    d = ImageChops.difference(a, b)
    n = (w - 1) if axis == 'x' else (h - 1)
    out = []
    for i in range(n):
        strip = d.crop((i, 0, i + 1, h)) if axis == 'x' else d.crop((0, i, w, i + 1))
        if any(mx for _, mx in strip.getextrema()):
            out.append(i)
    return out


def measure_insets(path):
    """Smallest (horizontal, vertical) inset whose interior is constant.

    Stretching the middle of that region is lossless, so this is the smallest 9-slice
    inset that still reproduces the artwork exactly. Returns half the dimension when the
    art never becomes constant (i.e. it cannot be stretched on that axis without loss).
    """
    im = Image.open(path).convert('RGBA')
    out = []
    for axis, size in (('x', im.size[0]), ('y', im.size[1])):
        ch = _changes(im, axis)
        limit = size // 2
        found = limit
        for inset in range(limit):
            lo = bisect.bisect_left(ch, inset)
            hi = bisect.bisect_right(ch, size - inset - 2)
            if lo >= hi:
                found = inset
                break
        out.append(found)
    return out[0], out[1]


def resolve_border(path, csd_edges, node_sizes):
    """Pick 9-slice borders that reproduce the .csd *and* survive Cocos Creator.

    cocos2d-x scales the caps down when left+right exceeds the target width; Creator
    instead clamps the middle span to zero and stretches the caps, which distorts the
    corner art. So when the .csd insets do not fit the smallest node the frame is drawn
    at, fall back to the inset measured from the artwork - lossless, and always fits.
    Returns (left, bottom, right, top).
    """
    left, bottom, right, top = csd_edges
    if not node_sizes:
        return csd_edges
    min_w = min(s[0] for s in node_sizes)
    min_h = min(s[1] for s in node_sizes)
    if left + right <= min_w and top + bottom <= min_h:
        return csd_edges
    mh, mv = measure_insets(path)
    if left + right > min_w:
        left = right = min(left, mh, max(0, int(min_w // 2) - 1))
    if top + bottom > min_h:
        top = bottom = min(top, mv, max(0, int(min_h // 2) - 1))
    return left, bottom, right, top


def _alpha_bbox(im):
    bbox = im.getchannel('A').getbbox()
    if bbox is None:
        return 0, 0, im.size[0], im.size[1]
    x0, y0, x1, y1 = bbox
    return x0, y0, x1 - x0, y1 - y0


def _sprite_frame_user_data(im, border, trim):
    rw, rh = im.size
    if trim:
        tx, ty, w, h = _alpha_bbox(im)
    else:
        tx, ty, w, h = 0, 0, rw, rh
    if w == 0 or h == 0:
        tx, ty, w, h = 0, 0, rw, rh
    off_x = (tx + w / 2.0) - rw / 2.0
    off_y = rh / 2.0 - (ty + h / 2.0)
    # The quad is centred on the trimmed rect; the offset is carried separately in
    # offsetX/offsetY and must NOT be folded in here. Verified against the frames Cocos
    # Creator itself wrote for close_button / get_dice / grid_img_box, all of which have
    # a non-zero offset and still use plus/minus half the trimmed size.
    x0, y0, x1, y1 = -w / 2.0, -h / 2.0, w / 2.0, h / 2.0
    # uv is measured from the BOTTOM of the raw image, and nuv is derived from the trim
    # rect rather than from uv. Both only coincide with the naive top-down form when the
    # trim happens to be symmetric, which is why an asymmetric crop silently went wrong.
    top, bottom = rh - ty, rh - ty - h
    left, right = tx, tx + w
    uv = [left, top, right, top, left, bottom, right, bottom]
    nuv = [left / rw, bottom / rh, right / rw, bottom / rh,
           left / rw, top / rh, right / rw, top / rh]
    return {
        "trimType": "auto" if trim else "none", "trimThreshold": 1, "rotated": False,
        "offsetX": off_x, "offsetY": off_y, "trimX": tx, "trimY": ty,
        "width": w, "height": h, "rawWidth": rw, "rawHeight": rh,
        "borderTop": border[3], "borderBottom": border[1],
        "borderLeft": border[0], "borderRight": border[2],
        "packable": True, "pixelsToUnit": 100, "pivotX": 0.5, "pivotY": 0.5, "meshType": 0,
        "vertices": {"rawPosition": [x0, y0, 0, x1, y0, 0, x0, y1, 0, x1, y1, 0],
                     "indexes": [0, 1, 2, 2, 1, 3], "uv": uv, "nuv": nuv,
                     "minPos": [x0, y0, 0], "maxPos": [x1, y1, 0]},
        "isUuid": True, "atlasUuid": "",
    }


def image_meta(png_abs, border=(0, 0, 0, 0), trim=None, im=None):
    """Author the image .meta.

    9-sliced art keeps full bleed (trimType none) so the border insets stay expressed in
    raw-image space. Bitmap-font atlases must also skip trimming, since the .fnt glyph
    rects are raw coordinates - pass trim=False for those. `im` reuses an already-decoded
    image; the path is still needed for the uuid.
    """
    if im is None:
        im = Image.open(png_abs).convert('RGBA')
    if trim is None:
        trim = (border == (0, 0, 0, 0))
    name = os.path.splitext(os.path.basename(png_abs))[0]
    u = asset_uuid(db_path(png_abs))
    sf = _sprite_frame_user_data(im, border, trim)
    sf["imageUuidOrDatabaseUri"] = u + "@6c48a"
    return {
        "ver": "1.0.27", "importer": "image", "imported": True, "uuid": u,
        "files": [".json", ".png"],
        "subMetas": {
            "6c48a": {"importer": "texture", "uuid": u + "@6c48a", "displayName": name,
                      "id": "6c48a", "name": "texture",
                      "userData": {"wrapModeS": "clamp-to-edge", "wrapModeT": "clamp-to-edge",
                                   "minfilter": "linear", "magfilter": "linear",
                                   "mipfilter": "none", "anisotropy": 0,
                                   "imageUuidOrDatabaseUri": u, "isUuid": True,
                                   "visible": False},
                      "ver": "1.0.22", "imported": True, "files": [".json"], "subMetas": {}},
            "f9941": {"importer": "sprite-frame", "uuid": u + "@f9941", "displayName": name,
                      "id": "f9941", "name": "spriteFrame", "userData": sf,
                      "ver": "1.0.12", "imported": True, "files": [".json"], "subMetas": {}},
        },
        "userData": {"type": "sprite-frame", "hasAlpha": True,
                     "fixAlphaTransparencyArtifacts": False, "redirect": u + "@6c48a"},
    }


def directory_meta(abs_dir):
    return {"ver": "1.2.0", "importer": "directory", "imported": True,
            "uuid": asset_uuid(db_path(abs_dir)), "files": [], "subMetas": {}, "userData": {}}
