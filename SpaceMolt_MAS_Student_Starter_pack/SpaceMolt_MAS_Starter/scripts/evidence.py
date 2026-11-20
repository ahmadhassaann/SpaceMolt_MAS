"""Append-only JSONL events with secret redaction and independent timestamps."""
from __future__ import annotations
import json, re, time
from datetime import datetime, timezone
from pathlib import Path

SENSITIVE=('password','api_key','token','registration_code','session_id','authorization','secret','cookie')
KEYPAT=re.compile(r'\bgsk_[A-Za-z0-9_-]{15,}\b')

def scrub(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if any(s in str(k).lower() for s in SENSITIVE) else scrub(v)) for k,v in value.items()}
    if isinstance(value,list): return [scrub(x) for x in value]
    if isinstance(value,str): return KEYPAT.sub('[REDACTED GROQ KEY]',value)
    return value

def record(event, *, agent='system', task_id=None, data=None, path='logs/events.jsonl'):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    item={'time_utc':datetime.now(timezone.utc).isoformat(), 'monotonic_seconds':time.monotonic(),
          'event':event,'agent':agent,'task_id':task_id,'data':scrub(data or {})}
    with p.open('a',encoding='utf-8') as f: f.write(json.dumps(item,ensure_ascii=False,default=str)+'\n')
    print(f'[EVENT] {item["time_utc"]} {agent} {event} task={task_id}')
    return item

if __name__=='__main__':
    record('demo.event', agent='planner', task_id='demo-001', data={'message':'test','api_key':'never-log-this'})
