"""SQLite-backed group-wide LLM budget ledger; not a tamper-proof proctor.
Run budget check before calls; record usage after calls. All agents use same DB.
"""
import argparse, sqlite3, time
from pathlib import Path

CAP_REQUESTS=300
CAP_TOKENS=250000
MAX_PER_60_SECONDS=2

def connection(path='logs/budget.sqlite3'):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, model TEXT, input_tokens INT, output_tokens INT, status TEXT)')
    db.commit(); return db

def usage(db):
    row=db.execute("SELECT COUNT(*),COALESCE(SUM(input_tokens+output_tokens),0) FROM usage WHERE status IN ('ok','reserved','failed')").fetchone()
    recent=db.execute("SELECT COUNT(*) FROM usage WHERE status IN ('ok','reserved','failed') AND t>?",(time.time()-60,)).fetchone()[0]
    return {'requests':row[0],'tokens':row[1],'requests_last_60s':recent}

def reserve(model,db_path='logs/budget.sqlite3'):
    db=connection(db_path)
    try:
        db.execute('BEGIN IMMEDIATE')
        x=usage(db)
        if x['requests']>=CAP_REQUESTS or x['tokens']>=CAP_TOKENS or x['requests_last_60s']>=MAX_PER_60_SECONDS:
            db.rollback();raise RuntimeError('Budget exhausted or two requests made in the preceding rolling 60 seconds: '+str(x))
        cursor=db.execute('INSERT INTO usage(t,model,input_tokens,output_tokens,status) VALUES(?,?,0,0,?)',(time.time(),model,'reserved'))
        db.commit(); return cursor.lastrowid
    finally: db.close()

def complete(reservation_id,input_tokens,output_tokens,ok=True,db_path='logs/budget.sqlite3'):
    db=connection(db_path)
    try:
        db.execute('UPDATE usage SET input_tokens=?, output_tokens=?, status=? WHERE id=? AND status="reserved"',
                   (int(input_tokens),int(output_tokens),'ok' if ok else 'failed',reservation_id))
        db.commit()
    finally: db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--db',default='logs/budget.sqlite3');args=parser.parse_args()
    db=connection(args.db);print('Current:',usage(db)); db.close()
