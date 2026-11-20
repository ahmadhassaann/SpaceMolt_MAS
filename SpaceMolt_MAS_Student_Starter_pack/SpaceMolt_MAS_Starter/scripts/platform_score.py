"""Unofficial seven-day challenge score preview from PUBLIC SpaceMolt Service Record stats.
Supply the SUM of both new pilots. TA makes final determination at live demo.
No login, credentials, network, or game actions required.
"""
import argparse


def calculate(raw):
    a = {key: max(0, int(raw.get(key, 0))) for key in ('earned','spent','ore','trades','exchange_sales','distance','systems')}
    sold = a['trades'] >= 1 or a['exchange_sales'] >= 1
    productive = a['earned'] >= 500 and a['ore'] >= 10 and sold
    pts = {
        'Credits earned': 8 if a['earned'] >= 2000 else 6 if a['earned'] >= 1500 else 4 if a['earned'] >= 1000 else 2 if a['earned'] >= 500 else 0,
        'Ore mined': 4 if a['ore'] >= 30 else 3 if a['ore'] >= 20 else 2 if a['ore'] >= 10 else 1 if a['ore'] >= 1 else 0,
        'Trade or exchange sale': 4 if sold else 0,
        'Systems explored': 3 if a['systems'] >= 2 else 1.5 if a['systems'] == 1 else 0,
        'Controlled spending': (3 if a['spent'] <= 1500 else 1 if a['spent'] <= 3000 else 0) if productive else 0,
        'Travel efficiency': (3 if a['distance'] <= 1500 else 1 if a['distance'] <= 3000 else 0) if productive else 0,
    }
    return {'platform_stats': a, 'productive_activity_gate': productive,
            'component_marks': pts, 'competition_marks_out_of_25': sum(pts.values())}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('earned','spent','ore','trades','exchange_sales','distance','systems'):
        p.add_argument('--'+name.replace('_','-'), type=int, default=0)
    args=p.parse_args()
    result=calculate(vars(args))
    for k,v in result['component_marks'].items(): print(f'{k:24}: {v}')
    print(f"TOTAL COMPETITION MARKS  : {result['competition_marks_out_of_25']}/25")
    print('Unofficial preview: TA verifies BOTH profiles and individual demos.')

if __name__=='__main__': main()
