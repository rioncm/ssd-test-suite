# Troubleshooting

## Target rejected

Use `ssdbench list` and select a whole-disk `/dev/disk/by-id/ata-...` ID. The first version intentionally rejects USB/NVMe and disks without a serial or SSD rotational classification. Do not bypass this by changing the code's safety checks.

A mounted partition, active swap, LVM/RAID/device-mapper holder, or results filesystem on the target prevents testing. Inspect `lsblk` and your storage configuration. The runner never automatically unmounts, stops arrays, disables swap, or tears down mappings. Resolve usage deliberately and rerun `plan`.

Storage-member signatures (ZFS, Btrfs, Linux RAID, LVM, bcache, Ceph) are rejected even when apparently inactive, because some pools do not expose ordinary kernel holders. Any decommissioning and metadata removal must be done separately after verifying the device is no longer in use.

Both profiles require unused disks, including read-only screening. A disk with unavailable system usage evidence fails preflight rather than being assumed safe.

## Older suite reports `swapon: unrecognized option --json`

Update to version 0.1.1 or later and rerun the same command. The runner now reads the kernel inventory at `/proc/swaps` directly; no package upgrade or swap deactivation is needed. Check the installed project version with `ssdbench --version`.

## SMART problems

Raw SMART command return codes are bitmasks, not ordinary success/failure codes. The runner distinguishes low-bit command errors from health/log findings. Inspect the saved JSON `smartctl` section.

Unsupported self-tests produce REVIEW after the I/O stages complete. A self-test already running prevents a new run. An accepted test that aborts, times out, or cannot prove completion produces INCOMPLETE. If a test is interrupted by the runner, it requests `smartctl -X`; inspect `smart-abort.json` if present.

No automatic SMART enablement, drive database update, or firmware alteration is performed. Resolve unsupported access or configuration outside an active run.

## Stop or disconnect

Ctrl+C or SIGTERM stops fio and requests cancellation of a suite-started SMART self-test, then attempts to save final SMART and reports. SSH disconnects are best avoided with tmux. SIGKILL, power loss, process crashes, or a full results filesystem can prevent final capture; the last checkpoint remains incomplete. fio is started in its own process group, so SIGKILL of the Python process alone can leave fio running. Check processes before attempting another run.

There is no resume feature. Preserve the incomplete evidence and start a new run after resolving the cause. The station lock prevents concurrent suite runners; it does not prevent unrelated disk tools.

## fio error or stalled drive

Inspect the stage's `.stderr.txt`, `.stdout.txt`, and `.json`, plus `kernel.log`. A verified EILSEQ mismatch is FAIL. Other fio errors stop the suite as INCOMPLETE with a review finding; these can be configuration, kernel, connection, or media errors. Missing/malformed output also cannot pass. A kernel task stuck in uninterruptible I/O may not respond immediately even to termination signals.

## Temperature

The default stop threshold is 70 °C, an operator policy rather than a universal specification. Consult the drive's rated operating range. Use `--max-temperature N` to set a suitable threshold. Missing readings are retained as blanks and require review. Sampling is periodic, not a hardware protection mechanism.

## Reports

Rebuild with `ssdbench report --results PATH` when no run is active. A failed rebuild cannot establish that a run passed: inspect its summary and original logs. JSON/HTML files use atomic replacement at checkpoints, but the entire result directory is not a transactional snapshot.
