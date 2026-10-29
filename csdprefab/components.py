# -*- coding: utf-8 -*-
"""Cocos Creator 3.8 component payloads.

Every enum value here was checked against components that already exist in this project
rather than taken from memory. Two of them are easy to get wrong:

  cc.Sprite.Type   SIMPLE=0  SLICED=1  TILED=2  FILLED=3
      Using 2 for 9-slice silently tiles the texture instead. This project's prefabs
      only ever contain 0, 1 and 3 - a 2 is always a bug.
  blend factors    ZERO=0 ONE=1 SRC_ALPHA=2 DST_ALPHA=3 ONE_MINUS_SRC_ALPHA=4 ...
"""
import math

SIMPLE, SLICED = 0, 1
UI_LAYER = 33554432

# GL constant -> cc.gfx.BlendFactor
GL_TO_BLEND = {0: 0, 1: 1, 770: 2, 772: 3, 771: 4, 773: 5, 768: 6, 774: 7, 769: 8, 775: 9}

# cc.Widget align flags: TOP|BOTTOM|LEFT|RIGHT = full stretch
STRETCH = 45


def vec3(x, y, z=0):
    return {"__type__": "cc.Vec3", "x": x, "y": y, "z": z}


def vec2(x, y):
    return {"__type__": "cc.Vec2", "x": x, "y": y}


def size(w, h):
    return {"__type__": "cc.Size", "width": w, "height": h}


def color(r, g, b, a=255):
    return {"__type__": "cc.Color", "r": r, "g": g, "b": b, "a": a}


def quat_z(deg):
    half = math.radians(deg) / 2.0
    return {"__type__": "cc.Quat", "x": 0, "y": 0, "z": math.sin(half), "w": math.cos(half)}


def node(name, parent_id, lpos, scale, angle_z, active=True):
    """A .csd position is relative to the parent's bottom-left corner; a Creator _lpos is
    relative to the parent's anchor point, so callers must pass lpos already offset by
    -parentAnchor * parentSize. Rotation flips sign: Cocos Studio's RotationSkewX is
    clockwise-positive, Creator's euler z is counter-clockwise-positive."""
    return {
        "__type__": "cc.Node", "_name": name, "_objFlags": 0, "__editorExtras__": {},
        "_parent": {"__id__": parent_id} if parent_id is not None else None,
        "_children": [], "_active": active, "_components": [], "_prefab": None,
        "_lpos": vec3(lpos[0], lpos[1]), "_lrot": quat_z(angle_z),
        "_lscale": vec3(scale[0], scale[1], 1),
        "_mobility": 0, "_layer": UI_LAYER, "_euler": vec3(0, 0, angle_z), "_id": "",
    }


def map_blend(blend):
    """A src factor of GL_ONE in the .csd means 'the texture is premultiplied' - cocos2d-x
    premultiplies PNGs at load time. Creator keeps straight alpha, so copying GL_ONE
    across makes the colour surviving in transparent pixels get added over the background
    at full strength, drawing a solid rectangle around the artwork."""
    if not blend:
        return 2, 4
    src, dst = blend
    if src == 1:
        src = 770                                   # GL_ONE -> GL_SRC_ALPHA
    return GL_TO_BLEND.get(src, 2), GL_TO_BLEND.get(dst, 4)


def ui_transform(node_size, anchor):
    return {"__type__": "cc.UITransform", "_contentSize": size(node_size[0], node_size[1]),
            "_anchorPoint": vec2(anchor[0], anchor[1])}


def sprite(frame_uuid, rgb, blend, sliced):
    src, dst = map_blend(blend)
    return {
        "__type__": "cc.Sprite", "_customMaterial": None,
        "_srcBlendFactor": src, "_dstBlendFactor": dst,
        "_color": color(rgb[0], rgb[1], rgb[2]),
        "_spriteFrame": ({"__uuid__": frame_uuid, "__expectedType__": "cc.SpriteFrame"}
                         if frame_uuid else None),
        "_type": SLICED if sliced else SIMPLE, "_fillType": 0, "_sizeMode": 0,
        "_fillCenter": vec2(0, 0), "_fillStart": 0, "_fillRange": 0,
        # _isTrimmedMode true stretches the auto-trimmed region over the whole node and
        # throws away the frame's trim offset, so any art with transparent margins moves
        # and grows. It is invisible on tightly-cropped art and obvious on a sequence
        # whose bounding box changes per frame (a sweeping flare). false insets the frame
        # by its trim margins, reproducing the .csd placement, and matches this project's
        # own convention (7229 sprites false vs 430 true).
        "_isTrimmedMode": False, "_useGrayscale": False, "_atlas": None,
    }


def label(text, font_size, rgb, font_uuid=None, wrap=False):
    """Cocos Studio Text nodes are left/top aligned; IsCustomSize means the designer fixed
    the box, which maps to CLAMP overflow with wrapping on."""
    return {
        "__type__": "cc.Label", "_customMaterial": None,
        "_srcBlendFactor": 2, "_dstBlendFactor": 4,
        "_color": color(rgb[0], rgb[1], rgb[2]), "_string": text,
        "_horizontalAlign": 0, "_verticalAlign": 0,
        "_actualFontSize": font_size, "_fontSize": font_size, "_fontFamily": "Arial",
        "_lineHeight": font_size, "_overflow": 1 if wrap else 0,
        "_enableWrapText": bool(wrap),
        "_font": ({"__uuid__": font_uuid, "__expectedType__": "cc.BitmapFont"}
                  if font_uuid else None),
        "_isSystemFontUsed": font_uuid is None, "_spacingX": 0,
        "_isItalic": False, "_isBold": False, "_isUnderline": False, "_underlineHeight": 0,
        "_cacheMode": 0, "_enableOutline": False, "_outlineColor": color(0, 0, 0),
        "_outlineWidth": 2, "_enableShadow": False, "_shadowColor": color(0, 0, 0),
        "_shadowOffset": vec2(2, 2), "_shadowBlur": 2,
    }


def button():
    """Cocos Studio buttons in this project use the same image for every state, so the
    project convention is the SCALE transition (3) rather than sprite swapping."""
    return {"__type__": "cc.Button", "clickEvents": [], "_interactable": True,
            "_transition": 3, "_normalColor": color(255, 255, 255),
            "_hoverColor": color(211, 211, 211), "_pressedColor": color(255, 255, 255),
            "_disabledColor": color(124, 124, 124), "_normalSprite": None,
            "_hoverSprite": None, "_pressedSprite": None, "_disabledSprite": None,
            "_duration": 0.1, "_zoomScale": 0.9, "_target": None}


def mask():
    return {"__type__": "cc.Mask", "_type": 0, "_inverted": False,
            "_segments": 64, "_alphaThreshold": 0.1}


def opacity(value):
    return {"__type__": "cc.UIOpacity", "_opacity": value}


def widget(w, h):
    return {"__type__": "cc.Widget", "_alignFlags": STRETCH, "_target": None,
            "_left": 0, "_right": 0, "_top": 0, "_bottom": 0,
            "_horizontalCenter": 0, "_verticalCenter": 0,
            "_isAbsLeft": True, "_isAbsRight": True, "_isAbsTop": True, "_isAbsBottom": True,
            "_isAbsHorizontalCenter": True, "_isAbsVerticalCenter": True,
            "_originalWidth": w, "_originalHeight": h, "_alignMode": 1,
            "_lockFlags": STRETCH}


def scroll_view(content_id, direction, bounce):
    return {"__type__": "cc.ScrollView", "bounceDuration": 0.23, "brake": 0.75,
            "elastic": bounce, "inertia": True,
            "horizontal": 'Horizontal' in direction or 'Both' in direction,
            "vertical": 'Vertical' in direction or 'Both' in direction,
            "cancelInnerEvents": True, "scrollEvents": [],
            "_content": {"__id__": content_id},
            "_horizontalScrollBar": None, "_verticalScrollBar": None}


def animation(clip_uuid):
    ref = {"__uuid__": clip_uuid, "__expectedType__": "cc.AnimationClip"}
    return {"__type__": "cc.Animation", "playOnLoad": False,
            "_clips": [ref], "_defaultClip": dict(ref)}
