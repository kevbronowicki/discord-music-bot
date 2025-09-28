# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- BOT ---
BOT_PREFIX = ";"

# --- AUDIO ---
DEFAULT_VOLUME = 0.15

# --- PLAYBACK ---
# Timeout in seconds for the bot to disconnect if the queue is empty.
# Can be overridden by setting PLAYBACK_TIMEOUT in the .env file.
PLAYBACK_TIMEOUT = float(os.getenv('PLAYBACK_TIMEOUT', '300.0')) # Default to 300 seconds (5 minutes)

# --- YOUTUBE / YT-DLP ---
YOUTUBE_API_KEY = os.getenv("youtube_api_key")
YT_DLP_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': 'temp/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0', # bind to ipv4 since ipv6 can cause issues
    'cookiefile': 'cookies.txt'
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# --- AWS POLLY ---
AWS_ACCESS_KEY_ID = os.getenv('ACCESS_KEY')
AWS_SECRET_ACCESS_KEY = os.getenv('SECRET_ACCESS_KEY')
AWS_REGION_NAME = 'ap-southeast-2'

# --- DIRECTORIES ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(SCRIPT_DIR, "temp")
MUSIC_DIR = os.path.join(SCRIPT_DIR, "music")
TTS_DIR = os.path.join(SCRIPT_DIR, "tts")