# Installation and upgrades

The executable is `ssdbench`. Existing subcommands and options are unchanged:

```bash
ssdbench --version
ssdbench list
sudo ssdbench plan --device /dev/disk/by-id/ata-MODEL_SERIAL --profile screen
sudo ssdbench run --device /dev/disk/by-id/ata-MODEL_SERIAL --profile screen
sudo ssdbench report --results /srv/ssd-results
```

The disk path may use another whole-disk stable alias, such as `scsi-0ATA_...`; actual transport and device usage are checked independently of that name. No disk operations are performed by installation, `--help`, or `--version`.

## Station installation

Follow the dedicated `/opt/ssdbench` virtual environment instructions in the README. It provides a root-owned installed copy and `/usr/local/bin/ssdbench` for use with sudo. Do not use an editable install for the privileged station command: install a regular copy and upgrade it after reviewing changes.

Run installation commands from the checkout containing `pyproject.toml`. The package name is `ssdbench`, but this project has not been published to PyPI; use `pip install .` or an explicit local wheel, not `pip install ssdbench` from a public index.

OS dependencies (`fio`, `smartctl`, util-linux, journalctl) remain external. Installing the Python wheel does not install or configure them, Caddy, or a service. Python 3.10+ is required; Linux is required for disk operations. Reports can also be rebuilt on macOS.

## Wheel installation

Build artifacts on a development machine in a separate environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

This creates a source archive and a pure-Python wheel under `dist/`. Copy the wheel to the station, create the dedicated virtual environment as shown in the README, then install the wheel (substitute its actual version):

```bash
sudo /opt/ssdbench/bin/python -m pip install --no-index --upgrade ./ssdbench-0.2.0-py3-none-any.whl
```

The wheel includes both JSON profiles and has no Python runtime dependencies. Wheel installation with `--no-index` requires no package-index access. Retain the source archive or checkout separately for the documentation and examples.

## Development installation

For unprivileged CLI/report development:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/ssdbench --help
.venv/bin/python -m unittest discover -s tests -v
```

Running `python3 -m ssdbench` from the checkout remains supported. When verifying an installed package, change to a directory outside the checkout so the source package cannot mask the installed copy.

## Upgrade and removal

Stop any active suite before upgrading. From the updated source checkout:

```bash
sudo /opt/ssdbench/bin/python -m pip install --upgrade .
ssdbench --version
sudo /usr/local/bin/ssdbench --version
```

These should report the same version. The existing symlink remains valid. For a rollback, reinstall a retained older wheel using `--force-reinstall` and its explicit path.

To uninstall the Python package:

```bash
sudo /opt/ssdbench/bin/python -m pip uninstall ssdbench
```

Remove `/usr/local/bin/ssdbench` only after confirming it is the symlink created for this project. The dedicated virtual environment can then be removed if no longer needed. Results in `/srv/ssd-results` and Caddy configuration are separate and remain intact.

## Packaging references

- [Python packaging metadata and console scripts](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Setuptools package data](https://setuptools.pypa.io/en/latest/userguide/datafiles.html)
