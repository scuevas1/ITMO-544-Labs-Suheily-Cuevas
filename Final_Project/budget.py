import argparse
from decimal import Decimal
from stack.config import settings

def estimate(hours, rate, gemini_calls, other_cost):
    if min(hours,rate,gemini_calls,other_cost)<0:raise ValueError('Inputs must not be negative')
    cost=Decimal(str(hours))*Decimal(str(rate))+Decimal(str(other_cost))
    return {'running_hours':hours,'assumed_hourly_usd':rate,'gemini_calls':gemini_calls,'other_usd':other_cost,'estimated_total_usd':round(cost,4),'under_two_dollars':cost<Decimal('2.00')}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--hours',type=float,required=True,help='Real cumulative running hours from your test sessions')
    parser.add_argument('--hourly-rate',type=float,default=0.07,help='Replace with actual billing estimate')
    parser.add_argument('--gemini-calls',type=int,default=0)
    parser.add_argument('--other-cost',type=float,default=0)
    args=parser.parse_args()
    import json
    print(json.dumps(estimate(args.hours,args.hourly_rate,args.gemini_calls,args.other_cost),indent=2,default=str))

if __name__=='__main__':main()

