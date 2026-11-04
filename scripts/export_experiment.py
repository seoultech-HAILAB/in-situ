"""Export labelled browser/server events plus complete code/result snapshots.

No public download endpoint and no .env or credentials in exported records.
"""
import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


def display_time(value, korean=False):
    if value is None or value=='':return ''
    try:
        stamp=datetime.fromtimestamp(value,timezone.utc) if isinstance(value,(int,float)) else datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone(timedelta(hours=9)) if korean else timezone.utc).isoformat(timespec='milliseconds')
    except (ValueError,TypeError,OverflowError):return ''


def export(data_dir, output, experiment_id=None):
    root = Path(data_dir)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    participants = []
    for file in sorted((root / 'experiments').glob('*.json')):
        state = json.loads(file.read_text(encoding='utf-8'))
        if experiment_id and state['id'] != experiment_id:
            continue
        state.pop('token_hash', None)
        participants.append(state)
    ids = {item['id'] for item in participants}
    events = []
    dbfile = root / 'experiments' / 'events.sqlite3'
    if dbfile.exists():
        with sqlite3.connect(dbfile) as db:
            for eid, payload in db.execute('SELECT experiment_id,payload FROM events ORDER BY rowid'):
                if eid in ids:
                    events.append(json.loads(payload))
    (output / 'participants.json').write_text(json.dumps(participants, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output / 'events.jsonl').open('w', encoding='utf-8') as handle:
        for entry in events:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    columns = ['id','server_at','client_at','participant_id','experiment_id','condition','phase','task_number','task_id',
               'session_id','label','action_label','page_id','sequence','context','data',
               'server_at_kst','client_at_kst','task_started_at_utc','task_started_at_kst','task_ended_at_utc','task_ended_at_kst']
    with (output / 'events.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for event in events:
            row={k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in event.items()}
            row.update(server_at_kst=display_time(event.get('server_at'),True),client_at_kst=display_time(event.get('client_at'),True))
            if event['label'] in ('task.started','task.finished'):
                data=event.get('data',{})
                started=data.get('started_at') if 'started_at' in data else event.get('server_at') if event['label']=='task.started' else None
                for suffix,korean in [('utc',False),('kst',True)]:
                    row['task_started_at_'+suffix]=display_time(started,korean)
                    row['task_ended_at_'+suffix]=display_time(data.get('ended_at'),korean)
            writer.writerow(row)
    sessions = output / 'sessions'
    sessions.mkdir(exist_ok=True)
    count = 0
    for file in sorted((root / 'sessions').glob('*.json')):
        session = json.loads(file.read_text(encoding='utf-8'))
        if session.get('experiment_id') in ids:
            (sessions / file.name).write_text(json.dumps(session, ensure_ascii=False), encoding='utf-8')
            count += 1
    return {'participants': len(participants), 'events': len(events), 'sessions': count}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='.local')
    parser.add_argument('--output', required=True)
    parser.add_argument('--experiment-id')
    args = parser.parse_args()
    print(json.dumps(export(args.data_dir, args.output, args.experiment_id)))
