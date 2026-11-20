"""Offline tests; do not call the game, A2A servers, or Groq."""
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts.budget import reserve, complete, connection, usage
from scripts.evidence import record
from scripts.platform_score import calculate

def main():
    with TemporaryDirectory() as temp:
        d = str(Path(temp)/'budget.db')
        r=reserve('mock',d);complete(r,9,6,db_path=d)
        db=connection(d); observed=usage(db);db.close()
        assert observed['requests']==1 and observed['tokens']==15
        print('[PASS] Persistent LLM budget accounting')
        log=str(Path(temp)/'events.jsonl')
        record('local.test',data={'api_key':'SECRET','msg':'gsk_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345'},path=log)
        out=Path(log).read_text()
        assert 'SECRET' not in out and 'gsk_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345' not in out
        print('[PASS] Credential redaction')
        assert calculate({})['competition_marks_out_of_25']==0
        full={'earned':2000,'spent':1000,'ore':30,'trades':1,'exchange_sales':0,'distance':900,'systems':2}
        assert calculate(full)['competition_marks_out_of_25']==25
        assert calculate({**full,'trades':0,'exchange_sales':1})['competition_marks_out_of_25']==25
        assert calculate({**full,'ore':0})['component_marks']['Travel efficiency']==0
        print('[PASS] Platform score bands and safety gates')
    print('LOCAL SELF-TEST PASS')
if __name__=='__main__': main()
