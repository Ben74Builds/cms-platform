"""
Kafka stream producer for units GPS positions and status from a given JSON file 

Usage: kafka_stream_producer_from_postgres.py [ARGUMENTS] 

Optional arguments:
    -h, --help  show this help message and exit

Positional arguments:
    speed_up_n_times (int, optional): speed up times, default 1.
    current_datetime (datetime, optional): with following format YYYY-MM-DDTHH:MM:SS, default '1900-01-01'.

Default values can be defined in the config.py.

Structure of the message produced:

{
  serv: <service>       not null  required
  ,date: <datetime>     not null  required
  ,data: [
    {
      uni: [            required
          <unit id>                             int or string   not null    required
          ,<unit category>                      short int       not null    required
          ,<unit's parking station>             short int       null        required
          ,[<competence>, <competence>, ...]    short int       null        optional
        ]
      ,sta: [            optional   
          <status id>                   short int
          ,<is free>                    bool [0,1]
        ]
      ,gp1: [            optional   
          <current latitude>            float
          ,<current longitude>          float
        ]
      ,gp2: [            optional
          <destination's latitude>      float
          ,<destination's longitude>    float
        ]
      ,int: [            optional   
          <intervention id>                unsigned long int
          ,<intervention category>      short int
        ]
      ,obj: {}
    },{
      uni: [<unit id>,<unit category>,<unit's parking station>]
      ,sta: [<status id>,<is free>]
      ,gp1: [<current latitude>,<current longitude>]
      ,gp2: [<destination's latitude>,<destination's longitude>]
      ,int: [<intervention>,<intervention category>]
      ,obj: {}
    },
    ...
  ]
}
  
"""

# Authors: Benjamin Berhault

# Load required packages
from pykafka import KafkaClient
import json, time, sys, psycopg2
from psycopg2 import pool
from datetime import datetime
import pandas as pd
import redis
import atexit
# Load the custom config file

import config
import os

previous = {}
previous['datetime'] = None
current_datetime = config.DEFAULT_DATETIME
speed_up_n_times = config.SPEED_UP_N_TIMES

# Load hourly mobilization overhead (P50) for dynamic coverage threshold
# Coverage threshold = 600s (10min target) minus mobilization time for current hour
# This gives the backend the NET travel time budget
_hourly_mobilization = {}
try:
    _thresholds_path = os.path.join(os.path.dirname(__file__), '..', 'hourly_thresholds.json')
    with open(_thresholds_path) as f:
        _hourly_mobilization = json.load(f).get('mobilization_p50', {})
except Exception:
    pass
# Fallback: average mobilization by hour from the calibrated hourly profile
if not _hourly_mobilization:
    _hourly_mobilization = {
        "0": 155, "1": 170, "2": 185, "3": 195, "4": 200, "5": 200,
        "6": 180, "7": 148, "8": 133, "9": 135, "10": 128, "11": 125,
        "12": 124, "13": 128, "14": 128, "15": 129, "16": 128, "17": 131,
        "18": 134, "19": 131, "20": 131, "21": 131, "22": 134, "23": 143,
    }
COVERAGE_TARGET_SEC = 600  # 10 minutes operational target

# Redis
r = redis.StrictRedis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    password=config.REDIS_PASSWORD,
    decode_responses=True)


# ============================================================================
# Database Connection Pool (50-80% reduction in connection overhead)
# ============================================================================

# Connection pool configuration
MIN_CONNECTIONS = 2
MAX_CONNECTIONS = 10

# Initialize connection pool
db_pool = None

def init_db_pool():
    """Initialize the PostgreSQL connection pool"""
    global db_pool
    if db_pool is None:
        try:
            db_pool = pool.ThreadedConnectionPool(
                MIN_CONNECTIONS,
                MAX_CONNECTIONS,
                host=config.DB_HOST,
                database=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_USER_PW
            )
            print(f"[DB Pool] Initialized with {MIN_CONNECTIONS}-{MAX_CONNECTIONS} connections")
        except Exception as e:
            print(f"[DB Pool] Failed to initialize: {e}")
            db_pool = None
    return db_pool

def get_db_connection():
    """Get a connection from the pool"""
    if db_pool is None:
        init_db_pool()
    if db_pool:
        return db_pool.getconn()
    return None

def return_db_connection(conn):
    """Return a connection to the pool"""
    if db_pool and conn:
        db_pool.putconn(conn)

def close_db_pool():
    """Close all connections in the pool"""
    global db_pool
    if db_pool:
        db_pool.closeall()
        print("[DB Pool] All connections closed")
        db_pool = None

# Register cleanup on exit
atexit.register(close_db_pool)



def handle_help_flag():
  """ help a help flag """
  if len(sys.argv)==2 and sys.argv[1] in {'--help','-h'}:
    print(__doc__)
    sys.exit()

def handle_arguments():
  """ handle global optional positional command line arguments 
  
  Global optional arguments:
    speed_up_n_times -- the real part (default 0.0)
    current_datetime -- the imaginary part (default 0.0)  
  """  
  global speed_up_n_times
  global current_datetime
  if len(sys.argv) > 1: 
    speed_up_n_times = int(sys.argv[1])
  if len(sys.argv) > 2: 
    current_datetime = sys.argv[2]



def get_next_status_and_position(last_datetime_treated = '1900-01-01 00:00:00'):
    """ query part and vendor data from multiple tables"""
    conn = None         # PostgreSQL connection
    query_result = []   # PostgreSQL query result container
    json_response = {}  # JSON response to return

    try:
        # Get connection from pool (much faster than creating new connection)
        conn = get_db_connection()
        if conn is None:
            # Fallback to direct connection if pool fails
            conn = psycopg2.connect(
              host=config.DB_HOST,
              database=config.DB_NAME,
              user=config.DB_USER,
              password=config.DB_USER_PW)

        # Create a cursor to get the next date        
        cur_get_date = conn.cursor()
        # Execute the query to get next positions and status
        unit_clause = ""
        if hasattr(config, 'UNIT_FILTER') and config.UNIT_FILTER:
            unit_clause = " AND unit IN " + config.UNIT_FILTER
        cur_get_date.execute("""
          select datetime
          FROM data_id
          WHERE datetime > '"""+last_datetime_treated+"""'"""+unit_clause+"""
          ORDER BY datetime
          LIMIT 1;

        """)

        # Start building the message
        json_response['date'] = cur_get_date.fetchone()[0].strftime("%Y-%m-%d %H:%M:%S")
        
        # close the first connection
        cur_get_date.close()

        # Create a cursor to get the next data
        cur = conn.cursor()

        cur.execute("""
            SELECT 
              json_build_object(
                'uni', ('[' || 
                    concat_ws(',',
                      cast(unit as varchar)
                      ,coalesce(cast("unit type" as varchar),'null')
                      ,coalesce(cast("unit lso" as varchar),'null')
                      ,nullif(
                        concat(
                          '['
                          ,concat_ws(
                            ','
                            ,CASE
                              WHEN "unit type" IN (2,3) THEN '1'
                              ELSE null
                            END
                            ,CASE
                              WHEN unit > 3289 THEN '2'
                              ELSE null
                            END
                            ,null
                          )
                          ,']'
                        )
                        ,'[]'
                      )
                    ) ||
                    ']')::json
                , 'sta', ('[' || status || ',' || availability || ']')::json
                , 'gp1', ('[' || latitude1 || ',' || longitude1 || ']')::json
                , 'gp2', ('[' || latitude2 || ',' || longitude2 || ']')::json	
                , 'int', ('[' || intervention || ',' || "intervention type" || ']')::json	
                , 'obj', json_build_object(
                  'id_unit_selection', "id unit selection"
                )			          
              ) AS data
              ,unit
              ,"unit type"
              ,"unit lso"
              ,status
              ,availability
              ,latitude1
              ,longitude1 
              ,intervention
              ,"intervention type"
              ,nullif(
                concat_ws(
                  ','
                  ,CASE
                    WHEN "unit type" IN (2,3) THEN '1'
                    ELSE null
                  END
                  ,null) -- remove all null without additional comma
                ,''
              ) competences
            FROM data_id
            WHERE datetime = '"""+json_response['date']+"""'"""+unit_clause+""";

        """)
        row = cur.fetchone()

        column_names=["unit","unit type","unit lso","status","availability","latitude1","longitude1","intervention","intervention type","competences"]
        df = pd.DataFrame(columns=column_names)

        # Retrieve every row if few
        while row is not None:
            subdf = pd.DataFrame([row[1:]], columns=column_names)
            df = pd.concat([df, subdf], ignore_index=True)  # insert for Redis update
            query_result.append(row[0]) # insert for Kafka stream
            row = cur.fetchone()

        # Enlève les champs vides
        for i in range(len(query_result)):
          empty_keys = [k for k,v in query_result[i].items() if not v]
          for k in empty_keys:
              del query_result[i][k]

        # Completed the message
        json_response['serv'] = config.SERVICE
        json_response['data'] = query_result


        # close second connection
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        # Return connection to pool (or close if it was a fallback connection)
        if conn is not None:
            return_db_connection(conn)

    return df, json_response # Message for Kafka stream

if __name__=='__main__':

  # Useful init functions
  handle_help_flag()
  handle_arguments()

  # Instanciate a Kafka producer
  client = KafkaClient(hosts=config.KAFKA_HOSTS)

  # Flux principal de données communiquant les statuts et positions GPS successifs des unités
  topic_main_stream = client.topics[config.KAFKA_TOPIC_MAIN_STREAM]
  producer_main_stream = topic_main_stream.get_sync_producer()
  
  # Flux secondaire pour requête de calcul d'itinéraire
  topic_route_request = client.topics[config.KAFKA_TOPIC_ROUTE_REQUEST]
  producer_route_request = topic_route_request.get_sync_producer()
      
  # Flux secondaire pour requête de calcul de couverture
  topic_coverage_request = client.topics[config.KAFKA_TOPIC_COVERAGE_REQUEST]
  producer_coverage_request = topic_coverage_request.get_sync_producer()

  while 1:
    # Conserve the previous datetime
    previous["datetime"] = current_datetime
    # Retrieve the new dataset as: 
    # {
    # 	"dat" : "2019-01-01T00:15:55"
    # 	, "uni" : [4192,2,260]
    # 	, "sta" : [1,0]
    # 	, "gp1" : [48.7602773,2.3672525]
    # 	, "gp2" : [48.7577561,2.3475053]
    # 	, "int" : [5960832,3]
    # }
    
    # Récupère les positions et statuts pour le datetime suivant
    # df: sous forme de dataframe
    # data: sous forme json permettant de directement diffusé le message
    df, data = get_next_status_and_position(current_datetime)

    # Auto-loop: if no more data, reset to beginning
    if not data.get('data') and data.get('date') == current_datetime:
        print(f"[Replay] End of data reached at {current_datetime}, looping back to {config.DEFAULT_DATETIME}")
        current_datetime = config.DEFAULT_DATETIME
        previous["datetime"] = None
        time.sleep(2)
        continue

    # Enregistre le nouveau datetime
    current_datetime = data['date']

    # Wait some time based on the previous["datetime"] and current_datetime
    # difference and the speed rate
    if previous["datetime"] != None:
        sleeping_time = abs(datetime.strptime(current_datetime,"%Y-%m-%d %H:%M:%S" ) - datetime.strptime(previous["datetime"],"%Y-%m-%d %H:%M:%S" )).seconds/speed_up_n_times
        #print('sleeping time: ', sleeping_time, ' | speed_up_n_times: ', speed_up_n_times)
        time.sleep(sleeping_time)
        
    if config.PRINT_MESSAGES == True:
      print("**",config.KAFKA_TOPIC_MAIN_STREAM.upper()," ",data,sep='')

    # [Flux principal] Diffuse les statuts et positions sur le topic principal
    producer_main_stream.produce(json.dumps(data).encode('ascii'))
    
    # Débute le renseignement des propriétés de la requête pour le calcul d'itinéraire
    route_request = {}
    route_request['date'] = data['date']
    route_request['serv'] = data['serv']
    route_request['data'] = []

    # Débute le renseignement des propriétés de la requête calcul de couverture
    coverage_request = {}
    coverage_request['date'] = data['date']
    coverage_request['serv'] = data['serv']
    coverage_request['data'] = []
    # Dynamic coverage threshold: 600s target minus mobilization time for this hour
    # Gives the backend the NET travel time budget (what the CH should compute against)
    try:
        current_hour = str(datetime.strptime(current_datetime, "%Y-%m-%d %H:%M:%S").hour)
        mobilization = _hourly_mobilization.get(current_hour, 145)
        coverage_request['threshold'] = max(180, COVERAGE_TARGET_SEC - mobilization)
    except Exception:
        coverage_request['threshold'] = 450  # 600 - 150 avg mobilization

    # Check if a route needs to be compute
    # If so, build a message and send it on 
    # a Kafka topic: KAFKA_TOPIC_ROUTE_REQUEST
    for obj in data['data']:
      # Route service
      if 'gp1' in obj and 'gp2' in obj:
        if obj['gp1'] != None and obj['gp2'] != None:
          route_request['data'].append({
            "uni": obj['uni'][0]
            ,"gp1": [obj['gp1'][0],obj['gp1'][1]]
            ,"gp2": [obj['gp2'][0],obj['gp2'][1]]
          })

      redis_key = "customer_side:mma:"+str(obj['uni'][0]) 
      previous['availability'] = r.hget(redis_key, 'availability')
      previous['latitude1'] = r.hget(redis_key, 'latitude1')
      previous['longitude1'] = r.hget(redis_key, 'longitude1')

      # Coverage service
      # On récupère la position de l'unité
      if 'gp1' in obj and obj['gp1'] != None and obj['gp1'][0] != None:
        latitude = obj['gp1'][0]
        longitude = obj['gp1'][1]
      else: 
        latitude = r.hget(redis_key, 'latitude1')
        longitude = r.hget(redis_key, 'longitude1')


      # Calcul s'il y a eu un changement significatif de latitude
      change_for_latitude = False
      if ('gp1' in obj and ((r.hget(redis_key, 'latitude1') == None and obj['gp1'][0] != None) 
        or (r.hget(redis_key, 'latitude1') != None and obj['gp1'][0] != None 
          and round(float(r.hget(redis_key, 'latitude1')),4) != round(float(obj['gp1'][0]), 4)))):
        change_for_latitude = True

      # Calcul s'il y a eu un changement significatif de longitude
      change_for_longitude = False
      if ('gp1' in obj and ((r.hget(redis_key, 'longitude1') == None and obj['gp1'][1] != None) 
        or (r.hget(redis_key, 'longitude1') != None and obj['gp1'][1] != None 
          and round(float(r.hget(redis_key, 'longitude1')),4) != round(float(obj['gp1'][1]), 4)))):
        change_for_longitude = True

      if (
        obj['sta'][1] == 1 and latitude != None and longitude != None and (       # Si désormais disponible avec une position GPS connue et
        not r.exists(redis_key) or r.hget(redis_key, "availability") == "0" or r.hget(redis_key, "availability") == None or         # n'était pas connu jusqu'ici ou non disponible                             
        change_for_latitude == True or                                                 # ou est arrivée sur une nouvelle latitude 
        change_for_longitude == True)                                                  # ou est arrivée sur une nouvelel longitude
      ):

        latitude = float(latitude)
        longitude = float(longitude)
        print("Calcul de couverture pour ", obj['uni'][0])
        coverage_request['data'].append({
          "uni": obj['uni'][0]
          ,"gp1": [latitude,longitude]
        })
        
      elif (obj['sta'][1] == 0 and                  # Si est indisponible maintenant 
        r.hget(redis_key, "availability") == "1"):    # était disponible précédemment  

        coverage_request['data'].append({
          "uni": obj['uni'][0]
        })
      print("UNIT: ",obj['uni'][0]
        , "\n unité déjà connue: ", r.exists(redis_key)
        , "\n Indisponibilité précédente: ",r.hget(redis_key, "availability") == 0 #r.hget(redis_key, "availability") == 1
        , "\n Indisponibilité précédente (texte): ",r.hget(redis_key, "availability") == "0" #r.hget(redis_key, "availability") == 1
        , "\n Disponibilité précédente: ",r.hget(redis_key, "availability") #r.hget(redis_key, "availability") == 1
        , "\n Disponibilité actuelle: ",obj['sta'][1] == 1
        , "\n Changement de latitude: ",change_for_latitude
        , "\n Changement de longitude: ",change_for_longitude)
      print("obj['sta'][1] == 1 ",obj['sta'][1] == 1
        , "\n latitude != None: ", latitude != None
        , "\n longitude != None: ",longitude != None
        , "\n not r.exists(redis_key): ",not r.exists(redis_key)
        , "\n r.hget(redis_key, \"availability\") == 0: ",r.hget(redis_key, "availability") == 0
        , "\n change_for_latitude == True: ",change_for_latitude == True)



  

    # Update redis
    for index, row in df.iterrows():
      redis_key = "customer_side:mma:"+str(row['unit']) 
      for k,v in row.items():
        if k not in ('unit') and v != None:
          r.hset(redis_key, k, str(v))
          try:
            float(v)
            r.hset(redis_key, k, str(v))
          except ValueError:
            r.hset(redis_key, k, v)


    # Route service    
    if route_request['data'] != []:
      if config.PRINT_MESSAGES == True:
        print("**",config.KAFKA_TOPIC_ROUTE_REQUEST.upper()," ",route_request,sep='')

      # Diffuse une demande de calcul d'itinéraire sur un topic secondaire
      producer_route_request.produce(json.dumps(route_request).encode('ascii'))

    # Coverage service    
    if coverage_request['data'] != []:
      if config.PRINT_MESSAGES == True:
        print("**",config.KAFKA_TOPIC_COVERAGE_REQUEST.upper()," ",coverage_request,sep='')

      # Diffuse une demande de calcul de couverture sur un autre topic secondaire
      producer_coverage_request.produce(json.dumps(coverage_request).encode('ascii'))

