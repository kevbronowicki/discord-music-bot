import asyncio
import logging
import random
from functools import partial

import discord
import yt_dlp
from discord.ext import commands
from googleapiclient.discovery import build

import config
from utils import Song

class Music(commands.Cog, name="Music"):
    """Commands for playing music from YouTube."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ytdl = yt_dlp.YoutubeDL(config.YT_DLP_OPTIONS)
        self.youtube_api = build('youtube', 'v3', developerKey=config.YOUTUBE_API_KEY) if config.YOUTUBE_API_KEY else None
        self.playback_cog = self.bot.get_cog("PlaybackManager")

    async def cog_before_invoke(self, ctx: commands.Context):
        """Ensure the PlaybackManager is available before running a command."""
        if self.playback_cog is None:
            self.playback_cog = self.bot.get_cog("PlaybackManager")
        
        if self.playback_cog is None:
            raise commands.CommandError("PlaybackManager cog is not loaded.")
            
        # Voice channel check
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("You need to be in a voice channel to use music commands.")
            raise commands.CommandError("Author not connected to a voice channel.")
    
    async def _fetch_from_youtube(self, query: str, loop: asyncio.AbstractEventLoop):
        """Fetches video information from YouTube."""
        # Playlist handling
        if 'playlist?list=' in query and self.youtube_api:
            playlist_id = query.split('playlist?list=')[1].split('&')[0]
            videos = []
            next_page_token = None
            while True:
                # Build the request and execute it in a background thread
                request = self.youtube_api.playlistItems().list(
                    playlistId=playlist_id,
                    part='snippet',
                    maxResults=50,
                    pageToken=next_page_token
                )
                executor = getattr(self.playback_cog, 'executor', None)
                res = await loop.run_in_executor(executor, request.execute)
                
                videos.extend(res['items'])
                next_page_token = res.get('nextPageToken')
                if next_page_token is None:
                    break
            # Return metadata: title, source_url, and None for stream_url (to be fetched later).
            return [(item['snippet']['title'], f"https://www.youtube.com/watch?v={item['snippet']['resourceId']['videoId']}", None) for item in videos if item['snippet']['title'] not in ["Deleted video", "Private video"]]

        # Single video or search query handling
        # Prefer YouTube Data API for search and basic metadata to avoid yt_dlp latency
        if self.youtube_api:
            try:
                executor = getattr(self.playback_cog, 'executor', None)
                is_url = query.startswith('http://') or query.startswith('https://')
                if is_url and ('youtube.com/watch' in query or 'youtu.be/' in query):
                    # Extract videoId from URL
                    video_id = None
                    if 'v=' in query:
                        video_id = query.split('v=')[1].split('&')[0]
                    elif 'youtu.be/' in query:
                        video_id = query.split('youtu.be/')[1].split('?')[0].split('&')[0]
                    if video_id:
                        req = self.youtube_api.videos().list(id=video_id, part='snippet', maxResults=1)
                        res = await loop.run_in_executor(executor, req.execute)
                        items = res.get('items', [])
                        if items:
                            title = items[0]['snippet']['title']
                            return [(title, f"https://www.youtube.com/watch?v={video_id}", None)]
                        # Fall through to yt_dlp if API returns nothing
                else:
                    # Treat as search query
                    req = self.youtube_api.search().list(q=query, type='video', part='snippet', maxResults=1)
                    res = await loop.run_in_executor(executor, req.execute)
                    items = res.get('items', [])
                    if items:
                        # return the first item
                        return [(items[0]['snippet']['title'], f"https://www.youtube.com/watch?v={items[0]['id']['videoId']}", None)]
                        
            except Exception as e:
                logging.warning(f"YouTube API search failed, falling back to yt_dlp: {e}")

        # Fallback: use yt_dlp (may be slower but more tolerant)
        to_run = partial(self.ytdl.extract_info, url=query, download=False)
        executor = getattr(self.playback_cog, 'executor', None)
        data = await loop.run_in_executor(executor, to_run)
        if not data:
            raise ValueError("Could not extract information from YouTube.")

        if 'entries' in data: # It's a search result or non-API playlist
            return [(entry['title'], entry.get('webpage_url'), entry.get('url')) for entry in data['entries'] if entry]
        else: # It's a single video
            return [(data['title'], data.get('webpage_url'), data.get('url'))]
    
    async def _enqueue_youtube_songs(self, ctx: commands.Context, query: str, shuffle=False, ffmpeg_filters: str = ''):
        """Fetches songs from YouTube and enqueues them via the PlaybackManager."""
        async with ctx.typing():
            try:
                results = await self._fetch_from_youtube(query, self.bot.loop)
                if not results:
                    return await ctx.send("Could not find any songs for that query.")
                if shuffle:
                    random.shuffle(results)

                songs_added_count = 0
                for title, source_url, stream_url in results:
                    if not source_url:
                        continue

                    # Build a single filter chain for FFmpeg
                    filters = [f"volume={config.EFFECTIVE_VOLUME}"]
                    if ffmpeg_filters:
                        filters.append(ffmpeg_filters)
                    filter_chain = ','.join(filters)

                    ffmpeg_opts = {
                        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                        'options': f'-vn -filter:a "{filter_chain}"'
                    }
                    
                    song = Song(
                        title=title, 
                        source_url=source_url,
                        stream_url=stream_url,
                        requester=ctx.author, 
                        ffmpeg_options=ffmpeg_opts
                    )
                    
                    if await self.playback_cog.enqueue(ctx, song):
                        songs_added_count += 1
                
                if songs_added_count > 1:
                    await ctx.send(f":notes: Added `{songs_added_count}` songs to the queue.")
                elif songs_added_count == 1:
                    await ctx.send(f":notes: Added **{results[0][0]}** to the queue.")

            except Exception as e:
                logging.error(f"Error enqueuing YouTube song: {e}", exc_info=True)
                await ctx.send(f"An error occurred: `{e}`")

    @commands.command(name='play', aliases=['p', 'py'], help='Plays a song from YouTube or adds to queue.')
    async def play(self, ctx: commands.Context, *, query: str):
        await self._enqueue_youtube_songs(ctx, query)
        
    @commands.command(name='pboosted', aliases=['pb'], help='Plays a song with extra bass.')
    async def play_boosted(self, ctx: commands.Context, *, query: str):
        await self._enqueue_youtube_songs(ctx, query, ffmpeg_filters='bass=g=20')

    @commands.command(name='pshuffled', aliases=['ps'], help='Plays and shuffles a YouTube playlist.')
    async def play_shuffled(self, ctx: commands.Context, *, playlist_url: str):
        await self._enqueue_youtube_songs(ctx, playlist_url, shuffle=True)
    
    @commands.command(name='csgo', help='Clears songs in queue then skips, then plays the requested YouTube videos shuffled')
    async def csgo(self, ctx: commands.Context, *, query: str):
        state = self.playback_cog._get_or_create_state(ctx.guild)

        # Clear the queue
        while not state.queue.empty():
            try:
                state.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Skip current if playing
        if state.voice_client and state.voice_client.is_playing():
            current = str(state.current_song) if state.current_song else "current track"
            await ctx.send(f":wastebasket: Cleared the queue. :track_next: Skipping {current}")
            state.voice_client.stop()
        else:
            await ctx.send(":wastebasket: Cleared the queue.")

        # Enqueue the requested YouTube video using the shared helper
        await self._enqueue_youtube_songs(ctx, query, shuffle=True)
        
async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))

