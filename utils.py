from dataclasses import dataclass
import discord
from typing import Optional

@dataclass
class Song:
    """Represents a song or audio track."""
    title: str
    source_url: str = "" # Original URL (e.g., YouTube link)
    # stream_url is now optional and will be loaded just-in-time
    stream_url: Optional[str] = None
    requester: discord.Member = None
    is_tts: bool = False
    is_local: bool = False
    ffmpeg_options: dict = None
    
    def __str__(self):
        """Returns a user-friendly string representation."""
        if self.source_url:
            return f"[{self.title}]({self.source_url})"
        return f"**{self.title}**"

