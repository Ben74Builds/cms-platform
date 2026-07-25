import os

# App setup
SERVICE = 13  # Annecy
SPEED_UP_N_TIMES = 100
DEFAULT_DATETIME = '2025-01-01 00:00:00'
PRINT_MESSAGES = True
PRINT_MESSAGES_FULL = True

# Units
UNIT_FILTER = '(1301, 1302, 1303, 1304, 1305, 1306, 1307, 1308, 1309, 1310, 1311, 1312, 1313, 1314, 1315, 1316, 1317, 1318, 1319, 1320)'

# Database
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'ems')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_USER_PW = os.getenv('DB_PASSWORD', '')

# Kafka
KAFKA_HOSTS = os.getenv('KAFKA_HOSTS', 'localhost:9092')
KAFKA_TOPIC_MAIN_STREAM = 'annecy_gps_status'
KAFKA_TOPIC_ROUTE_REQUEST = 'annecy_route_request'
KAFKA_TOPIC_COVERAGE_REQUEST = 'annecy_coverage_request'
KAFKA_CONSUMER_GROUP = 'annecy_group'

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CHANNEL = 'annecy_gps_status'
