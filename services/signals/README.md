## Installation
```
pip install -r requirements.txt
```

## Run
Setup environment variables that will be used by the following commands for your configuration.
```bash
export BROKER_IP_ADDRESS=localhost
export BROKER_PORT=9092
export YOUR_TOPIC_NAME=paris_units_gps_tracking
```

Start Zookeeper and Kafka under different tmux sessions.
```bash
# Start Zookeeper service in a tmux session
tmux new -s zookeeper-server-start -d
tmux send-keys "~/Kafka/bin/zookeeper-server-start.sh ~/Kafka/config/zookeeper.properties" Enter

# Start Kafka server in a tmux session
tmux new -s kafka-server-start -d
tmux send-keys "~/Kafka/bin/kafka-server-start.sh ~/Kafka/config/server.properties" Enter
```

Start services requiring sudo privileges
```bash
sudo systemctl start redis.service && \
while ! nc -z localhost 6379; do sleep 1; done && \
echo 'Redis started' && \
redis-cli FLUSHDB && \
echo 'Redis keys from the current selected DB have been deleted' && \
sudo systemctl start postgresql-13.service && \
while ! nc -z localhost 5432; do sleep 1; done && \
echo 'PostgreSQL started'
```

Start the signal provider
```bash
# Start Zookeeper and then Kafka in 2 tmux sessions
tmux new -s zookeeper-server-start -d && \
tmux send-keys "~/Kafka/bin/zookeeper-server-start.sh ~/Kafka/config/zookeeper.properties" Enter && \
while ! nc -z localhost 2181; do sleep 1; done && \
echo 'Zookeeper started' && \
sleep 20 && tmux new -s kafka-server-start -d && \
tmux send-keys "~/Kafka/bin/kafka-server-start.sh ~/Kafka/config/server.properties" Enter && \
while ! nc -z localhost 9092; do sleep 1; done && \
echo 'Kafka started' && \
sleep 3 && tmux new -s services -d && \
tmux send-keys "tmux new-window \; split-window -p 66 \; split-window -d \; split-window -h" Enter && \
tmux send-keys -t services:0.0 "export PYTHONPATH=\$PYTHONPATH:/home/benjamin/Documents/playground/ds4es/cms/signals && ~/miniconda3/envs/cms-backend/bin/python ~/Documents/playground/ds4es/cms/signals/customer_side/main_stream_replay_from_postgres_to_kafka.py 10" Enter && \
sleep 1 && tmux send-keys -t services:0.1 "cd /home/benjamin/Documents/playground/ds4es/cms/service-coverage-monitoring-backend && ./bin/stream_geo_worker" Enter && \
tmux attach-session -t services
```

Or 
```bash
# Start Zookeeper and then Kafka in 2 tmux sessions
tmux new -s zookeeper-server-start -d && \
tmux send-keys "~/Kafka/bin/zookeeper-server-start.sh ~/Kafka/config/zookeeper.properties" Enter && \
while ! nc -z localhost 2181; do sleep 1; done && \
echo 'Zookeeper started' && echo 'Waiting 20 seconds before starting Kafka is required...' && \
sleep 20 && tmux new -s kafka-server-start -d && \
tmux send-keys "~/Kafka/bin/kafka-server-start.sh ~/Kafka/config/server.properties" Enter && \
while ! nc -z localhost 9092; do sleep 1; done && \
echo 'Kafka started' && \
sleep 3 && tmux new -s services -d && \
tmux send-keys "tmux splitw -h -p 50 && tmux splitw -v -p 50 && tmux selectp -t 0 && tmux splitw -v -p 50"  Enter && \
sleep 1 && echo 'Start the services' && \
tmux send-keys -t services:0.0 "cd /home/benjamin/Documents/playground/ds4es/cms/service-coverage-monitoring-backend && ./bin/stream_record_worker" Enter && \
tmux send-keys -t services:0.1 "cd /home/benjamin/Documents/playground/ds4es/cms/service-coverage-monitoring-backend && ./bin/api_get_gp_n_status" Enter && \
tmux send-keys -t services:0.2 "cd /home/benjamin/Documents/playground/ds4es/cms/service-coverage-monitoring-backend && ./bin/stream_geo_worker" Enter && \
 echo 'And finally start the main data stream!' && \
tmux send-keys -t services:0.3 "export PYTHONPATH=\$PYTHONPATH:/home/benjamin/Documents/playground/ds4es/cms/signals && ~/miniconda3/envs/cms-backend/bin/python ~/Documents/playground/ds4es/cms/signals/customer_side/main_stream_replay_from_postgres_to_kafka.py 10" Enter && \
tmux attach-session -t services
```


```bash
tmux new -s services -d && \
tmux send-keys "tmux splitw -v -p 50"  Enter && \
sleep 1 && echo 'Start the services' && \
tmux send-keys -t services:0.0 "cd /home/benjamin/Documents/playground/ds4es/cms/service-coverage-monitoring-backend && ./bin/stream_geo_worker" Enter && \
 echo 'And finally start the main data stream!' && \
tmux send-keys -t services:0.1 "export PYTHONPATH=\$PYTHONPATH:/home/benjamin/Documents/playground/ds4es/cms/signals && ~/miniconda3/envs/cms-backend/bin/python ~/Documents/playground/ds4es/cms/signals/customer_side/main_stream_replay_from_postgres_to_kafka.py 10" Enter && \
tmux attach-session -t services
```

Source: https://github.com/wurstmeister/kafka-docker/issues/389
Introduce a 20 second delay between zookeeper and kafka. The zookeeper has a session expiry time of 18000ms. It needs this time to declare the old session dead. If the Kafka broker is brought up before this happens, the broker shuts down with "Error while creating ephemeral at /broker/ids/1, node already exists". You can thus create an entrypoint

General stop
```
tmux kill-server && \
sudo systemctl stop redis.service && \
sudo systemctl stop postgresql-13.service
```

tmux commands
```
# Pour lister les sessions actives et récupérer l'identifiant de session
tmux ls
# Ré-ouverture d'une session
tmux attach-session -t <session_identifier>
# Pour mettre fin à une session tmux
tmux kill-session -t <session_identifier>
```
Detach from tmux by pressing Ctrl+b, d 

Check if Zookeeper is running
```
echo dump | nc localhost 2181 | grep brokers
```

List all Kafka topics
```
~/Kafka/bin/kafka-topics.sh --list --zookeeper localhost:2181
```

Use the console producer to send messages on your topic
```
~/Kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic yaya
```

Use the console consumer to view messages produced on your topic
```
~/Kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic my_topic_name
```

Add `--from-beginning` if you want to start from the beginning.

Start Redis
```
sudo systemctl start redis.service
```

Start the GPS positionning provider
```
~/miniconda3/envs/cms-backend/bin/python ~/Documents/playground/ds4es/cms/signals/units_gps_positioning/kafka_stream_producer_paris_alpha.py 1
```

Start the GPS signal consumer 
```
~/miniconda3/envs/cms-backend/bin/python ~/Documents/playground/ds4es/cms/signals/units_gps_positioning/kafka_consumer_to_redis_v1.py
```

## Install and start Redis
```
sudo dnf install redis
sudo vi /etc/redis.conf
sudo systemctl start redis.service
sudo systemctl status redis
```

### Redis basic commands
Access to the command line interface
```
redis-cli
```

Check if Redis works
```
ping
```

Set a key
```
set my_key some_value
```

Retrieve a key value
```
get my_key
```

Delete a key
```
del my_key
```

Cf. playground/C++/redis-plus-plus

Next: 
- Créer un petit programme Python maintenant à jour les positions GPS courantes des engins au sein de Redis
- Créer un script de lecture d'une base Redis en C++

Message:
```
{
    dat: <datetime>
    ,uni: [<unit id>,<unit category>,<unit's parking station>]
    ,sta: [<status id>,<availability>]
    ,gp1: [<current latitude>,<current longitude>]
    ,gp2: [<destination's latitude>,<destination's longitude>]
    ,int: [<intervention>,<intervention category>]
}
```