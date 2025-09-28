import asyncio
import logging
import os
import uuid
import random
import difflib
from functools import partial

import discord
import yt_dlp
from discord.ext import commands
from googleapiclient.discovery import build

import config
from utils import Song

class GuildState:
    """Manages the state for a single guild."""
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue = asyncio.Queue()
        self.voice_client = None
        self.current_song: Song = None
        self.playback_task = None
        self.volume = config.DEFAULT_VOLUME
        self.announcement_channel_id = None
        # Event to signal when the next song can be played
        self.next_song = asyncio.Event()

    async def _playback_loop(self):
        """The main loop that plays songs from the queue."""
        await self.bot.wait_until_ready()
        music_cog = self.bot.get_cog("Music") # Get the cog to access its methods

        while not self.bot.is_closed():
            self.next_song.clear() # Clear the event for the new song

            try:
                # Wait for the next song. Timeout after 5 minutes of inactivity.
                self.current_song = await asyncio.wait_for(self.queue.get(), timeout=300.0) 
            except asyncio.TimeoutError:
                logging.info(f"Playback loop for guild {self.guild.id} timed out. Disconnecting.")
                return await self.stop()

            if not self.voice_client or not self.voice_client.is_connected():
                logging.warning(f"Voice client not connected in guild {self.guild.id}, stopping loop.")
                return

            # LAZY LOADING: Fetch the stream URL only when we're about to play it.
            try:
                if not self.current_song.stream_url:
                    stream_url = await music_cog._get_audio_source_url(self.current_song.source_url, self.bot.loop)
                    self.current_song.stream_url = stream_url
                    logging.info(f"Fetched stream URL for {self.current_song.title}")
                else:
                    logging.info(f"Using cached stream URL for {self.current_song.title}")
            except Exception as e:
                logging.error(f"Error fetching stream URL for {self.current_song.title}: {e}")
                if self.announcement_channel_id:
                    channel = self.guild.get_channel(self.announcement_channel_id)
                    if channel:
                        await channel.send(f":x: Could not play **{self.current_song.title}**. Skipping.")
                self._song_finished() # Signal to continue to the next song
                continue # Skip the rest of the loop for this failed song

            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(self.current_song.stream_url, **self.current_song.ffmpeg_options),
                volume=self.volume
            )
            
            self.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self._song_finished, e))
            
            if self.announcement_channel_id:
                channel = self.guild.get_channel(self.announcement_channel_id)
                if channel:
                     await channel.send(f":musical_note: Now playing: {self.current_song}")
            
            # Wait until the song is finished (or skipped)
            await self.next_song.wait()


    def _song_finished(self, error=None):
        """Callback for when a song finishes. Signals the loop to continue."""
        if error:
            logging.error(f"Player error in guild {self.guild.id}: {error}")
        
        self.current_song = None
        self.next_song.set() # Set the event to signal the next song can play

    def start_playback(self, channel_id: int):
        """Starts the playback loop if not already running."""
        if self.playback_task is None or self.playback_task.done():
            self.announcement_channel_id = channel_id
            self.playback_task = self.bot.loop.create_task(self._playback_loop())

    async def stop(self):
        """Stops playback and cleans up resources."""
        # Clear the queue
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


class MusicCog(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_states = {}
        self.ytdl = yt_dlp.YoutubeDL(config.YT_DLP_OPTIONS)
        self.youtube_api = build('youtube', 'v3', developerKey=config.YOUTUBE_API_KEY) if config.YOUTUBE_API_KEY else None

    def _get_or_create_state(self, guild: discord.Guild) -> GuildState:
        """Retrieves or creates a GuildState for a given guild."""
        if guild.id not in self.guild_states:
            self.guild_states[guild.id] = GuildState(self.bot, guild)
        return self.guild_states[guild.id]
        
    async def cog_before_invoke(self, ctx: commands.Context):
        playback_commands = ['play', 'p', 'pshuffled', 'pboosted']
        if ctx.command.name in playback_commands:
            if not ctx.author.voice or not ctx.author.voice.channel:
                await ctx.send("You need to be in a voice channel to use this command.")
                raise commands.CommandError("Author not connected to a voice channel.")
    
    async def _fetch_from_youtube(self, query: str, loop: asyncio.AbstractEventLoop):
        if 'playlist?list=' in query and self.youtube_api:
            playlist_id = query.split('playlist?list=')[1].split('&')[0]
            videos = []
            next_page_token = None
            while True:
                res = await loop.run_in_executor(None, lambda: self.youtube_api.playlistItems().list(
                    playlistId=playlist_id, part='snippet', maxResults=50, pageToken=next_page_token
                ).execute())
                videos.extend(res['items'])
                next_page_token = res.get('nextPageToken')
                if next_page_token is None:
                    break
            return [(item['snippet']['title'], f"https://www.youtube.com/watch?v={item['snippet']['resourceId']['videoId']}", None) for item in videos if item['snippet']['title'] != "Deleted video"]

        to_run = partial(self.ytdl.extract_info, url=query, download=False)
        data = await loop.run_in_executor(None, to_run)
        if not data: raise ValueError("Could not extract information from YouTube.")
        if 'entries' in data:
            return [(entry['title'], entry.get('webpage_url'), entry.get('url')) for entry in data['entries'] if entry]
        else:
            return [(data['title'], data.get('webpage_url'), data.get('url'))]
    
    async def _get_audio_source_url(self, youtube_url: str, loop: asyncio.AbstractEventLoop) -> str:
        to_run = partial(self.ytdl.extract_info, url=youtube_url, download=False)
        data = await loop.run_in_executor(None, to_run)
        if not data or 'url' not in data: raise ValueError("Could not extract stream URL.")
        return data['url']

    @commands.command(name='join', help='Joins your current voice channel.')
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            return await ctx.send("You are not connected to a voice channel.")
        channel = ctx.author.voice.channel
        state = self._get_or_create_state(ctx.guild)
        if state.voice_client and state.voice_client.is_connected():
            await state.voice_client.move_to(channel)
        else:
            state.voice_client = await channel.connect()

    @commands.command(name='leave', aliases=['disconnect', 'l'], help='Disconnects the bot and clears the queue.')
    async def leave(self, ctx: commands.Context):
        state = self._get_or_create_state(ctx.guild)
        if state.voice_client:
            await state.stop()
            self.guild_states.pop(ctx.guild.id, None)
            await ctx.send("Disconnected and cleared the queue.")
        else:
            await ctx.send("I'm not in a voice channel.")

    @commands.command(name='play', aliases=['p', 'py'], help='Plays a song from YouTube or adds to queue.')
    async def play(self, ctx: commands.Context, *, query: str):
        await self._enqueue_youtube_song(ctx, query)
        
    @commands.command(name='pboosted', aliases=['pb'], help='Plays a song with extra bass.')
    async def play_boosted(self, ctx: commands.Context, *, query: str):
        await self._enqueue_youtube_song(ctx, query, bass_boost=True)

    @commands.command(name='pshuffled', aliases=['ps'], help='Plays and shuffles a YouTube playlist.')
    async def play_shuffled(self, ctx: commands.Context, *, playlist_url: str):
        await self._enqueue_youtube_song(ctx, playlist_url, shuffle=True)
        
    async def _enqueue_youtube_song(self, ctx: commands.Context, query: str, shuffle=False, bass_boost=False):
        state = self._get_or_create_state(ctx.guild)
        if not state.voice_client or not state.voice_client.is_connected():
            state.voice_client = await ctx.author.voice.channel.connect()

        async with ctx.typing():
            try:
                results = await self._fetch_from_youtube(query, self.bot.loop)
                if not results: return await ctx.send("Could not find any songs for that query.")
                if shuffle: random.shuffle(results)

                songs_to_add = []
                for title, source_url, stream_url in results:
                    if not source_url: continue
                    ffmpeg_opts = config.FFMPEG_OPTIONS.copy()
                    options = list(ffmpeg_opts.get('options', '').split())
                    if bass_boost: options.extend(['-af', 'bass=g=20'])
                    ffmpeg_opts['options'] = ' '.join(options)
                    song = Song(
                        title=title, 
                        source_url=source_url,
                        stream_url=stream_url,
                        requester=ctx.author, 
                        ffmpeg_options=ffmpeg_opts
                    )
                    await state.queue.put(song)
                    songs_to_add.append(song)
                
                state.start_playback(ctx.channel.id)

                if len(songs_to_add) > 1:
                    await ctx.send(f":notes: Added `{len(songs_to_add)}` songs to the queue.")
                else:
                    await ctx.send(f":notes: Added {songs_to_add[0]} to the queue.")
            except Exception as e:
                logging.error(f"Error playing song: {e}", exc_info=True)
                await ctx.send(f"An error occurred: `{e}`")
    
    @commands.command(name='skip', help='Skips the current song.')
    async def skip(self, ctx: commands.Context):
        state = self._get_or_create_state(ctx.guild)
        if state.voice_client and state.voice_client.is_playing():
            await ctx.send(f":track_next: Skipping {state.current_song}")
            state.voice_client.stop()
        else:
            await ctx.send("Not playing anything right now.")

    @commands.command(name='queue', aliases=['q'], help='Shows the current song queue.')
    async def queue(self, ctx: commands.Context):
        state = self._get_or_create_state(ctx.guild)
        if state.current_song is None and state.queue.empty():
            return await ctx.send("**Queue is empty.**")

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())
        if state.current_song:
             embed.add_field(name="Now Playing", value=str(state.current_song), inline=False)
        if not state.queue.empty():
            queue_list = list(state.queue._queue)
            queue_text = ""
            for i, song in enumerate(queue_list[:10]):
                 queue_text += f"`{i+1}.` {song}\n"
            if len(queue_list) > 10:
                queue_text += f"\n...and {len(queue_list) - 10} more."
            embed.add_field(name="Up Next", value=queue_text, inline=False)
        await ctx.send(embed=embed)
        
    @commands.command(name='clear', help='Clears all songs from the queue.')
    async def clear(self, ctx: commands.Context):
        state = self._get_or_create_state(ctx.guild)
        if state.queue.empty():
            return await ctx.send("The queue is already empty.")
        while not state.queue.empty():
            try: state.queue.get_nowait()
            except asyncio.QueueEmpty: pass
        await ctx.send("**:wastebasket: Cleared the queue.**")

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
