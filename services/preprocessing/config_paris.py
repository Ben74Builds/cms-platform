import os

# App setup
SERVICE = 1  # Paris / Ile-de-France (Paris)
SPEED_UP_N_TIMES = 1  # Real-time (true historical data)
DEFAULT_DATETIME = '2019-01-12 11:03:00'
PRINT_MESSAGES = True
PRINT_MESSAGES_FULL = True

# City metadata
SLUG = 'paris'
NAME = 'Paris / Ile-de-France'
COUNTRY_CODE = 'FR'
CENTER_LAT = 48.866667
CENTER_LON = 2.333333
# Paris covers departments 75, 92, 93, 94 (~30km radius from center)
BBOX_RADIUS_KM = 30.0
ZOOM = 12

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
KAFKA_CONSUMER_GROUP = 'paris_group'

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CHANNEL = 'paris_gps_status'
