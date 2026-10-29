# -*- coding: utf-8 -*-
"""Conversion config: load, validate, and generate a starter file."""
import io
import json
import os

from . import csd
from .locate import find_csd_root

# Solid white frame this project already uses for full-screen dimmers
# (assets/main-assets/bootstrap/BootstrapWhite.jpg). Panels with a background colour are
# emitted as a tinted Sprite pointing at it.
DEFAULT_WHITE_FRAME = 'decb66d8-92d9-4aa8-bc57-e0d253fd2a48@f9941'

# Cocos Studio's built-in placeholder: there is no real art behind it.
DEFAULT_PLACEHOLDERS = ['Default/ImageFile.png']

# csdRoot is deliberately NOT required: committed configs stay machine-independent
# and the root is discovered instead (see locate.py).
REQUIRED = ('csdDir', 'module', 'imagesOut', 'prefabs')


class Config(object):
    def __init__(self, data, path, csd_root=None):
        self.path = path
        self.data = data
        self._csd_root = csd_root
        for key in REQUIRED:
            if key not in data:
                raise ValueError('config is missing "%s"' % key)

    def __getattr__(self, name):
        return self.data.get(name)

    @property
    def csd_root(self):
        """Resolved once: the override, the config, the env var, then a search."""
        if self._csd_root is None:
            here = os.path.dirname(os.path.abspath(self.path))
            self._csd_root = find_csd_root(self.data.get('csdRoot'), start=here)
        return self._csd_root

    @property
    def csd_dir(self):
        return os.path.join(self.csd_root, self.data['csdDir'])

    @property
    def placeholders(self):
        return set(self.data.get('placeholders', DEFAULT_PLACEHOLDERS))

    @property
    def white_frame(self):
        return self.data.get('whiteFrame', DEFAULT_WHITE_FRAME)

    @property
    def reuse(self):
        """csd resource path -> existing project asset to reference instead of copying."""
        return self.data.get('reuse', {})

    @property
    def external_prefabs(self):
        """csd path -> already-converted .prefab, for ProjectNodes outside this batch."""
        return self.data.get('externalPrefabs', {})

    def entries(self):
        for entry in self.data['prefabs']:
            yield {
                'csd': entry['csd'],
                'out': entry['out'],
                'name': entry.get('name') or os.path.splitext(os.path.basename(
                    entry['out']))[0],
                'root': entry.get('root', 'container'),
            }


def load(path, csd_root=None):
    with io.open(path, encoding='utf-8') as fh:
        return Config(json.load(fh), path, csd_root)


def _default_out(module, name, is_view):
    if is_view:
        return 'assets/main-assets/%s/%s.prefab' % (module, name)
    return 'assets/art-assets/modules/%s/prefabs/%s.prefab' % (module, name)


def generate(csd_root, csd_dir, module):
    """Starter config: every .csd in the folder, views (those with a canvas) into
    main-assets, everything else into the module's art-assets prefabs folder."""
    folder = os.path.join(csd_root, csd_dir)
    prefabs = []
    for rel in csd.find_csd_files(folder):
        name = os.path.splitext(os.path.basename(rel))[0]
        _, _, canvas = csd.parse(os.path.join(folder, rel.replace('/', os.sep)))
        is_view = canvas != (0.0, 0.0)
        prefabs.append({'csd': rel, 'name': name,
                        'out': _default_out(module, name, is_view),
                        'root': 'view' if is_view else 'container'})
    # a ProjectNode can only reference a prefab that already exists, so views go last
    prefabs.sort(key=lambda e: e['root'] == 'view')
    return {
        # csdRoot is omitted on purpose - see locate.py. Add it only when the checkout
        # sits somewhere the search cannot reach.
        'csdDir': csd_dir,
        'module': module,
        'imagesOut': 'assets/art-assets/modules/%s/images/main' % module,
        'fontsOut': 'assets/art-assets/modules/%s/fnt' % module,
        'copyAllModuleImages': True,
        'reuse': {},
        'externalPrefabs': {},
        'placeholders': DEFAULT_PLACEHOLDERS,
        'prefabs': prefabs,
    }
