# -*- coding: utf-8 -*-
"""Cocos Studio timelines -> one cc.AnimationClip.

Easing is flattened to linear, matching every other converted .anim already in this
project (all of their keyframes carry easingMethod 0). Constant single-key tracks such as
AnchorPoint / CColor / BlendFunc are already baked into the node, so they add nothing.
"""
import json

FPS = 60.0
WRAP_LOOP = 2


def _real_key(value):
    return {"__type__": "cc.RealKeyframeValue", "interpolationMode": 0,
            "tangentWeightMode": 0, "value": value, "rightTangent": 0,
            "rightTangentWeight": 0, "leftTangent": 0, "leftTangentWeight": 0,
            "easingMethod": 0, "__editorExtras__": None}


class Clip(object):
    def __init__(self, name):
        self.name = name
        self.objs = [None]
        self.tracks = []
        self.duration = 0.0

    def add(self, obj):
        self.objs.append(obj)
        return len(self.objs) - 1

    def _path(self, hierarchy, component, prop):
        parts = [{"__id__": self.add({"__type__": "cc.animation.HierarchyPath",
                                      "path": hierarchy})}]
        if component:
            parts.append({"__id__": self.add({"__type__": "cc.animation.ComponentPath",
                                              "component": component})})
        parts.append(prop)
        return self.add({"__type__": "cc.animation.TrackPath", "_paths": parts})

    def _channel(self, times, values):
        curve = self.add({"__type__": "cc.RealCurve", "_times": list(times),
                          "_values": [_real_key(v) for v in values]})
        return {"__id__": self.add({"__type__": "cc.animation.Channel",
                                    "_curve": {"__id__": curve}})}

    def _track(self, kind, path_id, extra):
        body = {"__type__": kind,
                "_binding": {"__type__": "cc.animation.TrackBinding",
                             "path": {"__id__": path_id}}}
        body.update(extra)
        self.tracks.append(self.add(body))

    def vector(self, hierarchy, prop, times, xs, ys, zs):
        """Creator always writes four channels for a VectorTrack; the fourth stays empty."""
        path_id = self._path(hierarchy, None, prop)
        self._track('cc.animation.VectorTrack', path_id, {
            "_channels": [self._channel(times, xs), self._channel(times, ys),
                          self._channel(times, zs), self._channel([], [])],
            "_nComponents": 3})
        self._bump(times)

    def real(self, hierarchy, component, prop, times, values):
        path_id = self._path(hierarchy, component, prop)
        self._track('cc.animation.RealTrack', path_id,
                    {"_channel": self._channel(times, values)})
        self._bump(times)

    def objects(self, hierarchy, component, prop, times, values):
        path_id = self._path(hierarchy, component, prop)
        curve = self.add({"__type__": "cc.ObjectCurve", "_times": list(times),
                          "_values": list(values)})
        self._track('cc.animation.ObjectTrack', path_id, {
            "_channel": {"__id__": self.add({"__type__": "cc.animation.Channel",
                                             "_curve": {"__id__": curve}})}})
        self._bump(times)

    def _bump(self, times):
        if times:
            self.duration = max(self.duration, times[-1])

    def dump(self, duration):
        self.objs[0] = {"__type__": "cc.AnimationClip", "_name": self.name, "_objFlags": 0,
                        "_native": "", "sample": 60, "speed": 1, "wrapMode": WRAP_LOOP,
                        "_duration": duration, "_hash": 0,
                        "_tracks": [{"__id__": t} for t in self.tracks],
                        "_events": [], "_exoticAnimation": None}
        return json.dumps(self.objs, ensure_ascii=False, indent=2)


def _frames(timelines):
    out = []
    for tl in timelines:
        out.extend(list(tl))
    return out


def _num(el, attr, default=0.0):
    v = el.get(attr)
    return float(v) if v is not None else default


def build(anim_el, by_tag, name, images, notes):
    """anim_el: the .csd <Animation> element. by_tag: ActionTag -> hierarchy path."""
    clip = Clip(name)
    declared = float(anim_el.get('Duration') or 0) / FPS
    groups = {}
    for tl in anim_el.findall('Timeline'):
        groups.setdefault((tl.get('ActionTag'), tl.get('Property')), []).append(tl)

    for (tag, prop), timelines in groups.items():
        hierarchy = by_tag.get(tag)
        if hierarchy is None:
            notes.append('animation: no node for ActionTag %s (%s)' % (tag, prop))
            continue
        frames = _frames(timelines)
        times = [float(f.get('FrameIndex')) / FPS for f in frames]
        if not times:
            continue
        _emit_track(clip, prop, hierarchy, frames, times, images, notes)
    return clip, max(declared, clip.duration)


def _emit_track(clip, prop, hierarchy, frames, times, images, notes):
    if prop == 'Position':
        clip.vector(hierarchy, 'position', times, [_num(f, 'X') for f in frames],
                    [_num(f, 'Y') for f in frames], [0.0] * len(frames))
    elif prop == 'Scale':
        clip.vector(hierarchy, 'scale', times, [_num(f, 'X', 1.0) for f in frames],
                    [_num(f, 'Y', 1.0) for f in frames], [1.0] * len(frames))
    elif prop == 'RotationSkew':
        clip.vector(hierarchy, 'eulerAngles', times, [0.0] * len(frames),
                    [0.0] * len(frames), [-_num(f, 'X') for f in frames])
    elif prop == 'Alpha':
        clip.real(hierarchy, 'cc.UIOpacity', 'opacity', times,
                  [_num(f, 'Value', 255) for f in frames])
    elif prop == 'FileData':
        values = []
        for f in frames:
            tf = f.find('TextureFile')
            res = (tf.get('Path') or '').replace('\\', '/') if tf is not None else ''
            uuid_ = images.get(res)
            if uuid_ is None:
                notes.append('animation: no art for frame %s' % res)
            values.append({"__uuid__": uuid_, "__expectedType__": "cc.SpriteFrame"}
                          if uuid_ else None)
        clip.objects(hierarchy, 'cc.Sprite', 'spriteFrame', times, values)
    elif len(frames) > 1:
        notes.append('animation: %s track on %s not converted' % (prop, hierarchy))
