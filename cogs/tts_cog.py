import logging
import os
import uuid

import boto3
import discord
from discord.ext import commands

import config
from utils import Song

class TTS(commands.Cog, name="TTS"):
    """Commands for Text-to-Speech functionality."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.polly_client = boto3.client(
            'polly',
            aws_access_key_id=config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
            region_name=config.AWS_REGION_NAME
        )
        self.playback_cog = self.bot.get_cog("PlaybackManager")

    async def cog_before_invoke(self, ctx: commands.Context):
        """Ensure the PlaybackManager is available and user is in a voice channel."""
        if self.playback_cog is None:
            self.playback_cog = self.bot.get_cog("PlaybackManager")

        if self.playback_cog is None:
            raise commands.CommandError("PlaybackManager cog is not loaded.")
            
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("You need to be in a voice channel to use TTS.")
            raise commands.CommandError("Author not connected to a voice channel.")

    @commands.command(name='tts', help='Generates Text-to-Speech audio and adds it to the queue.')
    async def tts(self, ctx: commands.Context, *, text: str):
        """Generates TTS audio and enqueues it via the PlaybackManager."""
        async with ctx.typing():
            try:
                response = self.polly_client.synthesize_speech(
                    VoiceId='Brian',
                    OutputFormat='mp3',
                    Text=text,
                    Engine='standard'
                )

                speech_id = uuid.uuid4().hex
                filename = os.path.join(config.TTS_DIR, f'speech_{speech_id}.mp3')

                with open(filename, 'wb') as f:
                    f.write(response['AudioStream'].read())
                
                # Use specific, simpler FFmpeg options for local TTS files
                tts_ffmpeg_options = {'options': '-vn'}

                title = (text[:35] + '...') if len(text) > 35 else text
                song = Song(
                    title=f"TTS: '{title}'",
                    stream_url=filename, # Local file, so stream_url is known immediately
                    requester=ctx.author,
                    is_tts=True,
                    ffmpeg_options=tts_ffmpeg_options
                )

                if await self.playback_cog.enqueue(ctx, song):
                    await ctx.send(f":microphone2: Added TTS message to the queue.")

            except Exception as e:
                logging.error(f"Error with TTS: {e}", exc_info=True)
                await ctx.send("An error occurred during Text-to-Speech synthesis.")

async def setup(bot: commands.Bot):
    await bot.add_cog(TTS(bot))

