"""Pure validation, workload construction, and result classification."""
import re

VERSION = '0.2.0'


def walk(node):
    yield node
    for child in node.get('children', []):
        yield from walk(child)


def validate_disk(node, busy_ids, holders):
    if node.get('type') != 'disk' or node.get('ro') or node.get('rota'):
        raise ValueError('Target must be a writable, non-rotating whole disk.')
    if node.get('tran') != 'sata':
        raise ValueError('Version 1 supports direct SATA/eSATA SSDs only.')
    if not str(node.get('serial') or '').strip():
        raise ValueError('Target has no serial number.')
    for item in walk(node):
        if item.get('fstype') in ('zfs_member', 'btrfs', 'linux_raid_member', 'LVM2_member', 'bcache', 'ceph_bluestore'):
            raise ValueError('Storage pool/member signature requires separate operator review and removal before testing.')
        if any(item.get('mountpoints') or []) or item['maj:min'] in busy_ids:
            raise ValueError('Target or descendant is mounted, swap, or backs the results filesystem.')
        if item.get('type') not in ('disk', 'part') or holders.get(item['kname']):
            raise ValueError('Target has an active storage mapping/holder.')
    if int(node['size']) <= 0:
        raise ValueError('Invalid capacity.')


def workloads(profile, capacity, sector):
    if capacity % sector:
        raise ValueError('Capacity is not aligned to logical sectors.')
    # Use a divisor of capacity: no unverified tail sectors.
    block = 1048576
    while capacity % block or block < sector:
        block //= 2
        if block < sector:
            block = sector
            break
    full = profile['mode'] == 'full'
    yield 'integrity', dict(rw='write' if full else 'read', bs=block,
                           size=capacity, iodepth=32,
                           **({'verify': 'crc32c', 'do_verify': 1, 'verify_fatal': 1,
                               'verify_dump': 0, 'end_fsync': 1} if full else {}))
    for rw in (['read', 'write', 'randread', 'randwrite'] if full else ['read', 'randread']):
        for depth in ([1, 32] if rw.startswith('rand') else [32]):
            bs = 4096 if rw.startswith('rand') else 1048576
            size = capacity // bs * bs
            yield f'{rw}-qd{depth}', dict(rw=rw, bs=bs, size=size, iodepth=depth,
                                         time_based=1, runtime=profile['seconds'])


def fio_args(device, options, output, prefix, readonly=False):
    base = ['fio', '--name=ssdbench', f'--filename={device}', '--ioengine=libaio',
            '--direct=1', '--numjobs=1', '--thread=1', '--group_reporting=1',
            '--allow_file_create=0', '--verify_state_save=0', '--refill_buffers=1', '--randrepeat=1', '--randseed=20261103',
            '--lat_percentiles=1', '--percentile_list=50:95:99:99.9',
            '--output-format=json', f'--output={output}',
            f'--write_bw_log={prefix}', '--log_avg_msec=1000', '--log_unix_epoch=1']
    if readonly:
        base.append('--readonly')
    return base + [f'--{key}={value}' for key, value in options.items()]


def attributes(smart):
    return {str(a['id']): a for a in smart.get('ata_smart_attributes', {}).get('table', [])}


def health(before, after):
    fail, review = [], []
    if after.get('smart_status', {}).get('passed') is False:
        fail.append('Drive reports SMART health failure.')
    elif after.get('smart_status', {}).get('passed') is not True:
        review.append('SMART overall health unavailable.')
    old, new = attributes(before), attributes(after)
    for key, attr in new.items():
        if attr.get('when_failed') not in (None, '', '-'):
            review.append(f"SMART attribute {key} has a threshold failure: {attr.get('name')}.")
        if key in ('5', '187', '197', '198', '199'):
            value = attr.get('raw', {}).get('value')
            prior = old.get(key, {}).get('raw', {}).get('value')
            if isinstance(value, int) and value > 0:
                review.append(f"SMART {key} {attr.get('name')}: {prior} → {value}; interpret for this model.")
    code = after.get('smartctl', {}).get('exit_status', 0)
    if code & 0b111:
        review.append('SMART command/access error; evidence may be incomplete.')
    if code & 0b11110000:
        review.append('SMART reports historical threshold, error-log, or self-test findings.')
    return fail, review


def outcome(summary):
    if summary['failures']:
        return 'FAIL'
    if not summary.get('complete'):
        return 'INCOMPLETE'
    return 'REVIEW' if summary['reviews'] else 'PASS'


def slug(value):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', value)[:100] or 'unknown'
