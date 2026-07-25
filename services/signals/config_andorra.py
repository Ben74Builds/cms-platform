import os

# App setup
SERVICE = 2  # Andorra service
SPEED_UP_N_TIMES = 100
DEFAULT_DATETIME = '2025-01-01 00:00:00'
PRINT_MESSAGES = True
PRINT_MESSAGES_FULL = True

# Andorra units
UNIT_FILTER = '(101, 102, 103, 104, 105, 106, 107, 108, 109)'

# Database
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'ems')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_USER_PW = os.getenv('DB_PASSWORD', '')

# Kafka
KAFKA_HOSTS = os.getenv('KAFKA_HOSTS', 'localhost:9092')
KAFKA_TOPIC_MAIN_STREAM = 'andorra_gps_status'
KAFKA_TOPIC_ROUTE_REQUEST = 'andorra_route_request'
KAFKA_TOPIC_COVERAGE_REQUEST = 'andorra_coverage_request'
KAFKA_CONSUMER_GROUP = 'andorra_group'

# Redis config
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CHANNEL = 'andorra_gps_status'
