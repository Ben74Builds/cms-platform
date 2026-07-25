"""
Exec with: 
~/miniconda3/envs/cms-backend/bin/python ./simple_subscriber.py

"""

import redis
import json

r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()

def my_handler(message):
    unit = message["data"].decode()
    print(unit)
    print(r.get("mma:"+unit+":coverage"))

p.subscribe(**{'paris_units_coverage_up_to_date':my_handler})
# read the subscribe confirmation message
thread = p.run_in_thread(sleep_time=0.001)

