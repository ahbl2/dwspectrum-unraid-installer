#!/usr/bin/env python3
"""Validate a DW Spectrum config archive without extracting or disclosing secrets."""
import argparse
import pathlib
import tarfile
import sys


def verify(path):
    archive = pathlib.Path(path)
    with tarfile.open(archive, 'r:gz') as tf:
        members = tf.getmembers()
        if not members or len(members) > 100000:
            raise ValueError('empty or excessively large archive')
        names = set()
        types = {}
        for item in members:
            name = item.name.removeprefix('./')
            parts = pathlib.PurePosixPath(name).parts
            if (not parts or parts[0] != 'config' or '..' in parts
                    or item.issym() or item.islnk() or not (item.isfile() or item.isdir())
                    or name in names):
                raise ValueError('unsafe archive entry')
            names.add(name)
            types[name] = 'file' if item.isfile() else 'dir'
            if item.isfile():
                stream = tf.extractfile(item)
                if stream is None:
                    raise ValueError('unreadable archive entry')
                while stream.read(1024 * 1024):
                    pass
        if any(kind == 'file' and any(other.startswith(name + '/') for other in names) for name,kind in types.items()):
            raise ValueError('archive contains file ancestor of another entry')
        if not {'config/.initialized', 'config/var', 'config/etc'}.issubset(names):
            raise ValueError('missing required configuration structure')
        if not (types['config'] == 'dir' and types['config/.initialized'] == 'file' and types['config/var'] == 'dir' and types['config/etc'] == 'dir'):
            raise ValueError('incorrect configuration entry type')
    return len(members)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive')
    args = parser.parse_args()
    try:
        count = verify(args.archive)
    except (OSError, ValueError, tarfile.TarError) as exc:
        print('REFUSED: archive validation failed (' + type(exc).__name__ + ')', file=sys.stderr)
        sys.exit(42)
    print(f'PASS: backup archive safely validated ({count} entries)')
