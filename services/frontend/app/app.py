from flask import Flask, render_template, Response, redirect, request
from pykafka import KafkaClient
from pykafka.common import OffsetType
import redis
import locale
import glob
import json
import os
import subprocess
import config

app = Flask(__name__)

app.config["CACHE_TYPE"] = "null"
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

red = redis.StrictRedis(host=config.REDIS_HOST, port=config.REDIS_PORT)

global_supported_languages = {}    # Set by the call of fetch_language()
global_language_applied = ""

def event_stream():
    pubsub = red.pubsub()
    pubsub.subscribe(config.REDIS_CHANNEL)
    for message in pubsub.listen():
        print(message)
        yield 'data: %s\n\n' % message['data']

def get_stats(input):
    # Formats a number val according to the current LC_NUMERIC settings
    return locale.format_string('%d', input)

def fetch_language(language_set_in_url):
    global global_supported_languages
    global global_language_applied

    # Fetch available locales
    available_locales = get_supported_locales()

    try:
        if language_set_in_url + '.utf8' in available_locales:
            locale.setlocale(locale.LC_ALL, language_set_in_url + '.utf8')
            global_language_applied = language_set_in_url
            load_language_file(language_set_in_url)
            return True  # Language successfully set
        else:
            raise ValueError(f"Locale '{language_set_in_url}' not supported")

    except (locale.Error, ValueError) as e:
        print(f"Error setting locale '{language_set_in_url}': {e}")

    # Try default language
    try:
        default_locale = config.DEFAULT_LANGUAGE + '.utf8'
        if default_locale in available_locales:
            locale.setlocale(locale.LC_ALL, default_locale)
            global_language_applied = config.DEFAULT_LANGUAGE
            load_language_file(config.DEFAULT_LANGUAGE)
            return True  # Default language successfully set
        else:
            raise ValueError(f"Default locale '{default_locale}' not supported")

    except (locale.Error, ValueError) as e:
        print(f"Error setting default locale '{config.DEFAULT_LANGUAGE}': {e}")

    # Try known supported locales
    print("Setting to a known supported locale")
    for lang_code in global_supported_languages.keys():
        if lang_code + '.utf8' in available_locales:
            try:
                locale.setlocale(locale.LC_ALL, lang_code + '.utf8')
                global_language_applied = lang_code
                load_language_file(lang_code)
                return True  # Known supported language successfully set
            except locale.Error as e:
                print(f"Error setting locale '{lang_code}': {e}")

    # If no valid locale could be set
    global_language_applied = config.DEFAULT_LANGUAGE
    load_language_file(config.DEFAULT_LANGUAGE)
    return False  # No valid language set

def load_language_file(lang_code):
    global global_supported_languages

    lang_file_path = f"static/data/languages/{lang_code}.json"
    if os.path.exists(lang_file_path):
        with open(lang_file_path, 'r', encoding='utf8') as file:
            global_supported_languages[lang_code] = json.load(file)
    else:
        print(f"Language file '{lang_code}.json' not found.")

# Function to get supported locales
def get_supported_locales():
    locales_output = subprocess.check_output(['locale', '-a']).decode('utf-8')
    return set(locales_output.split())

@app.route('/')
def index():
    return redirect('/' + config.DEFAULT_LANGUAGE + '/map', code=302)

@app.route('/<language_set_in_url>/map')
@app.route('/map')
def map(language_set_in_url='fr_FR'):
    # Fetch and set the language
    if not fetch_language(language_set_in_url):
        # Handle case where language couldn't be set, maybe redirect or show an error page
        return "Language not supported"

    # Now global_language_applied should be correctly set
    PAGE_URL = request.base_url
    PAGE_TITLE = 'Coverage Live Map'

    MAP_URL_TEMPLATE = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
    MAP_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    MAP_STARTING_CENTER = [48.8566, 2.3522]
    MAP_STARTING_ZOOM = 12
    MAP_MAX_ZOOM = 18

    # Ensure global_language_applied is not empty
    if global_language_applied:
        # Render the template with multiple variables
        return render_template('index.php', **locals(), lang_data=global_supported_languages.get(global_language_applied, {}))
    else:
        return "Language not set properly"

def get_kafka_client():
    return KafkaClient(hosts=config.KAFKA_BROKER)

@app.route('/topic/<topicname>')
def get_messages(topicname):
    client = get_kafka_client()
    def events():
        for i in client.topics[topicname].get_simple_consumer(
            auto_offset_reset=OffsetType.LATEST,
            reset_offset_on_start=True
        ):
            yield 'data:{0}\n\n'.format(i.value.decode())
    return Response(events(), mimetype="text/event-stream")

def initialize_globals():
    global global_supported_languages
    global global_language_applied

    global_supported_languages = {}    # Set by the call of fetch_language()
    global_language_applied = ""

    # START Load in global_supported_languages the content of the language dictionary files retrieved in language_list
    language_list = glob.glob("static/data/languages/*.json")
    for lang in language_list:
        filename = os.path.basename(lang)
        lang_code = os.path.splitext(filename)[0]

        with open(lang, 'r', encoding='utf8') as file:
            global_supported_languages[lang_code] = json.load(file)
    # END Load in...

def main():
    initialize_globals()
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5001)

if __name__ == '__main__':
    main()
