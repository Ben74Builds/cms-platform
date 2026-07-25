import os

# App setup
SERVICE = 12  # San Marino
SPEED_UP_N_TIMES = 100
DEFAULT_DATETIME = '2025-01-01 00:00:00'
PRINT_MESSAGES = True
PRINT_MESSAGES_FULL = True

# Units
UNIT_FILTER = '(1201, 1202, 1203, 1204, 1205)'

# Database
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'ems')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_USER_PW = os.getenv('DB_PASSWORD', '')

# Kafka
KAFKA_HOSTS = os.getenv('KAFKA_HOSTS', 'localhost:9092')
KAFKA_TOPIC_MAIN_STREAM = 'san-marino_gps_status'
KAFKA_TOPIC_ROUTE_REQUEST = 'san-marino_route_request'
KAFKA_TOPIC_COVERAGE_REQUEST = 'san-marino_coverage_request'
KAFKA_CONSUMER_GROUP = 'san-marino_group'

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CHANNEL = 'san-marino_gps_status'
