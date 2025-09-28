# main.py
import os
import asyncio
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

import config

# Set up basic logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()
DISCORD_TOKEN = os.getenv("discord_token")

# Define the bot's intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read message content
intents.voice_states = True

# Bot class that will be used to run the bot
class MusicBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned_or(config.BOT_PREFIX), intents=intents)

    async def on_ready(self):
        logging.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logging.info('------')
        
    async def setup_hook(self):
        """This is called when the bot logs in."""
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    logging.info(f"Loaded cog: {filename}")
                except Exception as e:
                    logging.error(f'Failed to load extension {filename}.', exc_info=e)

async def main():
    bot = MusicBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    # Create necessary directories if they don't exist
    for path in [config.TEMP_DIR, config.MUSIC_DIR, config.TTS_DIR]:
        if not os.path.exists(path):
            os.makedirs(path)
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown requested. Exiting.")