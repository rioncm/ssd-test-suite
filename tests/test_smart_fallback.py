"""Regression for usable ATA SMART data accompanied by extended-query bit 2."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ssdbench.runner import Bench, smart


def snapshot(code=0):
    # Reduced, anonymized shape from the Micron report that exposed the bug.
    return {'smartctl':{'exit_status':code}, 'serial_number':'TEST123',
            'smart_status':{'passed':True}, 'temperature':{'current':39},
            'ata_smart_data':{'capabilities':{'self_tests_supported':True}},
            'ata_smart_attributes':{'table':[{'id':5,'name':'Reallocate_NAND_Blk_Cnt',
                                            'raw':{'value':0,'string':'0'}}]}}


class SmartFallback(unittest.TestCase):
    def bench(self, root):
        run=Path(root)/'TEST123'/'run'; (run/'fio').mkdir(parents=True)
        (run/'temperature.csv').write_text('epoch,celsius\n')
        args=SimpleNamespace(device='/dev/disk/by-id/ata-TEST123',results=Path(root),
                             profile='screen',max_temperature=70)
        node={'serial':'TEST123','model':'Test SSD','size':1048576,'log-sec':512}
        return Bench(args,node,{'version':'1','mode':'screen','seconds':60,'idle_seconds':0},run)

    def test_bit2_falls_back_preserves_raw_and_temperature(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root)
            with patch('ssdbench.runner.smart',side_effect=[snapshot(4),snapshot()]) as read:
                selected=b.snapshot('before')
            self.assertEqual(read.call_args_list[1].args[1:],('-i','-H','-A','-c'))
            self.assertEqual(selected['smartctl']['exit_status'],0)
            self.assertEqual(json.loads((b.run/'smart-before-extended.json').read_text())['smartctl']['exit_status'],4)
            self.assertIn(',39', (b.run/'temperature.csv').read_text())
            self.assertTrue(any('essential SMART query succeeded' in r for r in b.s['reviews']))

    def test_open_failure_never_falls_back(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root)
            with patch('ssdbench.runner.smart',return_value=snapshot(2)) as read:
                with self.assertRaisesRegex(RuntimeError,'device-open'): b.snapshot('before')
            self.assertEqual(read.call_count,1)

    def test_core_query_failure_still_stops(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root)
            with patch('ssdbench.runner.smart',side_effect=[snapshot(4),snapshot(4)]):
                with self.assertRaisesRegex(RuntimeError,'essential SMART query failed'): b.snapshot('before')
            self.assertTrue((b.run/'smart-before-core.json').exists())

    def test_core_missing_data_still_stops(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root); core=snapshot(); del core['ata_smart_attributes']
            with patch('ssdbench.runner.smart',side_effect=[snapshot(4),core]):
                with self.assertRaisesRegex(RuntimeError,'data incomplete'): b.snapshot('before')

    def test_core_wrong_serial_still_stops(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root); core=snapshot(); core['serial_number']='OTHER'
            with patch('ssdbench.runner.smart',side_effect=[snapshot(4),core]):
                with self.assertRaisesRegex(RuntimeError,'serial'): b.snapshot('before')

    def test_extended_wrong_serial_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root); extended=snapshot(4); extended['serial_number']='OTHER'
            with patch('ssdbench.runner.smart',return_value=extended) as read:
                with self.assertRaisesRegex(RuntimeError,'serial'): b.snapshot('before')
            self.assertEqual(read.call_count,1)

    def test_health_failure_is_retained_across_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root); extended=snapshot(12); extended['smart_status']['passed']=False
            with patch('ssdbench.runner.smart',side_effect=[extended,snapshot()]):
                b.snapshot('before')
            self.assertTrue(b.s['failures'])

    def test_full_orchestration_continues_with_review(self):
        with tempfile.TemporaryDirectory() as root:
            b=self.bench(root)
            with patch('ssdbench.runner.smart',side_effect=[snapshot(4),snapshot(),snapshot(4),snapshot()]),patch.object(b,'sample'),patch.object(b,'selftest'),patch.object(b,'fio') as fio,patch('ssdbench.runner.time.sleep'),patch('ssdbench.runner.command',return_value=(0,'','')):
                self.assertEqual(b.execute(),2)
            self.assertTrue(b.s['complete'])
            self.assertEqual(fio.call_count,4)
            self.assertFalse(any('temperature' in r.lower() for r in b.s['reviews']))

    def test_plaintext_and_stderr_are_retained(self):
        data=snapshot(4); data['smartctl']['output']=['An extended query failed']
        with patch('ssdbench.runner.command',return_value=(4,json.dumps(data),'diagnostic')) as command:
            result=smart('/dev/example','-x')
        self.assertIn('--json=o',command.call_args.args[0])
        self.assertEqual(result['ssdbench_stderr'],'diagnostic')
        self.assertEqual(result['smartctl']['output'],data['smartctl']['output'])


if __name__=='__main__': unittest.main()
