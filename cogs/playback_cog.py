import asyncio
import logging
from functools import partial

import discord
import yt_dlp
from discord.ext import commands

import config
from utils import Song
from guild_state import GuildState

class PlaybackManager(commands.Cog, name="PlaybackManager"):
    """A generic cog to manage audio playback state and commands for all sources."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_states = {}
        self.ytdl = yt_dlp.YoutubeDL(config.YT_DLP_OPTIONS)

    def _get_or_create_state(self, guild: discord.Guild) -> GuildState:
        """Retrieves or creates a GuildState for a given guild."""
        if guild.id not in self.guild_states:
            self.guild_states[guild.id] = GuildState(self.bot, guild)
        return self.guild_states[guild.id]

    # --- Public Methods for Other Cogs ---
    async def enqueue(self, ctx: commands.Context, song: Song):
        """A universal method for any cog to add a song to the queue."""
        state = self._get_or_create_state(ctx.guild)

        if not state.voice_client or not state.voice_client.is_connected():
             if ctx.author.voice:
                 state.voice_client = await ctx.author.voice.channel.connect()
             else:
                 await ctx.send("You need to be in a voice channel to play music.")
                 return False

        await state.queue.put(song)
        state.start_playback(ctx.channel.id)
        return True

    async def get_audio_source_url(self, youtube_url: str, loop: asyncio.AbstractEventLoop) -> str:
        """Utility to extract the direct streamable audio URL from a youtube_url."""
        to_run = partial(self.ytdl.extract_info, url=youtube_url, download=False)
        data = await loop.run_in_executor(None, to_run)
        if not data or 'url' not in data:
            raise ValueError("Could not extract stream URL from youtube_url.")
        return data['url']

    # --- Generic Playback Commands ---
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

    @commands.command(name='skip', help='Skips the current song.')
    async def skip(self, ctx: commands.Context):
        state = self._get_or_create_state(ctx.guild)
        if state.voice_client and state.voice_client.is_playing():
            await ctx.send(f":track_next: Skipping {state.current_song}")
            state.voice_client.stop() # This triggers the _song_finished_callback
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
        
        # This is a safe way to clear an asyncio.Queue
        while not state.queue.empty():
            try:
                state.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        
        await ctx.send("**:wastebasket: Cleared the queue.**")

async def setup(bot: commands.Bot):
    await bot.add_cog(PlaybackManager(bot))
