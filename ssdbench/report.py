"""Offline HTML reports: no web service, scripts, or external assets required."""
import csv
import html
import io
import json
import os
from pathlib import Path
from urllib.parse import quote


def atomic(path, text):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text)
    os.chmod(tmp, 0o644)
    tmp.replace(path)


def save(path, data):
    atomic(path, json.dumps(data, indent=2) + '\n')


def esc(value):
    return html.escape(str(value))


def page(title, body):
    return f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>
body{{font:16px system-ui,sans-serif;max-width:1150px;margin:40px auto;padding:0 24px;background:#f5f7fa;color:#182635}}
a{{color:#0758a6}} h1{{font-size:32px}} h2{{margin-top:32px}} table{{border-collapse:collapse;width:100%;background:white;display:block;overflow:auto}}
th,td{{text-align:left;padding:10px 14px;border-bottom:1px solid #dce2ea;white-space:nowrap}}
.card{{padding:18px;background:white;border:1px solid #dce2ea;border-radius:10px;margin:18px 0}}
.PASS{{color:#086139}} .FAIL{{color:#b32020}} .REVIEW{{color:#895200}} .INCOMPLETE{{color:#615270}}
svg{{width:100%;height:auto;background:white}} small{{color:#506070}} code{{overflow-wrap:anywhere}}
</style><main>{body}</main></html>'''


def table(headers, rows):
    return '<table><thead><tr>' + ''.join(f'<th>{esc(x)}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{esc(x)}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table>'


def chart(points, title, unit):
    if not points:
        return f'<p>{esc(title)}: no samples available.</p>'
    # Limit visual points without discarding raw evidence.
    ymax = max(max(y for _,y in points), 1)
    points = points[::max(1, len(points)//900)]
    xs, ys = zip(*points)
    lo, hi = min(xs), max(xs)
    poly = ' '.join(f'{60+(x-lo)/max(hi-lo,1)*860:.1f},{220-y/ymax*170:.1f}' for x,y in points)
    return f'<h3>{esc(title)}</h3><svg viewBox="0 0 960 270" role="img" aria-label="{esc(title)}"><path d="M60 40V220H920" fill="none" stroke="#94a3b8"/><polyline points="{poly}" fill="none" stroke="#087e8b" stroke-width="2"/><text x="60" y="25">Peak {ymax:.1f} {esc(unit)}</text><text x="60" y="250">0</text><text x="760" y="250">{hi-lo:.0f} seconds elapsed</text></svg>'


def report(run):
    run = Path(run)
    s = json.loads((run/'summary.json').read_text())
    status = s['outcome']
    body = f'<a href="../../index.html">All runs</a><h1>SSD test report</h1><div class="card"><h2 class="{esc(status)}">{esc(status)}</h2><p>{esc(s["model"])} · {esc(s["serial"])} · {esc(s["profile"])}</p><p>{esc(s["started"])} · {esc(s.get("finished", "In progress"))}</p></div>'
    body += table(['Property','Value'], [(k,s.get(k,'—')) for k in ('run_id','capacity_bytes','device','suite_version','profile_version','complete')])
    body += '<h2>Findings</h2><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in s['failures']+s['reviews']+s.get('notes',[])) + '</ul>'
    body += '<p>PASS applies only to the recorded profile and completed checks. Performance is not a reliability grade. Vendor-specific wear values require model-specific interpretation.</p>'
    body += '<h2>Stages</h2>' + table(['Stage','Result','Details'], [(x['name'],x['status'],x.get('detail','')) for x in s['stages']])
    rows=[]
    for path in sorted((run/'fio').glob('*.json')):
        try:
            data=json.loads(path.read_text())
            if not isinstance(data,dict): continue
            for job in data.get('jobs',[]):
                for direction in ('read','write'):
                    v=job.get(direction,{})
                    if not v.get('io_bytes'): continue
                    p=v.get('lat_ns',{}).get('percentile',{})
                    rows.append([path.stem,direction,v['io_bytes'],f"{v.get('bw_bytes',0)/1048576:.1f}",f"{v.get('iops',0):.0f}"]+[f"{p.get(k,0)/1000:.1f}" if k in p else '—' for k in ('50.000000','95.000000','99.000000','99.900000')])
        except (ValueError,KeyError):
            pass
    body += '<h2>Performance and coverage</h2><p>Total latency percentiles in µs. Integrity-stage rates include verification overhead.</p>' + table(['Stage','I/O','Bytes','MiB/s','IOPS','p50 µs','p95 µs','p99 µs','p99.9 µs'], rows)
    temps=[]
    tp=run/'temperature.csv'
    if tp.exists():
        for row in csv.DictReader(io.StringIO(tp.read_text())):
            if row['celsius']:
                temps.append((float(row['epoch']),float(row['celsius'])))
    body += chart(temps,'Observed drive temperature','°C')
    bw=[]
    for path in sorted((run/'fio').glob('integrity_bw*.log')):
        for line in path.read_text().splitlines():
            cols=line.split(',')
            if len(cols)>=3 and cols[2].strip()=='1':
                bw.append((float(cols[0])/1000,float(cols[1])/1024))
    body += chart(sorted(bw),'Full-capacity verification write bandwidth','MiB/s')
    before=run/'smart-before.json'; after=run/'smart-after.json'
    if before.exists() and after.exists():
        from .core import attributes
        b,a=json.loads(before.read_text()),json.loads(after.read_text())
        ba,aa=attributes(b),attributes(a)
        body += '<h2>Drive identity and SATA link</h2>' + table(['Field','Value'],[(k,a.get(k,'Unavailable')) for k in ('firmware_version','sata_version','interface_speed','power_on_time','temperature')])
        body += '<h2>SMART attributes</h2><p>Raw values are vendor-specific; no universal remaining-life percentage is inferred.</p>' + table(['ID','Attribute','Before raw','After raw','Normalized','Threshold'],[(k,v.get('name'),ba.get(k,{}).get('raw',{}).get('string','—'),v.get('raw',{}).get('string','—'),v.get('value'),v.get('thresh')) for k,v in aa.items()])
    body += '<h2>Evidence</h2><ul>'
    for path in sorted(run.rglob('*')):
        if path.is_file() and path.name!='report.html' and not path.name.endswith('.tmp'):
            rel=path.relative_to(run).as_posix()
            body += f'<li><a href="{quote(rel)}">{esc(rel)}</a></li>'
    body += '</ul>'
    atomic(run/'report.html',page('SSD report — '+s['serial'],body))


def index(root):
    root=Path(root)
    rows=[]
    for path in sorted(root.glob('*/*/summary.json'),reverse=True):
        s=json.loads(path.read_text())
        rows.append({k:s.get(k,'') for k in ('started','serial','model','profile','outcome','capacity_bytes','run_id')} | {'report':str(path.parent.relative_to(root)/'report.html')})
    fields=['started','serial','model','profile','outcome','capacity_bytes','run_id','report']
    out=io.StringIO(); writer=csv.DictWriter(out,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    atomic(root/'index.csv',out.getvalue())
    body='<h1>SSD bench results</h1><p>One immutable directory per run. <a href="index.csv">Download CSV index</a>.</p><table><tr>'+''.join(f'<th>{esc(k)}</th>' for k in fields[:-1])+ '<th>Report</th></tr>'
    for row in rows:
        body+='<tr>'+''.join(f'<td>{esc(row[k])}</td>' for k in fields[:-1])+f'<td><a href="{quote(row["report"])}">Open report</a></td></tr>'
    atomic(root/'index.html',page('SSD bench results',body+'</table>'))
