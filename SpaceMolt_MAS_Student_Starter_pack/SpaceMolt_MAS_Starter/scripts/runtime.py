"""Manual assessed-session runtime ledger (not tamper-proof).
Use once per group with a shared local database; must log start/stop for every
live assessed session. Instructor compares these times with game activity.
"""
import argparse,sqlite3,time,datetime
from pathlib import Path
DB='logs/runtime.sqlite3'; CAP=8*3600

def conn():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB)
    db.execute('CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY,started REAL,ended REAL)')
    db.commit();return db

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('start','stop','status'))
    a=p.parse_args().action;db=conn()
    openrow=db.execute('SELECT id,started FROM sessions WHERE ended IS NULL ORDER BY id DESC LIMIT 1').fetchone()
    if a=='start':
        if openrow: raise SystemExit('Already running: close existing assessed session first')
        used=db.execute('SELECT COALESCE(SUM(ended-started),0) FROM sessions WHERE ended IS NOT NULL').fetchone()[0]
        if used>=CAP: raise SystemExit('Eight-hour assessed execution cap reached')
        db.execute('INSERT INTO sessions(started,ended) VALUES(?,NULL)',(time.time(),));db.commit();print('ASSESSED SESSION STARTED')
    if a=='stop':
        if not openrow: raise SystemExit('No running assessed session')
        db.execute('UPDATE sessions SET ended=? WHERE id=?',(time.time(),openrow[0]));db.commit();print('ASSESSED SESSION STOPPED')
    used=db.execute('SELECT COALESCE(SUM(ended-started),0) FROM sessions WHERE ended IS NOT NULL').fetchone()[0]
    if openrow and a!='stop': used+=time.time()-openrow[1]
    print(f'Assessed minutes accounted: {used/60:.2f} / {CAP/60:.0f}; remaining: {max(0,CAP-used)/60:.2f}')
    db.close()
if __name__=='__main__':main()
