import asyncio
import logging
import os
import uuid

import boto3
import discord
from discord.ext import commands

import config
from utils import Song

class TTSCog(commands.Cog, name="TTS"):
    """Handles Text-to-Speech functionality."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.polly_client = boto3.client(
            'polly',
            aws_access_key_id=config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
            region_name=config.AWS_REGION_NAME
        )

    async def cog_before_invoke(self, ctx: commands.Context):
        """Checks for prerequisites before running a command."""
        # Ensure user is in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("You need to be in a voice channel to use this command.")
            raise commands.CommandError("Author not connected to a voice channel.")
            
        # Ensure the Music cog is loaded, as we depend on it for playback
        music_cog = self.bot.get_cog('Music')
        if not music_cog:
            await ctx.send("The Music module is not loaded. TTS functionality is unavailable.")
            raise commands.CommandError("MusicCog not found.")

    @commands.command(name='tts', help='Generates Text-to-Speech audio and adds it to the queue.')
    async def tts(self, ctx: commands.Context, *, text: str):
        """Generates a TTS audio file and queues it for playback using the MusicCog."""
        music_cog = self.bot.get_cog('Music')
        # We get the guild's state from the MusicCog to access the queue
        state = music_cog._get_or_create_state(ctx.guild)
        
        if not state.voice_client or not state.voice_client.is_connected():
            state.voice_client = await ctx.author.voice.channel.connect()

        async with ctx.typing():
            try:
                response = await self.bot.loop.run_in_executor(None, 
                    lambda: self.polly_client.synthesize_speech(
                        VoiceId='Brian', OutputFormat='mp3', Text=text, Engine='standard'
                    )
                )

                speech_id = uuid.uuid4().hex
                filename = os.path.join(config.TTS_DIR, f'speech_{speech_id}.mp3')

                with open(filename, 'wb') as f:
                    f.write(response['AudioStream'].read())
                
                title = (text[:30] + '...') if len(text) > 30 else text
                song = Song(
                    title=f"TTS: '{title}'", stream_url=filename, requester=ctx.author,
                    is_tts=True, ffmpeg_options=config.FFMPEG_OPTIONS.copy()
                )

                await state.queue.put(song)
                # Start playback via the music cog's state manager
                state.start_playback(ctx.channel.id)
                await ctx.send(f":microphone2: Added TTS message to the queue.")

            except Exception as e:
                logging.error(f"Error with TTS: {e}", exc_info=True)
                await ctx.send("An error occurred during Text-to-Speech synthesis.")

async def setup(bot: commands.Bot):
    """Adds the cog to the bot."""
    await bot.add_cog(TTSCog(bot))
