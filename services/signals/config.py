import os

# App setup
SERVICE = 1
SPEED_UP_N_TIMES = 1
DEFAULT_DATETIME = '2019-01-12 11:03:00'
PRINT_MESSAGES = True
PRINT_MESSAGES_FULL = True

# Database
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'ems')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_USER_PW = os.getenv('DB_PASSWORD', '')

# Kafka
KAFKA_HOSTS = os.getenv('KAFKA_HOSTS', 'localhost:9092')
KAFKA_TOPIC_MAIN_STREAM = 'paris_gps_status'
KAFKA_TOPIC_ROUTE_REQUEST = 'paris_route_request'
KAFKA_TOPIC_COVERAGE_REQUEST = 'paris_coverage_request'
KAFKA_CONSUMER_GROUP = 'mygroup'

# Redis config
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CHANNEL = 'paris_gps_status'
