# -*- coding: utf-8 -*-
"""Finding the Cocos Studio project without hard-coding one machine's paths.

Committed configs must stay portable, so `csdRoot` is optional in them. The root is
resolved in this order:

  1. --csd-root on the command line
  2. "csdRoot" in the config, when it exists on this machine
  3. the INANNA_CSD_ROOT environment variable
  4. searching upward from the repo for */TMD_CocosStudio_Inanna/<marker>
"""
import glob
import os

ENV_VAR = 'INANNA_CSD_ROOT'

# The Cocos Studio project is checked out separately; only its tail is predictable.
PROJECT_DIR = 'TMD_CocosStudio_Inanna'
MARKER = os.path.join('CocoStudioProject', 'Inanna', 'cocosstudio')

SEARCH_LEVELS = 8          # deep enough to reach a sibling checkout from any
                           # starting point inside the repo


def _valid(path):
    return bool(path) and os.path.isdir(path)


def _search_upward(start):
    """Look for the Cocos Studio checkout beside, or near, the repo."""
    current = os.path.abspath(start)
    for _ in range(SEARCH_LEVELS + 1):
        for pattern in (os.path.join(current, PROJECT_DIR, MARKER),
                        os.path.join(current, '*', PROJECT_DIR, MARKER)):
            for hit in sorted(glob.glob(pattern)):
                if os.path.isdir(hit):
                    return hit
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def repo_root():
    """<repo>/tools/csd_to_prefab/csdprefab/locate.py -> <repo>"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, '..', '..', '..'))


def find_csd_root(explicit=None, start=None):
    """Resolve the cocosstudio folder, or raise with the ways to point at it."""
    for candidate in (explicit, os.environ.get(ENV_VAR)):
        if _valid(candidate):
            return os.path.abspath(candidate)
    # Search from the repo as well as the caller's directory, so the result does not
    # depend on which folder the command happened to be run from.
    for base in (start, repo_root(), os.getcwd()):
        found = _search_upward(base) if base else None
        if found:
            return found
    tried = [c for c in (explicit, os.environ.get(ENV_VAR)) if c]
    raise RuntimeError(
        'cannot find the Cocos Studio project (%s/%s).\n'
        'Point at it with --csd-root, with "csdRoot" in the config, or by setting %s.%s'
        % (PROJECT_DIR, MARKER.replace(os.sep, '/'), ENV_VAR,
           ('\nTried: %s' % ', '.join(tried)) if tried else ''))
