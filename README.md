# SSD Bench

A command-line SATA SSD qualification suite for Ubuntu Server 24.04. It runs SMART self-tests and `fio` workloads, preserves evidence, and generates static HTML reports and a CSV catalog suitable for Caddy. Python uses only the standard library.

**Full qualification destroys all data on the selected drive.** The default `screen` profile performs no host writes or TRIM. Both profiles require an idle, unmounted, direct SATA/eSATA SSD. USB bridges, NVMe, SAS, HDDs, and RAID logical disks are outside this first version's supported scope.

## Install

Copy this project to your Ubuntu station, then enter its directory. Use Python 3.10 or later (Ubuntu 24.04 includes Python 3.12).

Install into a dedicated environment and expose the command system-wide:

```bash
sudo apt update
sudo apt install python3 python3-venv fio smartmontools util-linux tmux
sudo python3 -m venv /opt/ssdbench
sudo /opt/ssdbench/bin/python -m pip install .
sudo ln -s /opt/ssdbench/bin/ssdbench /usr/local/bin/ssdbench
sudo install -d -m 0755 /srv/ssd-results
ssdbench --version
```

The install copies the Python package and its test profiles into `/opt/ssdbench`; it does not require the checkout at runtime. Run `ssdbench` from any directory. The dedicated environment avoids changing Ubuntu's system Python packages and works with `sudo ssdbench`. Initial builds download setuptools from the configured Python package index; runtime has no third-party Python dependencies.

If APT cannot locate `fio`, enable Universe with `sudo add-apt-repository universe`, update APT, and retry. If `/usr/local/bin/ssdbench` already exists, inspect it before creating the link; do not overwrite an unrelated executable. If sudo's PATH omits `/usr/local/bin`, use `sudo /usr/local/bin/ssdbench`.

To upgrade from an updated checkout, with no suite running:

```bash
sudo /opt/ssdbench/bin/python -m pip install --upgrade .
ssdbench --version
```

The symlink only needs to be created once. Source/profile edits take effect after reinstalling. See [installation options](docs/installation.md) for wheels, development installs, and removal.

## Identify and preview

```bash
ssdbench list
sudo ssdbench plan \
  --device /dev/disk/by-id/ata-YOUR_MODEL_YOUR_SERIAL \
  --profile screen
```

Replace the example path with the whole-disk ID from `list`; do not use a `-partN` path. `plan` validates the target and displays the exact workload parameters without running SMART tests or fio. Verify model, serial, capacity, and transport.

The runner rejects mounted disks and descendants, active swap, device-mapper/RAID holders, storage-pool/member signatures (including ZFS and Btrfs), and the disk containing the results filesystem. It rechecks the identity and usage before each stage. Keep automounters and other disk-management jobs inactive during a run; these checks are not a kernel-level exclusive lock against unrelated programs.

## Run read-only screening

Start a persistent terminal session:

```bash
tmux new -s ssdbench
```

Then run:

```bash
sudo ssdbench run \
  --device /dev/disk/by-id/ata-YOUR_MODEL_YOUR_SERIAL \
  --profile screen \
  --results /srv/ssd-results
```

Detach with **Ctrl+B, then D**; reconnect with `tmux attach -t ssdbench`. The runner prints each stage and the final report path. It does not automatically test newly attached drives.

## Run full qualification

Preview first with `plan --profile full`. After confirming the selected SSD is expendable:

```bash
sudo ssdbench run \
  --device /dev/disk/by-id/ata-YOUR_MODEL_YOUR_SERIAL \
  --profile full \
  --confirm-erase YOUR_SERIAL \
  --results /srv/ssd-results
```

The serial must exactly match the target. There is no default target, automatic selection, or general-purpose force flag. This overwrites partitions and files; it is **not a certified sanitization or secure-erase procedure**.

## Read the results

Open `/srv/ssd-results/index.html` or serve that directory with Caddy. Each report includes drive identity, outcome and reasons, individual stage results, exact I/O coverage, throughput/IOPS, total-latency percentiles, temperature and verification-write charts, SMART comparisons, and links to raw evidence.

| Outcome | Interpretation | Exit code |
|---|---|---|
| PASS | Required I/O finished, supported self-tests passed, no automated review findings | 0 |
| REVIEW | Workloads completed, but health, unsupported checks, temperature availability, or logs require review | 2 |
| FAIL | SMART health/self-test failure or verified data mismatch | 3 |
| INCOMPLETE | A required stage was interrupted, failed to execute, timed out, or lacked full coverage | 4 |
| Preflight error | Target, dependencies, arguments, lock, or setup rejected | 1 |

An interrupted run with a proven failure remains FAIL. Ordinary fio I/O errors produce an INCOMPLETE result with a review reason because cable/controller/configuration faults must be distinguished from media failure. Performance has no universal pass threshold. A screening PASS does not qualify writes or guarantee future reliability.

## Documentation

- [Installation and upgrades](docs/installation.md)
- [Test methodology and profile settings](docs/methodology.md)
- [Report format and interpretation](docs/reporting.md)
- [Caddy setup](docs/caddy.md)
- [Troubleshooting and recovery](docs/troubleshooting.md)
- [Development and validation](docs/development.md)

## Offline demonstration

Generate clearly labeled synthetic results without accessing any disk:

```bash
python3 examples/make_demo.py /tmp/ssdbench-demo
```

Open `/tmp/ssdbench-demo/index.html`. Demo measurements are invented and must not be mixed into actual bench results.

## Validation status

Automated safety, workload, classification, orchestration, and report tests are included. Development validation uses mocks and synthetic evidence; **live Ubuntu/SATA acceptance is still required**. No real drive was tested or erased during project creation. See the development guide for the acceptance checklist.
