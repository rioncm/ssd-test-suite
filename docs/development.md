# Development and validation

## Layout

- `ssdbench/core.py`: pure safety validation, generated fio workloads, health/outcome policy.
- `ssdbench/runner.py`: Linux inventory, subprocess orchestration, monitoring, cancellation, and checkpoints.
- `ssdbench/report.py`: HTML/SVG reports, atomic JSON/HTML writes, and CSV catalog.
- `profiles/*.json`: versioned workload policy.
- `tests/`: offline unit and mocked orchestration tests; no block-device writes.
- `examples/make_demo.py`: synthetic presentation fixture.

Run from the project root:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q ssdbench examples tests
python3 -m ssdbench --help
python3 examples/make_demo.py /tmp/ssdbench-demo
```

The suite needs no third-party Python libraries. Runtime requires Linux, util-linux (`lsblk`, `findmnt`, `swapon`), smartmontools, fio, and systemd journal access. Static reports can be regenerated on macOS/Linux. Disk operations are explicitly rejected off Linux.

## Design boundaries

The CLI never accepts an arbitrary fio job or runs a shell command assembled from drive metadata. Generated commands are persisted as JSON arrays. A root-owned station lock serializes suite runs. Stable IDs, serial/capacity/device-number rechecks, mounted/swap/holder checks, and explicit destructive authorization reduce wrong-device risk. They do not protect against an administrator or automounter changing storage concurrently between checks.

The profile files and Python sources are executable policy: keep them in a trusted directory and do not run unreviewed edits as root. The suite is a local administrator tool, not a multi-user privileged service.

Reports are generated at checkpoints. A hard kill can leave incomplete artifacts; the recorded outcome remains INCOMPLETE. No resumption or automatic PASS recovery is implemented. Reports do not establish secure erasure, retention life, power-loss behavior, or industry certification.

## Live acceptance before routine use

Development tests cannot validate a particular controller, firmware, or real fio behavior. On Ubuntu, use a sacrificial SATA SSD:

1. Verify `list` and `plan` identify the expected disk. Confirm the running system disk, a mounted test partition, and an active-swap target are rejected before any workload starts. Use disposable fixtures when setting up these cases.
2. Run `screen`. Confirm fio receives `--readonly`, full-capacity read bytes equal capacity, supported SMART tests actually complete, and temperature is captured when available.
3. Run `full` only with explicit approval to erase that SSD. Check integrity read and write coverage, verification success, and all six timed benchmarks.
4. Cancel a run with Ctrl+C. Confirm fio stops, any active suite-started self-test is aborted, and the report remains INCOMPLETE.
5. Inspect before/after SMART and kernel messages. Check latency units against raw fio JSON and bandwidth units against logs.
6. Serve the tree with Caddy, validate its configuration, and confirm index, report, charts, and evidence links work without write access for Caddy.
7. Archive a known-good baseline under the unchanged profile version.

Do not claim live acceptance from the synthetic demo or mocked tests. Record the drive model, firmware, host environment, date, and actual results when acceptance is performed.

## Project creation checks

- 29 offline tests passed on Python 3.15.0 on macOS.
- Python compilation and CLI help checks passed.
- Synthetic HTML/CSV generation and report regeneration passed.
- All 11 generated demo catalog/report links resolved to existing local files.
- Browser visual inspection was not completed: the browser tool rejected local `file:` URLs.
- Caddy is not installed in the development environment; live configuration validation remains part of deployment.
- No live Ubuntu/SATA or destructive hardware test was performed.
