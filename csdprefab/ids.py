# -*- coding: utf-8 -*-
"""Deterministic asset uuids and prefab fileIds.

Both are derived from the asset's db:// path, so re-running the converter produces the
same ids and never breaks references from prefabs that were already committed.
"""
import base64
import hashlib
import os
import uuid

# Fixed namespace: changing this re-issues every uuid the tool has ever generated.
NAMESPACE = uuid.UUID('6f6d1e6a-1b1e-4b7a-9f3a-a1b2c3d4e5f6')


def db_path(abs_path):
    """Absolute path under <project>/assets -> db://assets/... form."""
    unix = abs_path.replace(os.sep, '/')
    if '/assets/' not in unix:
        raise ValueError('not inside an assets folder: %s' % abs_path)
    return 'db://assets' + unix.split('/assets', 1)[1]


def asset_uuid(db):
    """Stable uuid for a db:// path."""
    return str(uuid.uuid5(NAMESPACE, db))


def file_id(seed):
    """22-character Creator fileId, stable for a given seed string."""
    return base64.b64encode(hashlib.md5(seed.encode('utf-8')).digest()).decode('ascii')[:22]
