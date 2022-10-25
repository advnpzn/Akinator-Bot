from json import load
import os
from dotenv import load_dotenv

load_dotenv()

AKI_MONGO_HOST = os.environ.get('aki_mongo_host', "")
BOT_TOKEN = os.environ.get('bot_token', "")