import os

# App setup
SERVICE = 11  # Vaduz
SPEED_UP_N_TIMES = 100
DEFAULT_DATETIME = '2025-01-01 00:00:00'
PRINT_MESSAGES = True
PRINT_MESSAGES_FULL = True

# Units
UNIT_FILTER = '(1101, 1102, 1103, 1104, 1105, 1106, 1107, 1108, 1109, 1110, 1111, 1112, 1113, 1114, 1115, 1116, 1117, 1118, 1119, 1120, 1121, 1122, 1123)'

# Database
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'ems')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_USER_PW = os.getenv('DB_PASSWORD', '')

# Kafka
KAFKA_HOSTS = os.getenv('KAFKA_HOSTS', 'localhost:9092')
KAFKA_TOPIC_MAIN_STREAM = 'vaduz_gps_status'
KAFKA_TOPIC_ROUTE_REQUEST = 'vaduz_route_request'
KAFKA_TOPIC_COVERAGE_REQUEST = 'vaduz_coverage_request'
KAFKA_CONSUMER_GROUP = 'vaduz_group'

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CHANNEL = 'vaduz_gps_status'
