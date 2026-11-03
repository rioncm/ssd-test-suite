# Reports and retained evidence

Store results on a separate internal or network filesystem, never on the drive under test. Each run creates a new serial/timestamp/profile/UUID directory. Runs are not resumed or overwritten by a new test. Reports update at stage boundaries; refresh the browser to see progress. While running, the outcome is INCOMPLETE and the active stage says RUNNING.

```text
/srv/ssd-results/
  index.html
  index.csv
  SERIAL/
    TIMESTAMP_PROFILE_UNIQUEID/
      report.html
      summary.json
      manifest.json
      smart-before.json
      smart-after.json
      smart-short-start.json
      smart-short-result.json
      smart-long-start.json
      smart-long-result.json
      temperature.csv
      kernel.log
      fio/
        integrity.command.json
        integrity.json
        integrity.stderr.txt
        integrity.stdout.txt
        integrity_bw.1.log
        ...
```

Extended-query fallback adds `smart-before-extended.json` and `smart-before-core.json` (and corresponding after files), preserving both attempts. Selected successful snapshots remain in the canonical before/after files. SMART JSON includes original plaintext in `smartctl.output` for diagnosing errors that structured fields do not identify.

Files for stages that did not start will be absent. Self-test result files contain the most recent poll, not every poll. `summary.json` is authoritative for completion and stage status; a partial fio JSON file alone is not a passing test.

## HTML and CSV

The catalog links to reports and contains one CSV row per run, including serial, model, profile, outcome, capacity, and relative report path. CSV does not flatten every performance metric; those remain in per-run fio JSON and report tables.

HTML is self-contained, escapes device metadata, and uses inline SVG charts without JavaScript or external assets. Charts may downsample displayed points; full-resolution logs remain available. The chart peak is the maximum observed sample, not proof of the drive's true instantaneous peak. Bandwidth logs use fio's KiB/s units, converted to MiB/s. Temperature is in °C; timestamps are UTC/Unix epoch.

Evidence includes drive serials, model/firmware, command paths, and kernel messages from all devices during the interval. Treat reports as internal operational data. Kernel errors from another drive can trigger REVIEW; attribution is deliberately left to the operator.

## Health interpretation

SMART health failure is FAIL. Current/historical threshold findings, nonzero monitored raw attributes (5, 187, 197, 198, 199), and historical error/self-test flags require review. These raw attributes are vendor-specific, so the suite does not automatically convert them into bad-block counts or remaining-life percentages. The report shows all available attributes before/after for manual interpretation, including vendor wear counters.

A CRC/link finding is not automatically a failed SSD. Check the cable, power, and controller and repeat with a known-good path. Slow performance alone never causes FAIL. Unknown/missing health data cannot yield a clean PASS.

## Rebuild

```bash
ssdbench report --results /srv/ssd-results
```

This regenerates HTML and CSV from existing evidence without accessing disks or changing verdicts. Use an account with write permission to the result directory; results created by the runner are normally root-owned. Run rebuilds only when no test is writing to the same tree.

If a process was forcibly killed, a stage may still say RUNNING, but the run remains INCOMPLETE. Preserve it and start a fresh run; do not manually change its verdict to PASS.

Back up the entire result tree. There is no automatic retention deletion or upload. Do not add symlinks in a served result tree; Caddy's filesystem root is not a symlink sandbox.
