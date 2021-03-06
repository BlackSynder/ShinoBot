from collections import namedtuple

import discord
from discord.ext import commands

from utils.resources import YTDLSource, get_song_length
from utils.paginator import Pages

Song = namedtuple("Song", "ctx player notif")


def master_only():
    def predicate(ctx):
        if ctx.state.master:
            return ctx.state.master in ctx.author.roles
        return False
    return commands.check(predicate)


class Music:
    def __init__(self, bot):
        self.bot = bot
        self.bot.states = {}

    def __local_check(self, ctx):
        if ctx.config['locked'] is None:
            return True
        return ctx.author.id not in ctx.config['locked']

    @master_only()
    @commands.command()
    async def summon(self, ctx):
        """[M] Joins the channel you're currently in"""
        if ctx.author.voice:
            if ctx.voice_client:
                return await ctx.voice_client.move_to(ctx.author.voice.channel)
            return await ctx.author.voice.channel.connect()
        await ctx.send(":exclamation: You're not connected to a voice channel!")

    @master_only()
    @commands.command()
    async def join(self, ctx, *, channel: discord.VoiceChannel):
        """[M] Joins a voice channel"""
        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)
        await channel.connect()

    @commands.command()
    async def play(self, ctx, *, query=None):
        """Streams from a query (almost anything youtube_dl supports)"""
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                return await ctx.send(":exclamation: Not connected to a voice channel.")

        if ctx.author.voice:
            if ctx.author.voice.channel != ctx.voice_client.channel:
                return await ctx.send(":exclamation: You must be in the same channel as me!")
        else:
            return await ctx.send("You must be in the voice channel to queue songs!")

        async with ctx.typing():
            if query:
                max_len = ctx.config['length_max']
                if max_len and max_len > 0:
                    length = await get_song_length(query)
                    if length > max_len:
                        return await ctx.send(f"Song is too long! Limit is `{max_len}` seconds.")
                player = await YTDLSource.from_query(query, loop=self.bot.loop)
            elif len(ctx.message.attachments) > 0:
                try:
                    file = ctx.message.attachments[0]
                    await file.save(file.filename)
                    player = YTDLSource.from_file(file.filename)
                except Exception as e:
                    print(e)
                    return await ctx.send("Could not play file.")
            else:
                return await ctx.send("Must specify search query or upload music file.")
        song = Song(ctx, player, [])
        await ctx.state.queue.put(song)
        await ctx.send(f'Enqueued:\n     {player.title}')

    @commands.command(aliases=["np"])
    async def playing(self, ctx):
        """Shows the currently playing song"""
        song = ctx.state.current
        embed = discord.Embed(title=song.ctx.author.name, description=song.player.title)
        await ctx.send(embed=embed)

    @commands.command()
    async def skip(self, ctx):
        """Votes to skip the current song"""
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send("Cannot skip, I'm not playing anything!")

        if ctx.author.voice:
            if ctx.author.voice.channel != ctx.voice_client.channel:
                return await ctx.send("You must be in the same channel as me to skip!")
        else:
            return await ctx.send("You're not in the voice channel!")

        if ctx.author.id in ctx.state.skips:
            await ctx.send("You've voted already!")
        else:
            ctx.state.skips.append(ctx.author.id)
            await ctx.send("Added vote to skip the song")
            ctx.state.skip_song()

    @commands.command()
    async def queue(self, ctx):
        """Shows the currently queued songs"""
        q = ctx.state.queue
        if q.empty():
            return await ctx.send("The queue is currently empty.\nYou can queue songs by typing `m!play <song name>`.")
        queue = [f"{song.player.title}\n    By: {song.ctx.author.name}" for song in q._queue]
        p = Pages(self.bot, message=ctx.message, entries=queue)
        p.embed.set_author(name="Music Queue")
        await p.paginate()

    @commands.command(aliases=['myq'])
    async def myqueue(self, ctx):
        """Shows the songs you've queued"""
        q = ctx.state.queue
        queue = [f"{song.player.title}\n" for song in q._queue if song.ctx.author == ctx.author]
        if not queue:
            return await ctx.send("You haven't queued anything yet! "
                                  "You can queue songs by typing `m!play <song name>`.")
        p = Pages(self.bot, message=ctx.message, entries=queue)
        p.embed.set_author(name=f"{ctx.author.name}'s Queue", icon_url=ctx.author.avatar_url)
        await p.paginate()

    @commands.command(aliases=['ohshit', 'shit'])
    async def unqueue(self, ctx):
        """Unqueue the last song you've queued"""
        q = ctx.state.queue
        if sum(1 for s in q._queue if s.ctx.author == ctx.author) == 0:
            return await ctx.send("You don't have any songs queued. Use `m!play <song name>` to queue something.")

        target = None
        for s in reversed(q._queue):
            if s.ctx.author == ctx.author:
                target = s
                break
        q._queue.remove(target)

        await ctx.send(f"Removed `{s.player.title}` from the queue.")

    @commands.command()
    async def remove(self, ctx, n: int):
        """Remove a specific song from the queue"""
        queue = ctx.state.queue._queue

        try:
            s = queue[n - 1]
        except IndexError:
            if n < 1:
                return await ctx.send("Song number cannot be negative or zero.")
            await ctx.send("Invalid song number. Check the queue for valid numbers.")

        if ctx.state.master and s.ctx.author != ctx.author:
            if ctx.state.master not in ctx.author.roles:
                return await ctx.send("You can only remove songs queued by yourself.")

        queue.remove(s)
        await ctx.send(f"Removed `{s.player.title}` from the queue.")

    @commands.command()
    async def notify(self, ctx, n: int):
        """Pings you when specified song comes on"""
        queue = ctx.state.queue._queue

        try:
            s = queue[n - 1]
        except IndexError:
            if n < 1:
                return await ctx.send("Song number cannot be negative or zero.")
            await ctx.send("Invalid song number. Check the queue for valid numbers.")

        s.notif.append(ctx.author.id)
        await ctx.send(f"Added you to `{s.player.title}`.")

    @master_only()
    @commands.command()
    async def volume(self, ctx, volume: int):
        """[M] Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"Changed volume to {volume}%")

    @master_only()
    @commands.command()
    async def stop(self, ctx):
        """[M] Stops and disconnects the bot from voice"""
        state = ctx.state
        async with ctx.typing():
            if not state.queue.empty():
                for _ in range(state.queue.qsize()):
                    state.queue.get_nowait()

        await ctx.send("<:blobstop:340118614848045076>")
        await ctx.voice_client.disconnect()


def setup(bot):
    bot.add_cog(Music(bot))
