"""Installed package resources, independent of the working directory."""
import hashlib
from importlib.resources import files
import json


def load_profile(name):
    if name not in ('screen', 'full'):
        raise ValueError(f'Unknown profile: {name}')
    return json.loads(files('ssdbench').joinpath('profiles', name + '.json').read_text())


def source_hashes():
    package = files('ssdbench')
    sources = [(f'ssdbench/{p.name}', p) for p in package.iterdir()
               if p.name.endswith('.py') and p.is_file()]
    profiles = [(f'ssdbench/profiles/{p.name}', p)
                for p in package.joinpath('profiles').iterdir()
                if p.name.endswith('.json') and p.is_file()]
    return {name: hashlib.sha256(p.read_bytes()).hexdigest()
            for name, p in sorted(sources + profiles)}
