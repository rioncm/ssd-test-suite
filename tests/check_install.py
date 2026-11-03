"""Build-artifact acceptance: install a wheel into a disposable environment.

Usage: python3 tests/check_install.py dist/ssdbench-VERSION-py3-none-any.whl
Uses no disk-testing tools and installs only the supplied local wheel.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def main():
    wheel = Path(sys.argv[1]).resolve(strict=True)
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='ssdbench-install-') as directory:
        root = Path(directory)
        environment = root / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / 'bin/python'
        cli = environment / 'bin/ssdbench'

        def run(*args):
            return subprocess.run([str(a) for a in args], cwd=root, check=True,
                                  text=True, capture_output=True).stdout

        run(python, '-m', 'pip', 'install', '--no-index', '--no-deps', wheel)
        version = run(cli, '--version').strip()
        assert version.startswith('ssdbench '), version
        assert 'plan' in run(cli, '--help')
        assert '--device' in run(cli, 'plan', '--help')
        assert '--confirm-erase' in run(cli, 'run', '--help')
        assert version == run(python, '-m', 'ssdbench', '--version').strip()
        run(python, '-I', '-c', '''
from importlib.metadata import version
from pathlib import Path
import ssdbench
from ssdbench.resources import load_profile, source_hashes
assert version('ssdbench') == ssdbench.__version__
assert 'site-packages' in str(Path(ssdbench.__file__))
assert load_profile('screen')['mode'] == 'screen'
assert load_profile('full')['mode'] == 'full'
assert 'ssdbench/profiles/full.json' in source_hashes()
''')
        # Run the full regression suite against the installed package, not the checkout.
        shutil.copytree(source / 'tests', root / 'tests', ignore=shutil.ignore_patterns('__pycache__'))
        print(run(python, '-m', 'unittest', 'discover', '-s', 'tests'))
        # The demo generator adds its parent to sys.path; copy it away from source too.
        (root / 'examples').mkdir()
        shutil.copy(source / 'examples/make_demo.py', root / 'examples/make_demo.py')
        results = root / 'results'
        run(python, root / 'examples/make_demo.py', results)
        run(cli, 'report', '--results', results)
        assert (results / 'index.html').is_file()
        assert list(results.glob('*/*/report.html'))
        print(f'{version}: clean wheel installation, installed regression tests, profiles, '
              'manifest hashes, console/module entry points, and report regeneration passed.')


if __name__ == '__main__':
    main()
