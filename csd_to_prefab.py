# -*- coding: utf-8 -*-
"""Convert Cocos Studio .csd layouts into Cocos Creator 3.8 prefabs.

    python csd_to_prefab.py init <module> --csd-dir <folder> [--csd-root <cocosstudio>]
    python csd_to_prefab.py convert <config.json>
    python csd_to_prefab.py verify  <config.json>
    python csd_to_prefab.py drift   <config.json> [--fix]

Read AGENT_GUIDE.md first. Always run `verify` after `convert` - it is what catches the
mistakes this converter is prone to.
"""
import argparse
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from csdprefab import config, convert, csd, locate, render, verify   # noqa: E402


def project_root():
    """<repo>/tools/csd_to_prefab/ -> <repo>"""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def log(message):
    sys.stdout.write(message + '\n')
    sys.stdout.flush()


# ------------------------------------------------------------------------- init
def cmd_init(args):
    root = locate.find_csd_root(args.csd_root, start=project_root())
    log('using the Cocos Studio project at %s' % root)
    folder = os.path.join(root, args.csd_dir or args.module)
    if not os.path.isdir(folder):
        log('no such folder: %s' % folder)
        return 2
    data = config.generate(root, args.csd_dir or args.module, args.module)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'configs', '%s.json' % args.module)
    if not os.path.isdir(os.path.dirname(out)):
        os.makedirs(os.path.dirname(out))
    with io.open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    log('wrote %s with %d prefab entries' % (out, len(data['prefabs'])))
    log('review "out" paths and fill in "reuse" / "externalPrefabs" before converting')
    return 0


# ---------------------------------------------------------------------- convert
def cmd_convert(args):
    cfg = config.load(args.config, getattr(args, 'csd_root', None))
    root = project_root()
    convert.run(cfg, root, log)
    log('done - now run: python csd_to_prefab.py verify %s' % args.config)
    return 0


# ------------------------------------------------------------------------ drift
def cmd_drift(args):
    """Report generated prefabs that no longer match their .csd, and optionally rebuild."""
    cfg = config.load(args.config, getattr(args, 'csd_root', None))
    root = project_root()
    drifted = convert.drift(cfg, root, log)
    if not drifted:
        return 0
    if not args.fix:
        log('')
        log('re-run with --fix to rebuild these from the .csd')
        return 1
    log('')
    convert.run(cfg, root, log)
    remaining = convert.drift(cfg, root, log)
    if remaining:
        log('still drifting after the rebuild - the editor may be writing the file back; '
            'close the prefab in Cocos Creator and run this again')
        return 1
    return 0


# ----------------------------------------------------------------------- verify
def _frame_index(cfg, root):
    subdirs = {os.path.dirname(cfg.imagesOut)}
    if cfg.fontsOut:
        subdirs.add(cfg.fontsOut)
    for rel in cfg.reuse.values():
        subdirs.add(os.path.dirname(rel))
    for rel in cfg.external_prefabs.values():
        subdirs.add(os.path.dirname(rel))
    subdirs.add('assets/main-assets/bootstrap')
    return render.build_frame_index(root, sorted(subdirs))


def _csdview_specs(cfg, entries):
    """Fetch every csdview spec at once - the calls are separate processes, so running
    them together turns six half-second waits into one."""
    paths = [os.path.join(cfg.csd_dir, e['csd']) for e in entries]
    with ThreadPoolExecutor(max_workers=min(8, len(paths) or 1)) as pool:
        return dict(zip(paths, pool.map(verify.csdview_rects, paths)))


def _asset_dirs(cfg):
    """Folders this conversion writes to or reuses from - checked before the whole tree."""
    dirs = {os.path.dirname(cfg.imagesOut)}
    if cfg.fontsOut:
        dirs.add(cfg.fontsOut)
    for rel in list(cfg.reuse.values()) + list(cfg.external_prefabs.values()):
        dirs.add(os.path.dirname(rel))
    for entry in cfg.entries():
        dirs.add(os.path.dirname(entry['out']))
    dirs.add('assets/main-assets/bootstrap')
    return sorted(dirs)


def _verify_entry(cfg, root, entry, frames, fonts, failures, specs):
    out_abs = os.path.join(root, entry['out'].replace('/', os.sep))
    csd_path = os.path.join(cfg.csd_dir, entry['csd'])
    objs = verify.load(out_abs)

    holes, bad_refs = verify.check_integrity(objs)
    if holes or bad_refs:
        failures.append('%s: %d unfilled slots, bad refs %s'
                        % (entry['csd'], holes, bad_refs[:3]))

    for name, why in verify.check_sliced_insets(objs, frames):
        failures.append('%s: sliced sprite "%s" %s' % (entry['csd'], name, why))
    for name, why in verify.check_trim_mode(objs, frames):
        failures.append('%s: sprite "%s" %s' % (entry['csd'], name, why))
    for name, why in verify.check_labels(objs, fonts):
        failures.append('%s: label "%s" %s' % (entry['csd'], name, why))

    clip_path = out_abs.replace('.prefab', '_animation0.anim')
    clip = verify.load(clip_path) if os.path.exists(clip_path) else None
    for name, why in verify.check_animated_frames(objs, clip, frames):
        failures.append('%s: %s %s' % (entry['csd'], name, why))

    count, same = verify.compare_labels(objs, csd_path)
    if not same:
        failures.append('%s: label strings differ from the .csd' % entry['csd'])

    _, _, canvas = csd.parse(csd_path)
    offset = (0.0, 0.0)
    if entry['root'] == 'view' and canvas != (0.0, 0.0):
        offset = (0.5 * canvas[0], 0.5 * canvas[1])
    geo = verify.compare_geometry(objs, csd_path, root_offset=offset,
                                  rects=specs.get(csd_path))
    if geo is None:
        log('%-28s %3d labels  geometry: csdview not on PATH, skipped' % (entry['csd'], count))
        return
    if not geo['ok']:
        failures.append('%s: geometry off by %.2fpx at %s'
                        % (entry['csd'], geo['worst_geometry'][0], geo['worst_geometry'][1]))
    log('%-28s %3d labels  %3d nodes  geometry<=%.2fpx  labels<=%.1fpx'
        % (entry['csd'], count, geo['compared'], geo['worst_geometry'][0],
           geo['worst_label'][0]))


def cmd_verify(args):
    cfg = config.load(args.config, getattr(args, 'csd_root', None))
    root = project_root()
    entries = list(cfg.entries())
    frames = _frame_index(cfg, root)
    fonts = verify.build_font_index(os.path.join(root, 'assets'),
                                    [os.path.join(root, d) for d in _asset_dirs(cfg)])
    specs = _csdview_specs(cfg, entries)
    failures = []
    generated = []
    for entry in entries:
        _verify_entry(cfg, root, entry, frames, fonts, failures, specs)
        out_abs = os.path.join(root, entry['out'].replace('/', os.sep))
        generated.append(out_abs)
        clip = out_abs.replace('.prefab', '_animation0.anim')
        if os.path.exists(clip):
            generated.append(clip)

    missing = verify.check_references(generated, os.path.join(root, 'assets'),
                                     search_dirs=_asset_dirs(cfg))
    if missing:
        failures.append('unresolved asset references: %s' % missing[:5])

    log('')
    if failures:
        for f in failures:
            log('FAIL  %s' % f)
        return 1
    log('all checks passed')
    log('label deltas are expected: csdview measures rendered glyphs, the .csd stores the')
    log('designer box. Only whole-block displacement of a text node is a real problem.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command')

    p_init = sub.add_parser('init', help='generate a starter config for a module')
    p_init.add_argument('module')
    p_init.add_argument('--csd-dir', help='folder under cocosstudio/ (default: module name)')
    p_init.add_argument('--csd-root', help='path to the Cocos Studio cocosstudio/ folder')
    p_init.add_argument('--out', help='where to write the config')
    p_init.set_defaults(func=cmd_init)

    p_conv = sub.add_parser('convert', help='copy art and build the prefabs')
    p_conv.add_argument('config')
    p_conv.add_argument('--csd-root', help='override where the .csd files live')
    p_conv.set_defaults(func=cmd_convert)

    p_ver = sub.add_parser('verify', help='check the generated prefabs against the .csd')
    p_ver.add_argument('config')
    p_ver.add_argument('--csd-root', help='override where the .csd files live')
    p_ver.set_defaults(func=cmd_verify)

    p_drift = sub.add_parser('drift', help='find prefabs edited outside this tool')
    p_drift.add_argument('config')
    p_drift.add_argument('--csd-root', help='override where the .csd files live')
    p_drift.add_argument('--fix', action='store_true', help='rebuild the drifted prefabs')
    p_drift.set_defaults(func=cmd_drift)

    args = parser.parse_args(argv)
    if not getattr(args, 'func', None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
