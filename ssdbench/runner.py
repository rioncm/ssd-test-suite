"""Linux-only SATA bench orchestration. No shell evaluation of drive metadata."""
import argparse
import csv
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import time
import uuid

from .core import VERSION, validate_disk, workloads, fio_args, health, outcome, slug, walk
from .report import save, report, index
from .resources import load_profile, source_hashes


def command(args, timeout=60):
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def required(args):
    code, out, err = command(args)
    if code:
        raise RuntimeError(f'{args[0]} failed ({code}): {err.strip()}')
    return out


def smart(device, *options):
    code, out, err = command(['smartctl', '--json=o', *options, device])
    try:
        data = json.loads(out)
    except ValueError as exc:
        raise RuntimeError(f'smartctl returned no JSON: {err or out}') from exc
    data.setdefault('smartctl', {})['exit_status'] = code
    if err:
        data['ssdbench_stderr'] = err
    return data


def active_swap_ids():
    """Read kernel swap inventory without relying on swapon output options.

    /proc paths use octal escapes. Decode once, preserving filesystem bytes.
    An unreadable inventory or unresolvable entry must stop preflight.
    """
    lines = Path('/proc/swaps').read_bytes().splitlines()
    if not lines or lines[0].split() != [b'Filename', b'Type', b'Size', b'Used', b'Priority']:
        raise ValueError('Cannot validate /proc/swaps header.')
    busy = set()
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 5 or fields[1] not in (b'file', b'partition'):
            raise ValueError('Cannot parse active swap entry in /proc/swaps.')
        raw_path = re.sub(rb'\\([0-7]{3})', lambda m: bytes([int(m[1], 8)]), fields[0])
        path = Path(os.fsdecode(raw_path))
        if not path.is_absolute():
            raise ValueError('Active swap path is not absolute.')
        st = path.stat()
        if not (stat.S_ISBLK(st.st_mode) or stat.S_ISREG(st.st_mode)):
            raise ValueError(f'Unexpected active swap file type: {path}')
        number = st.st_rdev if stat.S_ISBLK(st.st_mode) else st.st_dev
        busy.add(f'{os.major(number)}:{os.minor(number)}')
    return busy


def inspect(device, root):
    if not device.startswith('/dev/disk/by-id/') or Path(device).parent != Path('/dev/disk/by-id'):
        raise ValueError('Use a whole-disk /dev/disk/by-id/ path.')
    resolved = Path(device).resolve(strict=True)
    if not stat.S_ISBLK(resolved.stat().st_mode):
        raise ValueError('Not a block device.')
    data=json.loads(required(['lsblk','--json','--bytes','--paths','--output',
        'NAME,KNAME,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,RO,MOUNTPOINTS,MAJ:MIN,LOG-SEC,FSTYPE']))
    nodes=[x for top in data['blockdevices'] for x in walk(top) if x['name']==str(resolved)]
    if not nodes:
        raise ValueError('Device missing from lsblk.')
    node=nodes[0]
    # All mounted devices, including root and the results destination. lsblk supplies descendants.
    mounts=json.loads(required(['findmnt','--json','--output','MAJ:MIN']))
    busy={x['maj:min'] for top in mounts.get('filesystems',[]) for x in walk(top)}
    busy.update(active_swap_ids())
    dest=root.resolve()
    while not dest.exists(): dest=dest.parent
    dev=dest.stat().st_dev
    busy.add(f'{os.major(dev)}:{os.minor(dev)}')
    holders={}
    for item in walk(node):
        key=Path(item['kname']).name
        h=Path('/sys/class/block')/key/'holders'
        if not h.is_dir(): raise ValueError(f'Cannot inspect holders for {key}.')
        holders[item['kname']]=list(h.iterdir())
    validate_disk(node,busy,holders)
    return node


class Bench:
    def __init__(self, args, node, profile, run):
        self.args,self.node,self.profile,self.run=args,node,profile,run
        self.proc=None
        self.selftest_active=False
        self.s={'run_id':run.name,'serial':node['serial'].strip(),'model':node['model'],
                'capacity_bytes':int(node['size']),'device':args.device,'profile':args.profile,
                'suite_version':VERSION,'profile_version':profile['version'],
                'started':dt.datetime.now(dt.timezone.utc).isoformat(),'started_epoch':time.time(),
                'complete':False,'stages':[],'failures':[],'reviews':[],'notes':[]}
        self.last_temperature=0
        self.before={}

    def checkpoint(self):
        self.s['outcome']=outcome(self.s)
        save(self.run/'summary.json',self.s)
        report(self.run)
        index(self.args.results)

    def stage(self,name,status,detail=''):
        self.s['stages']=[x for x in self.s['stages'] if x['name']!=name]
        self.s['stages'].append(dict(name=name,status=status,detail=detail))
        print(f'{name}: {status} {detail}',flush=True)
        self.checkpoint()

    def identity(self):
        node=inspect(self.args.device,self.args.results)
        if (node['serial'].strip(),node['size'],node['maj:min']) != (self.node['serial'].strip(),self.node['size'],self.node['maj:min']):
            raise RuntimeError('Target identity changed; stopped.')

    def sample(self, force=False):
        if not force and time.monotonic()-self.last_temperature<30: return
        data=smart(self.args.device,'-A')
        self.last_temperature=time.monotonic()
        self.record_temperature(data)

    def record_temperature(self, data, enforce=True):
        temp=data.get('temperature',{}).get('current')
        with (self.run/'temperature.csv').open('a') as f:
            csv.writer(f).writerow([time.time(),temp if temp is not None else ''])
        if enforce and temp is not None and temp>=self.args.max_temperature:
            self.s['reviews'].append(f'Temperature {temp} °C reached configured stop limit {self.args.max_temperature} °C.')
            raise RuntimeError('Temperature limit reached.')

    def snapshot(self, label):
        """Keep extended evidence; independently verify essential data on bit 2."""
        data=smart(self.args.device,'-x')
        save(self.run/f'smart-{label}.json',data)
        # Keep known health findings even if a separate query also failed.
        failures,reviews=health(self.before,data)
        self.s['failures']+=failures
        self.s['reviews']+=reviews
        self.record_temperature(data,enforce=label=='before')
        code=data['smartctl']['exit_status']
        if code & 3:
            raise RuntimeError(f'{label} SMART invocation/device-open failed (status {code}).')
        serial=data.get('serial_number','').strip()
        if serial and serial!=self.s['serial']:
            raise RuntimeError('SMART serial does not match lsblk serial.')
        if code & 4:
            save(self.run/f'smart-{label}-extended.json',data)
            data=smart(self.args.device,'-i','-H','-A','-c')
            save(self.run/f'smart-{label}-core.json',data)
            failures,reviews=health(self.before,data)
            self.s['failures']+=failures
            self.s['reviews']+=reviews
            self.record_temperature(data,enforce=label=='before')
            if data['smartctl']['exit_status'] & 7:
                raise RuntimeError(f'{label} essential SMART query failed; see smart-{label}-core.json.')
            # Never treat a successful exit with missing data as a usable baseline.
            if (not isinstance(data.get('smart_status',{}).get('passed'),bool)
                    or not data.get('ata_smart_attributes',{}).get('table')
                    or not data.get('ata_smart_data',{})):
                raise RuntimeError(f'{label} essential SMART data incomplete; see smart-{label}-core.json.')
            self.s['reviews'].append(f'{label}: extended SMART query returned bit 2; essential SMART query succeeded. Extended evidence remains incomplete.')
        if data.get('serial_number','').strip()!=self.s['serial']:
            raise RuntimeError('SMART serial does not match lsblk serial.')
        # Canonical snapshot is the selected successful query; raw attempts remain separate.
        save(self.run/f'smart-{label}.json',data)
        return data

    def selftest(self, kind):
        self.identity()
        data=smart(self.args.device,'-a')
        tests=data.get('ata_smart_data',{}).get('self_test',{})
        if tests.get('status',{}).get('value',0)>>4==15:
            raise RuntimeError('A self-test is already running; wait for it before starting a suite.')
        supported=data.get('ata_smart_data',{}).get('capabilities',{}).get('self_tests_supported')
        if supported is not True:
            self.s['reviews'].append(f'{kind} self-test support unavailable or unsupported.')
            self.stage('smart-'+kind,'UNSUPPORTED')
            return
        start=smart(self.args.device,'-t',kind)
        save(self.run/f'smart-{kind}-start.json',start)
        if start['smartctl']['exit_status']&7:
            raise RuntimeError(f'Cannot start {kind} self-test.')
        self.selftest_active=True
        self.stage('smart-'+kind,'RUNNING')
        original_log=data.get('ata_smart_self_test_log',{})
        saw_progress=False
        deadline=time.monotonic()+self.args.selftest_timeout*60
        # Poll status, not estimated completion time; wait before first check.
        while time.monotonic()<deadline:
            time.sleep(10)
            self.sample()
            data=smart(self.args.device,'-a')
            save(self.run/f'smart-{kind}-result.json',data)
            if data['smartctl']['exit_status']&7:
                raise RuntimeError('Cannot read self-test progress.')
            status=data.get('ata_smart_data',{}).get('self_test',{}).get('status',{})
            value=status.get('value')
            if value is None: raise RuntimeError('Self-test status unavailable.')
            code=value>>4
            if code==15:
                saw_progress=True
                continue
            self.selftest_active=False
            logs=data.get('ata_smart_self_test_log',{})
            entries=(logs.get('standard',{}).get('table') or logs.get('extended',{}).get('table') or [])
            expected=1 if kind=='short' else 2
            entry=entries[0] if entries else {}
            if code==0 and (saw_progress or logs!=original_log) and entry.get('type',{}).get('value')==expected and entry.get('status',{}).get('passed') is True:
                self.stage('smart-'+kind,'PASS',status.get('string','Completed'))
                return
            if code in (3,4,5,6,7,8):
                self.s['failures'].append(f'{kind} self-test failed: {status.get("string",code)}')
                self.stage('smart-'+kind,'FAIL')
            else:
                self.stage('smart-'+kind,'INCOMPLETE','Completion could not be verified in self-test log.')
            raise RuntimeError('Self-test did not complete successfully.')
        raise RuntimeError('Self-test timed out.')

    def fio(self,name,options):
        self.identity()
        folder=self.run/'fio'
        args=fio_args(str(Path(self.args.device).resolve()),options,folder/f'{name}.json',folder/name,self.profile['mode']=='screen')
        save(folder/f'{name}.command.json',args)
        self.stage(name,'RUNNING')
        with (folder/f'{name}.stderr.txt').open('w') as err, (folder/f'{name}.stdout.txt').open('w') as out:
            self.proc=subprocess.Popen(args,stdout=out,stderr=err,start_new_session=True)
            while self.proc.poll() is None:
                self.sample()
                time.sleep(1)
            code=self.proc.returncode
            self.proc=None
        data=json.loads((folder/f'{name}.json').read_text())
        jobs=data.get('jobs',[])
        if code or not jobs or any(j.get('error',0) for j in jobs):
            # EILSEQ indicates verified data corruption; other errors can be host/configuration faults.
            if any(j.get('error')==84 for j in jobs):
                self.s['failures'].append(f'{name}: verification mismatch (EILSEQ).')
            else:
                self.s['reviews'].append(f'{name}: fio error; inspect JSON and stderr before attributing to the drive.')
            self.stage(name,'ERROR',f'fio exit {code}')
            raise RuntimeError('fio did not complete successfully.')
        if name=='integrity':
            directions=['read','write'] if self.profile['mode']=='full' else ['read']
            for direction in directions:
                total=sum(j.get(direction,{}).get('io_bytes',0) for j in jobs)
                if total!=int(self.node['size']):
                    raise RuntimeError(f'Incomplete {direction} coverage: {total} bytes.')
        self.stage(name,'PASS','Completed without reported errors.')

    def stop(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid,signal.SIGTERM)
            try: self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid,signal.SIGKILL); self.proc.wait()
        if self.selftest_active:
            try: save(self.run/'smart-abort.json',smart(self.args.device,'-X'))
            except Exception as exc: self.s['reviews'].append(f'Could not abort self-test: {exc}')

    def execute(self):
        self.checkpoint()
        (self.run/'temperature.csv').write_text('epoch,celsius\n')
        try:
            self.before=self.snapshot('before')
            failures,reviews=health(self.before,self.before)
            self.s['failures']+=failures
            self.s['reviews']+=reviews
            if self.s['failures']: raise RuntimeError('Baseline SMART health failed; no workload started.')
            self.sample(force=True)
            for kind in ('short','long'): self.selftest(kind)
            for name,options in workloads(self.profile,int(self.node['size']),int(self.node['log-sec'])):
                self.fio(name,options)
                time.sleep(self.profile['idle_seconds'])
            self.s['complete']=True
        except (Exception,KeyboardInterrupt) as exc:
            self.s['notes'].append(f'Stopped: {str(exc) or type(exc).__name__}')
            for stage in self.s['stages']:
                if stage['status']=='RUNNING': stage['status']='INCOMPLETE'
        finally:
            self.stop()
            try:
                after=self.snapshot('after')
                failures,reviews=health(self.before,after)
                self.s['failures']+=failures; self.s['reviews']+=reviews
            except Exception as exc: self.s['reviews'].append(f'Final SMART unavailable: {exc}')
            try:
                code,out,err=command(['journalctl','-k','-b','--since','@'+str(int(self.s['started_epoch'])),'--no-pager','-o','short-iso'])
            except Exception as exc:
                code,out,err=1,'',str(exc)
            (self.run/'kernel.log').write_text(out or err)
            if code:
                self.s['reviews'].append('No kernel log evidence available for this interval.')
            elif any(word in out.lower() for word in ('i/o error','hard resetting link','failed command','link is slow','exception emask')):
                self.s['reviews'].append('Kernel storage errors/resets found; inspect kernel.log (includes all devices).')
            if not any(row.split(',')[1].strip() for row in (self.run/'temperature.csv').read_text().splitlines()[1:]):
                self.s['reviews'].append('No valid temperature reading was collected; monitoring may not have started.')
            self.s['failures']=list(dict.fromkeys(self.s['failures']))
            self.s['reviews']=list(dict.fromkeys(self.s['reviews']))
            self.s['finished']=dt.datetime.now(dt.timezone.utc).isoformat()
            self.checkpoint()
        return {'PASS':0,'REVIEW':2,'FAIL':3,'INCOMPLETE':4}[self.s['outcome']]


def main():
    p=argparse.ArgumentParser(prog='ssdbench', description='Repeatable SATA SSD testing and static reports')
    p.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('list',help='List disks and stable IDs without testing')
    for name in ('plan','run'):
        q=sub.add_parser(name)
        q.add_argument('--device',required=True)
        q.add_argument('--profile',choices=['screen','full'],default='screen')
        q.add_argument('--results',type=Path,default=Path('/srv/ssd-results'))
        q.add_argument('--confirm-erase',help='Exact serial; mandatory for full runs')
        q.add_argument('--max-temperature',type=int,default=70)
        q.add_argument('--selftest-timeout',type=int,default=720,help='Minutes per self-test')
    q=sub.add_parser('report',help='Rebuild static reports from saved evidence')
    q.add_argument('--results',type=Path,required=True)
    args=p.parse_args()
    if args.action=='report':
        args.results=args.results.resolve()
        for path in args.results.glob('*/*/summary.json'): report(path.parent)
        index(args.results); return
    if platform.system()!='Linux': p.error('Disk operations require Linux. Reports can be built on any OS.')
    if args.action=='list':
        print(required(['lsblk','-d','-o','NAME,SIZE,MODEL,SERIAL,TRAN,ROTA']))
        for path in sorted(Path('/dev/disk/by-id').glob('*')):
            if '-part' not in path.name: print(path,'->',path.resolve())
        return
    if os.geteuid()!=0: p.error('Run plan/run with sudo for complete safety checks.')
    args.results=args.results.resolve()
    if args.max_temperature<1 or args.selftest_timeout<1: p.error('Limits must be positive.')
    try:
        profile=load_profile(args.profile)
        node=inspect(args.device,args.results)
        print(json.dumps({'target':node,'profile':profile,'workloads':list(workloads(profile,int(node['size']),int(node['log-sec'])))},indent=2))
        if args.action=='plan': return
        if args.profile=='full' and args.confirm_erase!=node['serial'].strip():
            raise ValueError('Full profile erases ALL target data. Supply --confirm-erase with its exact serial.')
        for exe in ('fio','smartctl','journalctl'):
            required([exe,'--version'])
        if 'fio-' not in required(['fio','--version']): raise ValueError('fio is not the Flexible I/O Tester.')
        os.umask(0o022)
        args.results.mkdir(parents=True,exist_ok=True)
        # Global station lock: one suite at a time, even across result directories.
        with open('/run/lock/ssdbench.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            node=inspect(args.device,args.results)
            if args.profile=='full' and args.confirm_erase!=node['serial'].strip():
                raise ValueError('Serial changed during preflight.')
            run=args.results/slug(node['serial'].strip())/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+args.profile+'_'+uuid.uuid4().hex[:8])
            (run/'fio').mkdir(parents=True)
            save(run/'manifest.json',{'suite_version':VERSION,'profile':profile,'target':node,'kernel':platform.release(),'platform':platform.platform(),'fio':required(['fio','--version']).strip(),'smartctl':required(['smartctl','--version']),'source_sha256':source_hashes(),'max_temperature':args.max_temperature,'selftest_timeout_minutes':args.selftest_timeout})
            def interrupt(signum, frame): raise KeyboardInterrupt(f'Signal {signum}')
            signal.signal(signal.SIGTERM,interrupt)
            bench=Bench(args,node,profile,run)
            code=bench.execute()
            print(f"{bench.s['outcome']}: {run/'report.html'}")
            sys.exit(code)
    except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as exc:
        p.exit(1,f'Preflight/orchestration error: {exc}\n')
