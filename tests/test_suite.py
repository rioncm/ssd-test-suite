import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ssdbench.core import validate_disk, workloads, fio_args, health, outcome
from ssdbench.report import save, report, index
from ssdbench.runner import Bench


def disk():
    return {'type':'disk','ro':False,'rota':False,'tran':'sata','serial':'TEST123',
            'size':1000204886016,'maj:min':'8:16','kname':'/dev/sdb','model':'Example SSD',
            'log-sec':512,'mountpoints':[None], 'children':[]}


class Safety(unittest.TestCase):
    def test_unmounted_sata_allowed(self):
        validate_disk(disk(),set(),{})

    def test_rejects_system_results_and_swap_device(self):
        with self.assertRaises(ValueError): validate_disk(disk(),{'8:16'},{})

    def test_rejects_mounted_partition(self):
        d=disk(); d['children']=[{'type':'part','maj:min':'8:17','kname':'sdb1','mountpoints':['/mnt/data']}]
        with self.assertRaises(ValueError): validate_disk(d,set(),{})

    def test_rejects_swap_partition(self):
        d=disk(); d['children']=[{'type':'part','maj:min':'8:17','kname':'sdb1','mountpoints':[]}]
        with self.assertRaises(ValueError): validate_disk(d,{'8:17'},{})

    def test_rejects_active_mapping(self):
        with self.assertRaises(ValueError): validate_disk(disk(),set(),{'/dev/sdb':['dm-0']})

    def test_rejects_missing_identity_wrong_transport_and_partition(self):
        for key,value in [('serial',''),('tran','usb'),('type','part'),('ro',True),('rota',True)]:
            d=disk(); d[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_disk(d,set(),{})


class Workloads(unittest.TestCase):
    def test_screen_never_writes(self):
        jobs=list(workloads({'mode':'screen','seconds':60},disk()['size'],512))
        self.assertTrue(all(j['rw'] in ('read','randread') for _,j in jobs))
        self.assertTrue(all('--readonly' in fio_args('/dev/test',j,'out','log',True) for _,j in jobs))
        self.assertEqual(jobs[0][1]['size'],disk()['size'])

    def test_full_verifies_entire_capacity_before_benchmarks(self):
        jobs=list(workloads({'mode':'full','seconds':60},disk()['size'],512))
        name,job=jobs[0]
        self.assertEqual(name,'integrity')
        self.assertEqual(job['verify'],'crc32c')
        self.assertEqual(job['size']%job['bs'],0)
        self.assertEqual(job['size'],disk()['size'])
        self.assertNotIn('time_based',job)
        self.assertEqual(len(jobs),7)

    def test_4kn_capacity_alignment(self):
        _,job=next(workloads({'mode':'full','seconds':60},4096*10001,4096))
        self.assertEqual(job['bs'],4096)

    def test_rejects_unaligned_capacity(self):
        with self.assertRaises(ValueError): list(workloads({'mode':'full','seconds':60},12345,512))


class Classification(unittest.TestCase):
    def test_incomplete_never_passes(self):
        self.assertEqual(outcome({'failures':[],'reviews':[],'complete':False}),'INCOMPLETE')

    def test_fail_precedes_incomplete(self):
        self.assertEqual(outcome({'failures':['mismatch'],'reviews':[],'complete':False}),'FAIL')

    def test_smart_command_error_is_not_media_failure(self):
        fail,review=health({}, {'smartctl':{'exit_status':2}})
        self.assertFalse(fail); self.assertTrue(review)

    def test_crc_changes_require_review(self):
        a={'smart_status':{'passed':True},'ata_smart_attributes':{'table':[{'id':199,'name':'CRC','raw':{'value':1}}]}}
        fail,review=health({},a)
        self.assertFalse(fail); self.assertTrue(review)

    def test_failed_smart_health(self):
        fail,_=health({}, {'smart_status':{'passed':False}})
        self.assertTrue(fail)


class Reporting(unittest.TestCase):
    def test_report_escapes_metadata_and_builds_relative_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); run=root/'TEST'/'run'; (run/'fio').mkdir(parents=True)
            s={'serial':'<script>alert(1)</script>','model':'A&B','profile':'screen','outcome':'INCOMPLETE',
               'started':'2026-11-03','run_id':'run','complete':False,'failures':[], 'reviews':[], 'stages':[]}
            save(run/'summary.json',s); report(run); index(root)
            content=(run/'report.html').read_text()
            self.assertNotIn('<script>',content)
            self.assertIn('&lt;script&gt;',content)
            self.assertIn('TEST/run/report.html',(root/'index.html').read_text())
            self.assertIn('INCOMPLETE',(root/'index.csv').read_text())


class SelfTests(unittest.TestCase):
    def bench(self,tmp):
        from types import SimpleNamespace
        args=SimpleNamespace(device='/dev/disk/by-id/ata-TEST123',results=Path(tmp),profile='screen',selftest_timeout=1,max_temperature=70)
        run=Path(tmp)/'TEST123'/'run'; (run/'fio').mkdir(parents=True)
        return Bench(args,disk(),{'mode':'screen','version':'1'},run)

    def test_unsupported_is_review_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            with patch.object(b,'identity'),patch('ssdbench.runner.smart',return_value={}):
                b.selftest('short')
            self.assertEqual(b.s['stages'][0]['status'],'UNSUPPORTED')
            self.assertTrue(b.s['reviews'])

    def test_running_test_does_not_start_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            data={'ata_smart_data':{'self_test':{'status':{'value':249}}}}
            with patch.object(b,'identity'),patch('ssdbench.runner.smart',return_value=data) as sm:
                with self.assertRaises(RuntimeError): b.selftest('short')
                self.assertEqual(sm.call_count,1)

    def test_success_requires_completed_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            initial={'ata_smart_data':{'capabilities':{'self_tests_supported':True}}}
            finish={'smartctl':{'exit_status':0},'ata_smart_data':{'self_test':{'status':{'value':0}}},
                    'ata_smart_self_test_log':{'standard':{'table':[{'type':{'value':1},'status':{'passed':True}}]}}}
            with patch.object(b,'identity'),patch.object(b,'sample'),patch('ssdbench.runner.time.sleep'),patch('ssdbench.runner.smart',side_effect=[initial,{'smartctl':{'exit_status':0}},finish]):
                b.selftest('short')
            self.assertEqual(b.s['stages'][0]['status'],'PASS')

    def test_stale_wrong_test_log_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            initial={'ata_smart_data':{'capabilities':{'self_tests_supported':True}}}
            finish={'smartctl':{'exit_status':0},'ata_smart_data':{'self_test':{'status':{'value':0}}},
                    'ata_smart_self_test_log':{'standard':{'table':[{'type':{'value':2},'status':{'passed':True}}]}}}
            with patch.object(b,'identity'),patch.object(b,'sample'),patch('ssdbench.runner.time.sleep'),patch('ssdbench.runner.smart',side_effect=[initial,{'smartctl':{'exit_status':0}},finish]):
                with self.assertRaises(RuntimeError): b.selftest('short')
            self.assertFalse(b.s['complete'])


class FailurePaths(unittest.TestCase):
    def bench(self,tmp,mode='screen'):
        from types import SimpleNamespace
        args=SimpleNamespace(device='/dev/disk/by-id/ata-TEST123',results=Path(tmp),profile=mode,selftest_timeout=1,max_temperature=70)
        run=Path(tmp)/'TEST123'/'run'; (run/'fio').mkdir(parents=True)
        return Bench(args,disk(),{'mode':mode,'version':'1','seconds':60,'idle_seconds':0},run)

    def test_storage_pool_signatures_rejected(self):
        for signature in ('zfs_member','btrfs','linux_raid_member','LVM2_member','bcache','ceph_bluestore'):
            d=disk(); d['fstype']=signature
            with self.subTest(signature=signature),self.assertRaises(ValueError): validate_disk(d,set(),{})

    def test_same_stale_log_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            data={'smartctl':{'exit_status':0},'ata_smart_data':{'capabilities':{'self_tests_supported':True},'self_test':{'status':{'value':0}}},
                    'ata_smart_self_test_log':{'standard':{'table':[{'type':{'value':1},'status':{'passed':True}}]}}}
            with patch.object(b,'identity'),patch.object(b,'sample'),patch('ssdbench.runner.time.sleep'),patch('ssdbench.runner.smart',side_effect=[data,{'smartctl':{'exit_status':0}},data]):
                with self.assertRaises(RuntimeError): b.selftest('short')
            self.assertFalse(b.s['complete'])

    def run_fio_fixture(self,b,job,code=0):
        from unittest.mock import Mock
        save(b.run/'fio/integrity.json',{'jobs':[job]})
        proc=Mock();proc.poll.return_value=code;proc.returncode=code
        with patch.object(b,'identity'),patch('ssdbench.runner.subprocess.Popen',return_value=proc):
            b.fio('integrity',{'rw':'read'})

    def test_short_read_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            with self.assertRaises(RuntimeError): self.run_fio_fixture(b,{'error':0,'read':{'io_bytes':512}})
            self.assertFalse(b.s['complete'])

    def test_mismatch_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp,'full')
            with self.assertRaises(RuntimeError): self.run_fio_fixture(b,{'error':84},1)
            self.assertEqual(outcome(b.s),'FAIL')

    def test_io_error_is_incomplete_not_false_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            with self.assertRaises(RuntimeError): self.run_fio_fixture(b,{'error':5},1)
            self.assertEqual(outcome(b.s),'INCOMPLETE');self.assertTrue(b.s['reviews'])

    def test_full_requires_read_and_write_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp,'full')
            with self.assertRaises(RuntimeError):
                self.run_fio_fixture(b,{'error':0,'read':{'io_bytes':disk()['size']},'write':{'io_bytes':512}})

    def test_complete_mocked_run_finalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            data={'serial_number':'TEST123','smartctl':{'exit_status':0},'smart_status':{'passed':True}}
            def sample(force=False):
                with (b.run/'temperature.csv').open('a') as f: f.write('1,35\n')
            with patch('ssdbench.runner.smart',return_value=data),patch.object(b,'sample',side_effect=sample),patch.object(b,'selftest'),patch.object(b,'fio'),patch('ssdbench.runner.time.sleep'),patch('ssdbench.runner.command',return_value=(0,'-- No entries --','')):
                self.assertEqual(b.execute(),0)
            self.assertEqual(json.loads((b.run/'summary.json').read_text())['outcome'],'PASS')

    def test_interrupt_finalizes_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            data={'serial_number':'TEST123','smartctl':{'exit_status':0},'smart_status':{'passed':True}}
            with patch('ssdbench.runner.smart',return_value=data),patch.object(b,'sample'),patch.object(b,'selftest',side_effect=KeyboardInterrupt),patch.object(b,'stop') as stop,patch('ssdbench.runner.command',return_value=(0,'','')):
                self.assertEqual(b.execute(),4)
            stop.assert_called_once()
            self.assertTrue((b.run/'report.html').exists())
            self.assertFalse(json.loads((b.run/'summary.json').read_text())['complete'])

    def test_temperature_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.bench(tmp)
            (b.run/'temperature.csv').write_text('epoch,celsius\n')
            with patch('ssdbench.runner.smart',return_value={'temperature':{'current':70}}):
                with self.assertRaises(RuntimeError): b.sample(force=True)
            self.assertTrue(b.s['reviews'])

if __name__=='__main__': unittest.main()
