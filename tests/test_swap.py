"""Regression checks for swap detection on util-linux without swapon JSON."""
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ssdbench.runner import active_swap_ids
from ssdbench.core import validate_disk

HEADER = b'Filename\t\t\tType\tSize\tUsed\tPriority\n'


class SwapInventory(unittest.TestCase):
    def test_no_active_swap(self):
        with patch.object(Path, 'read_bytes', return_value=HEADER):
            self.assertEqual(active_swap_ids(), set())

    def test_swap_partition_blocks_target(self):
        fixture = HEADER + b'/dev/sdb1 partition 1048572 0 -2\n'
        info = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 17))
        with patch.object(Path, 'read_bytes', return_value=fixture), patch.object(Path, 'stat', return_value=info):
            busy = active_swap_ids()
        disk = {'type':'disk', 'tran':'sata', 'serial':'TEST', 'size':1000000,
                'maj:min':'8:16', 'kname':'sdb', 'children':[
                    {'type':'part', 'maj:min':'8:17', 'kname':'sdb1'}]}
        with self.assertRaisesRegex(ValueError, 'swap'):
            validate_disk(disk, busy, {})

    def test_swap_file_uses_backing_filesystem_device(self):
        fixture = HEADER + b'/swapfile file 1048572 0 -2\n'
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=os.makedev(8, 2), st_rdev=0)
        with patch.object(Path, 'read_bytes', return_value=fixture), patch.object(Path, 'stat', return_value=info):
            self.assertEqual(active_swap_ids(), {'8:2'})

    def test_escaped_space_and_literal_backslash_decode_once(self):
        fixture = HEADER + rb'/swap\040dir/name\134040 file 1048572 0 -2' + b'\n'
        paths = []
        def get_stat(path):
            paths.append(str(path))
            return SimpleNamespace(st_mode=stat.S_IFREG, st_dev=os.makedev(8, 2))
        with patch.object(Path, 'read_bytes', return_value=fixture), patch.object(Path, 'stat', get_stat):
            active_swap_ids()
        self.assertEqual(paths, ['/swap dir/name\\040'])

    def test_malformed_inventory_fails_closed(self):
        for fixture in (b'', b'Unexpected header\n', HEADER+b'/swapfile file\n'):
            with self.subTest(fixture=fixture), patch.object(Path, 'read_bytes', return_value=fixture):
                with self.assertRaises(ValueError): active_swap_ids()

    def test_unreadable_inventory_fails_closed(self):
        with patch.object(Path, 'read_bytes', side_effect=PermissionError):
            with self.assertRaises(PermissionError): active_swap_ids()

    def test_missing_swap_path_fails_closed(self):
        with patch.object(Path, 'read_bytes', return_value=HEADER+b'/swapfile file 1000 0 -2\n'), patch.object(Path, 'stat', side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError): active_swap_ids()


if __name__ == '__main__':
    unittest.main()
