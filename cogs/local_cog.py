import os
import asyncio
import mimetypes
import difflib
from typing import List

import discord
from discord.ext import commands

import config
from utils import Song


ALLOWED_EXTENSIONS: List[str] = [
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac"
]


class LocalMusic(commands.Cog, name="LocalMusic"):
    """Commands for playing and managing local audio files in MUSIC_DIR."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.playback_cog = self.bot.get_cog("PlaybackManager")

    async def cog_before_invoke(self, ctx: commands.Context):
        """Ensure the PlaybackManager is available and author is in voice."""
        if self.playback_cog is None:
            self.playback_cog = self.bot.get_cog("PlaybackManager")

        if self.playback_cog is None:
            raise commands.CommandError("PlaybackManager cog is not loaded.")

        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("You need to be in a voice channel to use local music commands.")
            raise commands.CommandError("Author not connected to a voice channel.")

    def _is_audio_file(self, filename: str) -> bool:
        ext = os.path.splitext(filename)[1].lower()
        if ext in ALLOWED_EXTENSIONS:
            return True
        guessed, _ = mimetypes.guess_type(filename)
        return bool(guessed and guessed.startswith("audio/"))

    def _resolve_local_path(self, filename: str) -> str:
        # Prevent path traversal
        safe_name = os.path.basename(filename)
        full_path = os.path.abspath(os.path.join(config.MUSIC_DIR, safe_name))
        if not full_path.startswith(os.path.abspath(config.MUSIC_DIR) + os.sep):
            raise ValueError("Invalid path.")
        return full_path

    def _list_local_tracks(self) -> List[str]:
        if not os.path.isdir(config.MUSIC_DIR):
            return []
        return [f for f in os.listdir(config.MUSIC_DIR) if self._is_audio_file(f)]

    def _normalize_name(self, name: str) -> str:
        base = os.path.splitext(name)[0]
        # Replace common separators with spaces and lower
        normalized = ''.join(ch if ch.isalnum() else ' ' for ch in base).lower()
        # Collapse multiple spaces
        return ' '.join(normalized.split())

    def _fuzzy_find_best(self, query: str, files: List[str]):
        if not files:
            return None, []
        q = self._normalize_name(query)
        # Exact (case-insensitive) filename match
        lower_map = {f.lower(): f for f in files}
        if query.lower() in lower_map:
            return lower_map[query.lower()], []

        # Precompute normalized names
        norm_map = {f: self._normalize_name(f) for f in files}

        # Prefix matches have priority
        prefix_matches = [f for f, n in norm_map.items() if n.startswith(q)]
        if prefix_matches:
            # Prefer shortest name among prefix matches
            best = min(prefix_matches, key=lambda f: len(norm_map[f]))
            return best, []

        # Substring matches next
        substr_matches = [f for f, n in norm_map.items() if q in n]
        if substr_matches:
            # Rank by SequenceMatcher ratio on normalized names
            best = max(substr_matches, key=lambda f: difflib.SequenceMatcher(None, q, norm_map[f]).ratio())
            # Provide up to 5 suggestions ranked similarly
            ranked = sorted(substr_matches, key=lambda f: difflib.SequenceMatcher(None, q, norm_map[f]).ratio(), reverse=True)
            return best, ranked[:5]

        # Fallback to difflib across all names
        ranked_all = sorted(files, key=lambda f: difflib.SequenceMatcher(None, q, norm_map[f]).ratio(), reverse=True)
        best = ranked_all[0] if ranked_all else None
        return best, ranked_all[:5]

    async def _play_local(self, ctx: commands.Context, filename: str, ffmpeg_filters: str = ''):
        async with ctx.typing():
            try:
                path = self._resolve_local_path(filename)
                if not os.path.exists(path):
                    # Fuzzy match fallback
                    files = self._list_local_tracks()
                    if not files:
                        return await ctx.send(f"File not found in music dir: `{filename}`")

                    query = os.path.basename(filename).strip()
                    best, suggestions = self._fuzzy_find_best(query, files)
                    if not best:
                        if suggestions:
                            sug_text = "\n".join([f"- {s}" for s in suggestions])
                            return await ctx.send(f"File not found: `{filename}`. Did you mean:\n{sug_text}")
                        return await ctx.send(f"File not found in music dir: `{filename}`")

                    path = self._resolve_local_path(best)
                    await ctx.send(f"Could not find `{filename}`. Using closest match: **{best}**")

                # Build a single filter chain for FFmpeg
                filters = [f"volume={config.EFFECTIVE_VOLUME}"]
                if ffmpeg_filters:
                    filters.append(ffmpeg_filters)
                filter_chain = ','.join(filters)

                ffmpeg_opts = {
                    'options': f'-vn -filter:a "{filter_chain}"'
                }

                song = Song(
                    title=os.path.basename(path),
                    source_url="",
                    stream_url=path,
                    requester=ctx.author,
                    is_local=True,
                    ffmpeg_options=ffmpeg_opts
                )

                if await self.playback_cog.enqueue(ctx, song):
                    await ctx.send(f":cd: Queued local track **{song.title}**")
            except Exception as e:
                await ctx.send(f"Failed to queue local file: `{e}`")

    @commands.command(name='playlocal', aliases=["pl", "local"], help='Queue a local file.')
    async def local(self, ctx: commands.Context, *, filename: str):
        await self._play_local(ctx, filename)
                
    @commands.command(name='playlocalboosted', aliases=["plb", "localboosted"], help='Queue a local file with bass boost.')
    async def local_boosted(self, ctx: commands.Context, *, filename: str):
        await self._play_local(ctx, filename, ffmpeg_filters='bass=g=20')

    @commands.command(name='locallist', aliases=["ll"], help='List available local audio files.')
    async def locallist(self, ctx: commands.Context):
        files = self._list_local_tracks()
        if not files:
            return await ctx.send("No audio files found in the music directory.")
        # Limit to first 30 entries
        lines = [f"`{i+1:02}` {name}" for i, name in enumerate(files[:30])]
        if len(files) > 30:
            lines.append(f"...and {len(files) - 30} more")
        await ctx.send("Available local files:\n" + "\n".join(lines))

    @commands.command(name='upload', help='Upload attached audio files to the server music directory.')
    async def upload(self, ctx: commands.Context):
        if not ctx.message.attachments:
            return await ctx.send("Attach one or more audio files to upload.")

        os.makedirs(config.MUSIC_DIR, exist_ok=True)
        saved_count = 0

        async with ctx.typing():
            for attachment in ctx.message.attachments:
                try:
                    if not self._is_audio_file(attachment.filename):
                        continue
                    dest_path = self._resolve_local_path(attachment.filename)
                    # Stream download to disk
                    data = await attachment.read(use_cached=False)
                    # Avoid overwriting by deduping name
                    base, ext = os.path.splitext(os.path.basename(dest_path))
                    candidate = dest_path
                    counter = 1
                    while os.path.exists(candidate):
                        candidate = os.path.join(config.MUSIC_DIR, f"{base} ({counter}){ext}")
                        counter += 1
                    with open(candidate, 'wb') as f:
                        f.write(data)
                    saved_count += 1
                except Exception:
                    continue

        if saved_count:
            await ctx.send(f"Saved `{saved_count}` file(s) to the music directory.")
        else:
            await ctx.send("No valid audio attachments were uploaded.")


async def setup(bot: commands.Bot):
    await bot.add_cog(LocalMusic(bot))


