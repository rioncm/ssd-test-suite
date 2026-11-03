# Methodology

## Stage order

1. Validate a whole SATA SSD by stable ID and inspect active use.
2. Record baseline SMART, drive identity, tool/kernel versions, profile, and source hashes.
3. Run SMART short, then extended self-test. Poll at ten-second intervals until the device reports completion. Check the newest log entry and evidence of progress or a changed log; estimated time alone never means success.
4. Run one full-capacity integrity workload.
5. Run sequential read (and write in full mode), random read QD1/QD32, and random write QD1/QD32 in full mode.
6. Capture final SMART and the run's kernel-log interval; write final summaries and the catalog.

Unsupported SMART self-tests are explicitly recorded and force REVIEW if the remaining run completes. A command failure or unverified self-test completion stops the run. Pre-existing active self-tests are not replaced.

## Integrity

`screen` reads every addressable byte once. It detects host-visible read errors but does not verify pre-existing file contents.

`full` performs a sequential full-capacity write with fio CRC32C verification headers, then reads and verifies the written data in the same fio job before any benchmark overwrites it. The job is size-limited, not time-limited. The block size is the largest power-of-two divisor of capacity up to 1 MiB, never below the logical sector size. This covers tail sectors rather than rounding the integrity region down. The runner requires the fio read byte count—and write byte count in full mode—to equal capacity exactly.

No TRIM, secure erase, firmware changes, or cache settings are applied. A write-stage flush is requested. This does not test power-loss protection or long-term retention. Data verification reports throughput that includes checksum and buffer-generation costs; it is not directly interchangeable with a pure sequential benchmark.

## Performance

Profiles are versioned JSON in `ssdbench/profiles/`. Both use Linux libaio, direct I/O, one job, a fixed random seed, and a ten-second idle interval after each fio workload. Each timed workload runs for sixty seconds with no excluded warm-up interval.

| Workload | Block size | Queue depth | Profiles |
|---|---|---|---|
| Sequential read | 1 MiB | 32 | screen, full |
| Sequential write | 1 MiB | 32 | full |
| Random read | 4 KiB | 1 and 32 | screen, full |
| Random write | 4 KiB | 1 and 32 | full |

Benchmarks use the largest whole-block-aligned region fitting the drive. Unlike integrity testing, they can omit a final partial block. The recorded command identifies that region. Time-limited random tests are samples, not full-coverage scans. Writes use refilled buffers to reduce repeated-buffer compression effects.

Total latency percentiles include submission plus completion latency. Actual achieved queue depth is available in the fio JSON. A requested QD32 is not proof that depth was maintained.

These are practical bounded measurements, not an SNIA steady-state certification. SSD cache size, previous contents, internal garbage collection, temperature, link speed, and drive firmware affect results. Full qualification changes the device's fill state. Do not compare screen and full runs as equivalent conditions. Establish a known-good baseline for the same connection and profile.

## Limits and duration

Temperature is sampled approximately every thirty seconds, including during fio (the SMART query introduces small monitoring overhead). The default stop threshold is 70 °C; select a threshold appropriate to the drive vendor with `--max-temperature`. Missing temperature data forces REVIEW but does not stop testing. A limit crossing stops testing and leaves INCOMPLETE, unless an independent failure was already established.

`--selftest-timeout` defaults to 720 minutes per SMART test. A timed-out test is aborted and the run remains incomplete. fio has no overall wall-time deadline: a large or slow drive can require hours. Ctrl+C requests orderly cancellation.

At 400 MB/s, a 1 TB write plus read has a theoretical I/O floor of roughly 83 minutes, before self-tests, cache slowdown, and other overhead. The six performance jobs add roughly seven minutes including idle intervals. Actual duration can be much longer.

For an installed copy, edit profiles in the source checkout and reinstall the package before testing. Editing a profile changes comparability. Increment its version and archive the old file. Every run saves the profile, exact generated commands, and SHA-256 hashes of source/profile files. Never edit settings during an active run.

## References

- [fio documentation](https://fio.readthedocs.io/en/latest/fio_doc.html): verification, direct I/O, workload parameters, JSON and bandwidth logs.
- [Ubuntu 24.04 smartctl manual](https://manpages.ubuntu.com/manpages/noble/man8/smartctl.8.html): self-tests and bitmask exit status.
- [smartmontools 7.4 ATA JSON implementation](https://github.com/smartmontools/smartmontools/blob/RELEASE_7_4/smartmontools/ataprint.cpp): self-test status/log fields used by this runner.

Ubuntu's installed `man fio` describes its exact version; upstream documentation may include newer features.
