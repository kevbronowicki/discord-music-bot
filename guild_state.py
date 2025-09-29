import asyncio
import logging
import discord
from discord.ext import commands

import config
from utils import Song

class GuildState:
    """Manages the audio playback state for a single guild."""
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue = asyncio.Queue()
        self.voice_client: discord.VoiceClient = None
        self.current_song: Song = None
        self.playback_task: asyncio.Task = None
        self.announcement_channel_id: int = None
        self.next_song_event = asyncio.Event()
        self._prefetch_task: asyncio.Task = None

    async def _playback_loop(self):
        """The main loop that fetches from the queue and plays songs."""
        await self.bot.wait_until_ready()
        playback_cog = self.bot.get_cog("PlaybackManager")
        if not playback_cog:
            logging.error("CRITICAL: PlaybackManager cog not found.")
            return

        while not self.bot.is_closed():
            self.next_song_event.clear()

            try:
                # Use the configurable timeout from config.py
                self.current_song = await asyncio.wait_for(self.queue.get(), timeout=config.PLAYBACK_TIMEOUT)
            except asyncio.TimeoutError:
                logging.info(f"Playback loop for guild {self.guild.id} timed out. Disconnecting.")
                return await self.stop()

            if not self.voice_client or not self.voice_client.is_connected():
                logging.warning(f"Voice client invalid in guild {self.guild.id}, stopping.")
                return

            try:
                # Lazy load the stream URL if it wasn't provided initially (e.g., from YouTube)
                if not self.current_song.stream_url:
                    stream_url = await playback_cog.get_audio_source_url(self.current_song.source_url, self.bot.loop)
                    self.current_song.stream_url = stream_url

                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(self.current_song.stream_url, **self.current_song.ffmpeg_options)
                )

                self.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self._song_finished_callback, e))

                if self.announcement_channel_id:
                    channel = self.guild.get_channel(self.announcement_channel_id)
                    if channel:
                        await channel.send(f":musical_note: Now playing: {self.current_song}")

                # Opportunistic prefetch of the next song's stream URL in background
                self._start_prefetch_next(playback_cog)

                await self.next_song_event.wait()

            except Exception as e:
                logging.error(f"Error playing {self.current_song.title}: {e}", exc_info=True)
                if self.announcement_channel_id:
                    channel = self.guild.get_channel(self.announcement_channel_id)
                    if channel:
                        await channel.send(f":x: Could not play **{self.current_song.title}**. Skipping.")
                self._song_finished_callback() # Ensure we continue to the next song

    def _song_finished_callback(self, error=None):
        """Called when a song finishes playing. Signals the loop to continue."""
        if error:
            logging.error(f"Player error in guild {self.guild.id}: {error}")
        self.current_song = None
        self.next_song_event.set()

    def start_playback(self, channel_id: int):
        """Starts the playback loop if it's not already running."""
        if self.playback_task is None or self.playback_task.done():
            self.announcement_channel_id = channel_id
            self.playback_task = self.bot.loop.create_task(self._playback_loop())

    async def stop(self):
        """Stops playback, clears the queue, and disconnects."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        
        if self.playback_task:
            self.playback_task.cancel()
            self.playback_task = None

        if self.voice_client:
            await self.voice_client.disconnect()
            self.voice_client = None

        self.current_song = None
        if self._prefetch_task:
            self._prefetch_task.cancel()
            self._prefetch_task = None

    def _start_prefetch_next(self, playback_cog):
        # Only prefetch if there is at least one upcoming item and its stream_url is missing
        if self._prefetch_task and not self._prefetch_task.done():
            return
        try:
            next_song: Song = self.queue._queue[0] if self.queue.qsize() > 0 else None
        except Exception:
            next_song = None
        if not next_song or next_song.stream_url or not next_song.source_url:
            return

        async def _prefetch():
            try:
                stream_url = await playback_cog.get_audio_source_url(next_song.source_url, self.bot.loop)
                next_song.stream_url = stream_url
            except Exception:
                # Ignore prefetch errors; normal path will resolve when needed
                pass

        self._prefetch_task = self.bot.loop.create_task(_prefetch())

