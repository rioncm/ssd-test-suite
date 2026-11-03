"""Generate synthetic report fixtures only. Never accesses block devices."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ssdbench.report import save, report, index

root=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/ssdbench-demo').resolve()
run=root/'DEMO-NOT-A-REAL-DRIVE'/'20261103T120000Z_full_demo'
if run.exists():
    raise SystemExit(f'Refusing to overwrite existing demo: {run}')
(run/'fio').mkdir(parents=True)
s={'run_id':run.name,'serial':'DEMO-NOT-A-REAL-DRIVE','model':'SYNTHETIC EXAMPLE — not measured',
   'profile':'full','profile_version':'1.0.0','suite_version':'0.1.0','device':'DEMO ONLY',
   'capacity_bytes':1073741824,'started':'2026-11-03T12:00:00+00:00','finished':'2026-11-03T12:10:00+00:00',
   'outcome':'REVIEW','complete':True,'failures':[],'reviews':['Synthetic demonstration. No disk was tested.'],
   'stages':[{'name':x,'status':'DEMO','detail':'Invented sample results'} for x in ['smart-short','smart-long','integrity','read-qd32']],
   'notes':['All values in this report are invented to demonstrate presentation.']}
save(run/'summary.json',s)
for name in ('smart-before','smart-after'):
    save(run/(name+'.json'),{'model_name':s['model'],'serial_number':s['serial'],'firmware_version':'DEMO',
         'smart_status':{'passed':True},'temperature':{'current':38 if name.endswith('before') else 45},
         'interface_speed':{'current':{'string':'6.0 Gb/s'}},'ata_smart_attributes':{'table':[
             {'id':199,'name':'UDMA_CRC_Error_Count','value':100,'thresh':0,'raw':{'string':'0','value':0}}]}})
job={}
for direction,rate in [('read',500),('write',350)]:
    job[direction]={'io_bytes':1073741824,'bw_bytes':rate*1048576,'iops':rate,
                    'lat_ns':{'percentile':{'50.000000':100000,'95.000000':200000,'99.000000':500000,'99.900000':1000000}}}
save(run/'fio/integrity.json',{'jobs':[job]})
(run/'temperature.csv').write_text('epoch,celsius\n'+''.join(f'{1793707200+i*30},{35+min(i,10)}\n' for i in range(20)))
(run/'fio/integrity_bw.1.log').write_text(''.join(f'{1793707200000+i*1000}, {450000 if i<20 else 180000+(i%5)*2000}, 1, 0\n' for i in range(60)))
(run/'kernel.log').write_text('DEMO ONLY — no kernel evidence\n')
save(run/'manifest.json',{'demo':True,'note':'Synthetic, not a real test'})
report(run); index(root)
print(root/'index.html')
