import discord
from discord.ext import commands, tasks
import asyncio
import os
from dotenv import load_dotenv
import yt_dlp as youtube_dl
from async_timeout import timeout
import random

# Load environment variables
load_dotenv()

# Cấu hình yt-dlp với bypass YouTube mạnh hơn
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'age_limit': None,
    'geo_bypass': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web', 'ios'],
            'player_skip': ['webpage', 'configs'],
            'skip': ['hls', 'dash']
        }
    },
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -loglevel panic'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self._cog = ctx.cog

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()

        self.current = None
        self.volume = 0.5

        ctx.bot.loop.create_task(self.player_loop())

    def _after_playback(self, error):
        """Callback sau khi phát xong hoặc skip"""
        if error:
            print(f'Player error: {error}')
        self.bot.loop.call_soon_threadsafe(self.next.set)

    async def player_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()

            try:
                async with timeout(180):
                    source = await self.queue.get()
            except asyncio.TimeoutError:
                return self.destroy(self._guild)

            if not source:
                continue

            source.volume = self.volume
            self.current = source

            self._guild.voice_client.play(
                source, 
                after=lambda e: self._after_playback(e)
            )
            
            embed = discord.Embed(
                title="<:23347mambotongue:1459905486680883383> Đang Phát",
                description=f"[{source.title}]({source.webpage_url})",
                color=discord.Color.green()
            )
            if source.duration:
                mins, secs = divmod(source.duration, 60)
                embed.add_field(name="<a:7596clock:1459908088319443159> Thời lượng", value=f"{int(mins)}:{int(secs):02d}", inline=True)
            if source.uploader:
                embed.add_field(name="<a:38706playfulcat:1459909789814489302> Kênh", value=source.uploader, inline=True)
            
            # Hiển thị số bài còn lại trong queue
            remaining = self.queue.qsize()
            if remaining > 0:
                embed.add_field(name="<:6421bleb:1459905469836431411> Queue", value=f"{remaining} bài", inline=True)
                
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            
            await self._channel.send(embed=embed)

            await self.next.wait()
            
            # Cleanup source an toàn
            if self.current:
                try:
                    self.current.cleanup()
                except Exception as e:
                    # Bỏ qua lỗi cleanup
                    pass
                
            self.current = None

    def destroy(self, guild):
        return self.bot.loop.create_task(self._cog.cleanup(guild))

# Khởi tạo bot
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Danh sách các activity sẽ xoay vòng
activities = [
    {
        "type": discord.ActivityType.playing,
        "name": "nhạc | !help",
        "details": "Phát nhạc YouTube & SoundCloud"
    },
    {
        "type": discord.ActivityType.listening,
        "name": "!play | !sc",
        "details": "YouTube & SoundCloud"
    },
    {
        "type": discord.ActivityType.watching,
        "name": "{servers} servers | !menu",
        "details": "{users} người dùng"
    },
    {
        "type": discord.ActivityType.playing,
        "name": "Chit Chit",
        "details": "Music Bot"
    },
    {
        "type": discord.ActivityType.competing,
        "name": "Music Competition",
        "details": "Best Music Bot"
    }
]

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        
    async def update_presence(self):
        """Cập nhật trạng thái của bot"""
        # Lấy số liệu thống kê
        guild_count = len(self.bot.guilds)
        member_count = sum(g.member_count for g in self.bot.guilds)
        
        # Chọn activity ngẫu nhiên
        activity_data = random.choice(activities)
        
        # Thay thế placeholder
        activity_name = activity_data["name"].replace("{servers}", str(guild_count)).replace("{users}", str(member_count))
        
        # Tạo activity object
        if activity_data["type"] == discord.ActivityType.playing:
            activity = discord.Game(name=activity_name)
        elif activity_data["type"] == discord.ActivityType.listening:
            activity = discord.Activity(type=discord.ActivityType.listening, name=activity_name)
        elif activity_data["type"] == discord.ActivityType.watching:
            activity = discord.Activity(type=discord.ActivityType.watching, name=activity_name)
        elif activity_data["type"] == discord.ActivityType.competing:
            activity = discord.Activity(type=discord.ActivityType.competing, name=activity_name)
        else:
            activity = discord.Game(name=activity_name)
        
        # Đặt status và activity
        await self.bot.change_presence(
            status=discord.Status.online,
            activity=activity
        )
    
    @tasks.loop(seconds=30)  # Cập nhật mỗi 30 giây
    async def change_activity(self):
        """Thay đổi activity định kỳ"""
        await self.update_presence()
    
    @change_activity.before_loop
    async def before_change_activity(self):
        """Chờ bot ready trước khi bắt đầu loop"""
        await self.bot.wait_until_ready()

    async def cleanup(self, guild):
        try:
            # Dừng player hiện tại
            if guild.voice_client:
                if guild.voice_client.is_playing():
                    guild.voice_client.stop()
                await guild.voice_client.disconnect(force=False)
        except Exception as e:
            print(f"Cleanup error: {e}")

        try:
            del self.players[guild.id]
        except KeyError:
            pass

    def get_player(self, ctx):
        try:
            player = self.players[ctx.guild.id]
        except KeyError:
            player = MusicPlayer(ctx)
            self.players[ctx.guild.id] = player

        return player

    @commands.command(name='join', aliases=['j', 'connect'])
    async def join(self, ctx):
        """Bot join voice channel"""
        if not ctx.author.voice:
            return await ctx.send("<:874346wrong:1459906410975330325> Bạn phải ở trong voice channel!")

        channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()
        
        embed = discord.Embed(
            description=f"<a:736775redcheck:1459905519845376010> Đã join **{channel.name}**",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx, *, query):
        """Phát nhạc - Tự động thử nhiều nguồn"""
        if not ctx.voice_client:
            if not ctx.author.voice:
                return await ctx.send("<:874346wrong:1459906410975330325> Bạn phải ở trong voice channel!")
            await ctx.author.voice.channel.connect()

        search_msg = await ctx.send(f"<a:4428ghosticonload:1459905467852787878> Đang tìm kiếm: **{query}**...")

        async with ctx.typing():
            try:
                player = self.get_player(ctx)
                source = None
                
                # Nếu là link thì dùng trực tiếp
                if query.startswith('http'):
                    try:
                        source = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
                    except Exception as e:
                        await search_msg.edit(content=f"<:874346wrong:1459906410975330325> Lỗi khi tải từ link: {str(e)[:100]}")
                        return
                else:
                    # Thử nhiều nguồn theo thứ tự
                    sources_to_try = [
                        ('SoundCloud', f"scsearch:{query}"),
                        ('YouTube', f"ytsearch:{query}"),
                    ]
                    
                    for source_name, search_query in sources_to_try:
                        try:
                            await search_msg.edit(content=f"<a:4428ghosticonload:1459905467852787878> Đang thử {source_name}: **{query}**...")
                            source = await YTDLSource.from_url(search_query, loop=self.bot.loop, stream=True)
                            if source:
                                break
                        except Exception as e:
                            error_str = str(e).lower()
                            # Nếu bị chặn bot thì thử nguồn khác
                            if 'sign in' in error_str or 'bot' in error_str or 'cookies' in error_str:
                                continue
                            # Lỗi khác thì báo
                            if source_name == sources_to_try[-1][0]:  # Nguồn cuối cùng
                                await search_msg.edit(content="<:874346wrong:1459906410975330325> Không tìm thấy trên tất cả nguồn!")
                                return
                
                if not source:
                    await search_msg.edit(content="<:874346wrong:1459906410975330325> Không thể tải nhạc từ bất kỳ nguồn nào!")
                    return
                
                # Kiểm tra queue size TRƯỚC khi thêm
                queue_size = player.queue.qsize()
                
                await player.queue.put(source)
                await search_msg.delete()

                # Chỉ hiển thị "Đã thêm" nếu queue đã có bài
                if queue_size >= 1 or (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                    embed = discord.Embed(
                        title="<:104352add:1459907021653545062> Đã Thêm Vào Queue",
                        description=f"[{source.title}]({source.webpage_url})",
                        color=discord.Color.blue()
                    )
                    if source.duration:
                        mins, secs = divmod(source.duration, 60)
                        embed.add_field(name="<a:7596clock:1459908088319443159> Thời lượng", value=f"{int(mins)}:{int(secs):02d}", inline=True)
                    embed.add_field(name="<a:4403tsumikiblush:1460127978058022974> Vị trí", value=f"#{queue_size + 1}", inline=True)
                    embed.add_field(name="<a:38706playfulcat:1459909789814489302> Yêu cầu bởi", value=ctx.author.mention, inline=True)
                    if source.thumbnail:
                        embed.set_thumbnail(url=source.thumbnail)
                    
                    await ctx.send(embed=embed)
                
            except Exception as e:
                await search_msg.delete()
                error_msg = str(e)
                
                if "Sign in to confirm" in error_msg or "bot" in error_msg or "cookies" in error_msg:
                    embed = discord.Embed(
                        title="<a:816761transwaveforms:1459909819812020306> Không Thể Phát Nhạc",
                        description="Tất cả nguồn đều gặp vấn đề. Hãy thử:",
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="<:20133system:1459905480326643774> Giải pháp",
                        value="<a:4428ghosticonload:1459905467852787878> Dùng lệnh `!sc <tên bài>` cho SoundCloud\n<a:4428ghosticonload:1459905467852787878> Dùng link trực tiếp: `!p <link>`\n<a:4428ghosticonload:1459905467852787878> Thử lại sau vài phút",
                        inline=False
                    )
                    await ctx.send(embed=embed)
                else:
                    await ctx.send(f"<a:905900wagurihappy:1459905529760583895> Lỗi: {error_msg[:200]}")

    @commands.command(name='pause')
    async def pause(self, ctx):
        """Tạm dừng nhạc"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("<:9744spotifypause:1460127985465294869> Đã tạm dừng!")
        else:
            await ctx.send("<a:905900wagurihappy:1459905529760583895> Không có bài hát nào đang phát!")

    @commands.command(name='resume')
    async def resume(self, ctx):
        """Tiếp tục phát nhạc"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("<:2896spotifynext:1460127975151243537> Tiếp tục phát!")
        else:
            await ctx.send("<a:905900wagurihappy:1459905529760583895> Nhạc không bị tạm dừng!")

    @commands.command(name='skip', aliases=['s'])
    async def skip(self, ctx):
        """Skip bài hiện tại"""
        if not ctx.voice_client:
            return await ctx.send("<a:905900wagurihappy:1459905529760583895> Bot không ở trong voice channel!")
            
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            return await ctx.send("<a:905900wagurihappy:1459905529760583895> Không có bài hát nào đang phát!")

        player = self.get_player(ctx)
        
        # Kiểm tra còn bài trong queue không
        remaining = player.queue.qsize()
        
        # Stop bài hiện tại để trigger next song
        ctx.voice_client.stop()
        
        if remaining > 0:
            await ctx.send(f"<:2896spotifynext:1460127975151243537> Đã skip! Còn {remaining} bài trong queue.")
        else:
            await ctx.send("<:2896spotifynext:1460127975151243537> Đã skip! Queue trống.")

    @commands.command(name='volume', aliases=['vol'])
    async def volume(self, ctx, volume: int):
        """Chỉnh volume (0-100)"""
        if not ctx.voice_client:
            return await ctx.send("<a:905900wagurihappy:1459905529760583895> Bot không ở trong voice channel!")

        if 0 <= volume <= 100:
            player = self.get_player(ctx)
            player.volume = volume / 100
            if ctx.voice_client.source:
                ctx.voice_client.source.volume = volume / 100
            await ctx.send(f"<:7125spotifyvolume:1460127979836411915> Đã đặt volume: **{volume}%**")
        else:
            await ctx.send("<:7125spotifyvolume:1460127979836411915> Volume phải từ 0-100!")

    @commands.command(name='nowplaying', aliases=['np', 'current'])
    async def now_playing(self, ctx):
        """Xem bài đang phát"""
        player = self.get_player(ctx)

        if not player.current:
            return await ctx.send("<a:905900wagurihappy:1459905529760583895> Không có bài hát nào đang phát!")

        embed = discord.Embed(
            title="<a:49198online1:1459905430263300281> Đang Phát",
            description=f"[{player.current.title}]({player.current.webpage_url})",
            color=discord.Color.green()
        )
        if player.current.duration:
            mins, secs = divmod(player.current.duration, 60)
            embed.add_field(name="<a:7596clock:1459908088319443159> Thời lượng", value=f"{int(mins)}:{int(secs):02d}", inline=True)
        embed.add_field(name="<a:816761transwaveforms:1459909819812020306> Volume", value=f"{int(player.volume * 100)}%", inline=True)
        if player.current.thumbnail:
            embed.set_thumbnail(url=player.current.thumbnail)

        await ctx.send(embed=embed)

    @commands.command(name='queue', aliases=['q'])
    async def queue_info(self, ctx):
        """Xem queue"""
        player = self.get_player(ctx)
        
        if player.queue.empty() and not player.current:
            return await ctx.send("<a:905900wagurihappy:1459905529760583895> Queue trống!")

        embed = discord.Embed(
            title="<:8005spotifyqueueadd:1460127981740757248> Queue Nhạc",
            color=discord.Color.purple()
        )

        if player.current:
            embed.add_field(
                name="<a:49198online1:1459905430263300281> Đang phát",
                value=f"[{player.current.title}]({player.current.webpage_url})",
                inline=False
            )

        upcoming = list(player.queue._queue)
        if upcoming:
            queue_text = ""
            for i, song in enumerate(upcoming[:10], 1):
                queue_text += f"`{i}.` [{song.title}]({song.webpage_url})\n"
            
            if len(upcoming) > 10:
                queue_text += f"\n*...và {len(upcoming) - 10} bài khác*"
            
            embed.add_field(name="<:2896spotifynext:1460127975151243537> Tiếp theo", value=queue_text, inline=False)
            embed.set_footer(text=f"Tổng: {len(upcoming)} bài trong queue")

        await ctx.send(embed=embed)

    @commands.command(name='soundcloud', aliases=['sc'])
    async def soundcloud(self, ctx, *, query):
        """Tìm và phát nhạc từ SoundCloud"""
        if not ctx.voice_client:
            if not ctx.author.voice:
                return await ctx.send("<:874346wrong:1459906410975330325> Bạn phải ở trong voice channel!")
            await ctx.author.voice.channel.connect()

        search_msg = await ctx.send(f"<a:4428ghosticonload:1459905467852787878> Đang tìm trên SoundCloud: **{query}**...")

        async with ctx.typing():
            try:
                player = self.get_player(ctx)
                
                # Search trên SoundCloud
                search_query = f"scsearch:{query}" if not query.startswith('http') else query
                source = await YTDLSource.from_url(search_query, loop=self.bot.loop, stream=True)
                
                # Kiểm tra queue size TRƯỚC khi thêm
                queue_size = player.queue.qsize()
                
                await player.queue.put(source)
                await search_msg.delete()

                # Chỉ hiển thị nếu queue đã có bài
                if queue_size >= 1 or (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                    embed = discord.Embed(
                        title="<:104352add:1459907021653545062> Đã Thêm (SoundCloud)",
                        description=f"[{source.title}]({source.webpage_url})",
                        color=discord.Color.orange()
                    )
                    if source.duration:
                        mins, secs = divmod(source.duration, 60)
                        embed.add_field(name="<a:7596clock:1459908088319443159> Thời lượng", value=f"{int(mins)}:{int(secs):02d}", inline=True)
                    embed.add_field(name="<a:4403tsumikiblush:1460127978058022974> Vị trí", value=f"#{queue_size + 1}", inline=True)
                    embed.add_field(name="<a:38706playfulcat:1459909789814489302> Yêu cầu bởi", value=ctx.author.mention, inline=True)
                    if source.thumbnail:
                        embed.set_thumbnail(url=source.thumbnail)
                    
                    await ctx.send(embed=embed)
            except Exception as e:
                await search_msg.delete()
                await ctx.send(f"<a:905900wagurihappy:1459905529760583895> Lỗi SoundCloud: {str(e)}")

    @commands.command(name='spotify', aliases=['sp'])
    async def spotify_info(self, ctx):
        """Thông tin về Spotify"""
        embed = discord.Embed(
            title="<a:736775redcheck:1459905519845376010> Hỗ Trợ Spotify",
            description="Bot chưa hỗ trợ trực tiếp Spotify, nhưng bạn có thể:",
            color=discord.Color.green()
        )
        embed.add_field(
            name="<:47933cryingyt:1459909801327857737> Cách dùng",
            value="1 Tìm tên bài hát trên Spotify\n2 Dùng `!play <tên bài hát>`\n3 Hoặc dùng SoundCloud: `!sc <tên bài>`",
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name='leave', aliases=['dc', 'disconnect', 'stop'])
    async def leave(self, ctx):
        """Bot rời voice channel"""
        if not ctx.voice_client:
            return await ctx.send("<a:905900wagurihappy:1459905529760583895> Bot không ở trong voice channel!")

        await self.cleanup(ctx.guild)
        
        embed = discord.Embed(
            description="<a:905900wagurihappy:1459905529760583895> Đã rời voice channel!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    @commands.command(name='commands', aliases=['cmd', 'menu', 'lenh'])
    async def help_command(self, ctx):
        """Hiển thị tất cả lệnh"""
        embed = discord.Embed(
            title="<a:393380mymelodydance:1459909813969617142> Music Bot Commands",
            description="Bot phát nhạc YouTube & SoundCloud",
            color=discord.Color.gold()
        )
        
        commands_list = {
            "<a:816761transwaveforms:1459909819812020306> Phát nhạc": "`!play <tên/link>` hoặc `!p` - Tự động thử SoundCloud & YouTube\n`!soundcloud <tên/link>` hoặc `!sc` - Chỉ SoundCloud\n`!join` - Join voice\n`!leave` - Rời voice",
            "<:517009earlyverifiedbotdeveloperc:1459905513574633604> Điều khiển": "`!pause` - Tạm dừng\n`!resume` - Tiếp tục\n`!skip` hoặc `!s` - Skip bài\n`!volume <0-100>` - Chỉnh volume",
            "<:559950clipboard:1459909816742056172> Thông tin": "`!queue` hoặc `!q` - Xem queue\n`!nowplaying` hoặc `!np` - Bài đang phát",
            "<:3793othersexuality:1459909782679851050> Khác": "`!commands` hoặc `!menu` - Menu này\n`!spotify` - Info về Spotify"
        }
        
        for category, cmds in commands_list.items():
            embed.add_field(name=category, value=cmds, inline=False)
        
        embed.set_footer(text="Hỗ trợ: YouTube, SoundCloud | Prefix: !")
        await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'\n{"="*50}')
    print(f'✅ Bot đã đăng nhập: {bot.user.name}')
    
    # Cập nhật presence lần đầu
    music_cog = bot.get_cog('Music')
    if music_cog:
        await music_cog.update_presence()
        # Bắt đầu loop thay đổi activity
        music_cog.change_activity.start()
    
    print('✅ Bot Start\n')

@bot.event
async def on_guild_join(guild):
    """Khi bot join vào server mới"""
    # Cập nhật activity
    music_cog = bot.get_cog('Music')
    if music_cog:
        await music_cog.update_presence()

@bot.event
async def on_guild_remove(guild):
    """Khi bot bị remove khỏi server"""
    # Cập nhật activity
    music_cog = bot.get_cog('Music')
    if music_cog:
        await music_cog.update_presence()

async def main():
    token = os.getenv('DISCORD_TOKEN')
    
    if not token:
        print("❌ Không tìm thấy DISCORD_TOKEN!")
        print("Tạo file .env và thêm: DISCORD_TOKEN=your_token_here")
        return
    
    async with bot:
        await bot.add_cog(Music(bot))
        print("🚀 Đang khởi động bot với activity...")
        await bot.start(token)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Bot đã tắt!")
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")