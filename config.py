# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- BOT ---
BOT_PREFIX = os.getenv('BOT_PREFIX', '.')

# --- AUDIO ---
DEFAULT_VOLUME = 0.15
# Effective output volume used by FFmpeg filter. Can be overridden via MUSIC_VOLUME env var.
EFFECTIVE_VOLUME = float(os.getenv('MUSIC_VOLUME', str(DEFAULT_VOLUME)))

# --- PLAYBACK ---
# Timeout in seconds for the bot to disconnect if the queue is empty.
# Can be overridden by setting PLAYBACK_TIMEOUT in the .env file.
PLAYBACK_TIMEOUT = float(os.getenv('PLAYBACK_TIMEOUT', '300.0')) # Default to 300 seconds (5 minutes)

# --- YOUTUBE / YT-DLP ---
YOUTUBE_API_KEY = os.getenv("youtube_api_key")
YT_DLP_OPTIONS = {
    # Prefer 192 kbps audio when available, then <=192, then best fallback
    'format': 'bestaudio[abr=192]/bestaudio[abr<=192]/bestaudio/best',
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

# --- AWS POLLY ---
AWS_ACCESS_KEY_ID = os.getenv('ACCESS_KEY')
AWS_SECRET_ACCESS_KEY = os.getenv('SECRET_ACCESS_KEY')
AWS_REGION_NAME = 'ap-southeast-2'

# --- DIRECTORIES ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(SCRIPT_DIR, "temp")
MUSIC_DIR = os.path.join(SCRIPT_DIR, "music")
TTS_DIR = os.path.join(SCRIPT_DIR, "tts")