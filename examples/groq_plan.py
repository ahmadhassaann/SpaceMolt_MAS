"""One strategic Groq planning request; no SpaceMolt game actions.
Set GROQ_API_KEY as an environment variable privately before running.
"""
import os,json
from groq import Groq
from scripts.budget import reserve,complete
from scripts.evidence import record

MODEL='openai/gpt-oss-20b'

def main():
    if not os.environ.get('GROQ_API_KEY'):
        raise SystemExit('Missing GROQ_API_KEY: set an environment variable; never commit or paste the key into logs.')
    reservation=reserve(MODEL)
    try:
        client=Groq(api_key=os.environ['GROQ_API_KEY'])
        response=client.chat.completions.create(model=MODEL,reasoning_effort='low',temperature=0.2,max_completion_tokens=250,
            messages=[{'role':'system','content':'You are a cautious fleet coordinator. Return short advice, no game actions.'},
                      {'role':'user','content':'We have two pilots, limited fuel, and 250 credits. State three safe checks before mining.'}])
        use=response.usage
        complete(reservation,getattr(use,'prompt_tokens',0),getattr(use,'completion_tokens',0))
        advice=response.choices[0].message.content or ''
        record('llm.plan',agent='coordinator',task_id='plan-001',data={'model':MODEL,'response':advice,'tokens_in':use.prompt_tokens,'tokens_out':use.completion_tokens})
        print(advice)
    except Exception:
        complete(reservation,0,0,ok=False);raise
if __name__=='__main__':main()
