from collections import namedtuple
from copy import copy
from datetime import datetime, timedelta
import logging
import re

import discord
import typing
from discord.ext import tasks
from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import box

logger = logging.getLogger("red.RedAppsv2.reposts")


class RepostData:
    def __init__(self, url: str, data: list):
        self.url = url
        self._raw = data

    @property
    def data(self):
        return self.get_data()

    def get_data(self):
        RepostSeen = namedtuple('RepostSeen', ('message', 'jump_url', 'author', 'timestamp'))
        formatted = []
        for k in self._raw:
            formatted.append(RepostSeen(**k))
        return formatted


class Reposts(commands.Cog):
    """Détecteur de reposts"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'whitelist': {'users': [],
                                        'channels': [],
                                        'roles': [],
                                        'links_greedy': [],
                                        'links_lazy': []},
                         'autodelete': {'greedy': [],
                                        'lazy': []},
                         'delete_after': False,
                         'cache': {},

                         'toggled': False}
        self.config.register_guild(**default_guild)

        self.repost_emoji = self.bot.get_emoji(812380539319091230)
        self.reposts_cache_clear.start()

    @tasks.loop(hours=12)
    async def reposts_cache_clear(self):
        await self.clear_reposts_cache()

    @reposts_cache_clear.before_loop
    async def before_reposts_loop(self):
        logger.info('Starting reposts loop...')
        await self.bot.wait_until_ready()

    async def clear_reposts_cache(self):
        all_guilds = await self.config.all_guilds()
        for g in all_guilds:
            cache = all_guilds[g]['cache']
            new = copy(cache)
            for url in cache:
                for k in cache[url]:
                    if datetime.now().fromisoformat(k['timestamp']) < datetime.now() - timedelta(days=14):
                        new[url].remove(k)
                if not cache[url]:
                    del new[url]
            if cache != new:
                await self.config.guild_from_id(g).cache.set(new)

    async def is_whitelisted(self, message: discord.Message, link: str):
        author, channel = message.author, message.channel
        wl = await self.config.guild(message.guild).whitelist()
        if author.id in wl["users"] or channel.id in wl["channels"]:
            return True
        elif [r for r in wl["roles"] if r in [n.id for n in author.roles]]:
            return True

        if link in wl["links_greedy"]:
            return True
        elif [l for l in wl["links_lazy"] if link.startswith(l)]:
            return True
        return False

    def canon_link(self, link: str):
        is_yt = re.compile(r'https://www\.youtube\.com/watch\?v=([\w\-]*)', re.DOTALL | re.IGNORECASE).findall(
            link)
        if is_yt:
            return "https://youtu.be/{}".format(is_yt[0])
        is_tw = re.compile(r'https://twitter\.com/(?:\w*)/status/(\d*)', re.DOTALL | re.IGNORECASE).findall(link)
        if is_tw:
            return "https://twitter.com/u/status/{}".format(is_tw[0])
        return link

    async def get_repost_by_message(self, message: discord.Message):
        guild = message.guild
        reposts = await self.config.guild(guild).cache()
        for url in reposts:
            for k in reposts[url]:
                if k['message'] == message.id:
                    return RepostData(url, reposts[url])

    @commands.group(name="reposts")
    @checks.admin_or_permissions(manage_messages=True)
    @commands.guild_only()
    async def _reposts(self, ctx):
        """Paramètres du détecteur de reposts"""

    @_reposts.command()
    async def toggle(self, ctx):
        """Active/désactive la détection de reposts de liens"""
        guild = ctx.guild
        if not await self.config.guild(guild).toggled():
            await self.config.guild(guild).toggled.set(True)
            await ctx.send("**Activé** • Le détecteur de reposts de liens est activé.")
        else:
            await self.config.guild(guild).toggled.set(False)
            await ctx.send("**Désactivé** • Le détecteur de reposts de liens est désactivé.")

    @_reposts.command(hidden=True, name="reset")
    async def repost_reset(self, ctx):
        """Reset les données du cache"""
        guild = ctx.guild
        await self.config.guild(guild).clear_raw('cache')
        await ctx.send("**Reset effectué avec succès**")

    @_reposts.command(name="deleteafter")
    async def delete_after(self, ctx, delay: int = -1):
        """Définir un délai après lequel les reposts sont supprimés

        Mettre -1 désactive la suppression"""
        guild = ctx.guild
        if delay >= 0:
            await self.config.guild(guild).delete_after.set(delay)
            await ctx.send(f"**Délai de suppression configuré** • Les reposts détectés seront supprimés aprèsn {delay} secondes.")
        else:
            await self.config.guild(guild).delete_after.set(False)
            await ctx.send(
                f"**Délai de suppression retiré** • Les reposts détectés ne seront plus supprimés.")
 
    @commands.command()
    async def autodelete(self, ctx, lien: str = None):
        """Ajouter/retirer une URL à blacklister
        
        Ne rien mettre affiche une liste
        Mettre * à la fin de l'URL signifie que tous les URL commençant par votre texte seront supprimés automatiquement"""
        guild = ctx.guild
        links = await self.config.guild(guild).autodelete()
        if lien:
            if '*' in lien:
                lien = lien.replace('*', '')
                if lien not in links['lazy']:
                    links['lazy'].append(lien)
                    await ctx.send(f"**Lien ajouté** • Les liens commençant par `{lien}` seront automatiquement supprimés.")
                else:
                    links['lazy'].remove(lien)
                    await ctx.send(f"**Lien retiré** • Les liens commençant par `{lien}` ne seront plus automatiquement supprimés.")
            elif lien in links['greedy']:
                links['greedy'].remove(lien)
                await ctx.send(f"**Lien retiré** • Le lien `{lien}` ne sera plus supprimé automatiquement.")
            elif lien not in links['greedy']:
                links['greedy'].append(lien)
                await ctx.send(f"**Lien ajouté** • Le lien `{lien}` sera désormais supprimé automatiquement.")
            else:
                await ctx.send(f"**Commande invalide** : réessayez.")
            await self.config.guild(guild).autodelete.set(links)
        else:
            txt = ""
            for l in links['greedy']:
                txt += f"- `{l}`\n"
            for m in links['lazy']:
                txt += f"- `{m}*`\n"
            txt = txt if txt else "Aucune autosuppression de lien n'a été configurée"
            em = discord.Embed(title="Liens à supprimer automatiquement", description=txt)
            await ctx.send(embed=em)

    @_reposts.group(name="whitelist")
    async def reposts_whitelist(self, ctx):
        """Paramètres concernant l'immunité au détecteur de reposts (whitelist)"""

    @reposts_whitelist.command()
    async def user(self, ctx, user: discord.Member):
        """Ajouter ou retirer une immunité pour un membre"""
        guild = ctx.guild
        wl = await self.config.guild(guild).whitelist()
        if user.id not in wl['users']:
            wl['users'].append(user.id)
            await self.config.guild(guild).whitelist.set(wl)
            await ctx.send(f"**Ajouté à la whitelist** • {user.name} est désormais immunisé au détecteur de reposts.")
        else:
            wl['users'].remove(user.id)
            await self.config.guild(guild).whitelist.set(wl)
            await ctx.send(
                f"**Retiré de la whitelist** • {user.name} n'est désormais plus immunisé au détecteur de reposts.")

    @reposts_whitelist.command()
    async def channel(self, ctx, channel: discord.TextChannel):
        """Ajouter ou retirer une immunité pour un salon écrit"""
        guild = ctx.guild
        wl = await self.config.guild(guild).whitelist()
        if channel.id not in wl['channels']:
            wl['channels'].append(channel.id)
            await self.config.guild(guild).whitelist.set(wl)
            await ctx.send(f"**Ajouté à la whitelist** • Les reposts postés dans #{channel.name} ne seront plus signalés.")
        else:
            wl['channels'].remove(channel.id)
            await self.config.guild(guild).whitelist.set(wl)
            await ctx.send(f"**Retiré de la whitelist** • Les reposts postés dans #{channel.name} seront de nouveau signalés.")

    @reposts_whitelist.command()
    async def role(self, ctx, role: discord.Role):
        """Ajouter ou retirer une immunité pour un rôle (donc les membres possédant ce rôle)"""
        guild = ctx.guild
        wl = await self.config.guild(guild).whitelist()
        if role.id not in wl['roles']:
            wl['roles'].append(role.id)
            await self.config.guild(guild).whitelist.set(wl)
            await ctx.send(
                f"**Ajouté à la whitelist** • Les membres ayant le rôle {role.name} sont désormais immunisés.")
        else:
            wl['roles'].remove(role.id)
            await self.config.guild(guild).whitelist.set(wl)
            await ctx.send(
                f"**Retiré de la whitelist** • Les membres avec le rôle {role.name} ne sont plus immunisés.")

    @reposts_whitelist.command()
    async def link(self, ctx, lien: str):
        """Ajouter ou retirer l'immunité pour un lien, strictement ou non

        Si vous ajoutez une étoile à la fin du lien, ce sera tous les liens commençant par ce qu'il y a avant l'étoile qui ne seront pas comptés comme reposts
        __Exemples :__
        `;repost immune link https://discord.me/qqchose` => immunise seulement le lien `https://discord.me/qqchose`
        `;repost immune link https://discord.me/*` => immunise tous les liens commençant par `https://discord.me/`"""
        guild = ctx.guild
        wl = await self.config.guild(guild).whitelist()
        if lien == "https://www.youtube.com/*":
            lien = "https://youtu.be/*"

        if lien.endswith("*"):
            lien = lien[:-1]
            if lien not in wl['links_lazy']:
                wl['links_lazy'].append(lien)
                await self.config.guild(guild).whitelist.set(wl)
                await ctx.send(
                    f"**Whitelisté** • Les liens commençant par `{lien}` ne seront plus comptés comme des reposts.")
            else:
                wl['links_lazy'].remove(lien)
                await self.config.guild(guild).whitelist.set(wl)
                await ctx.send(
                    f"**Retiré de la whitelist** • Les liens commençant par `{lien}` ne sont plus immunisés.")
        else:
            if lien not in wl['links_greedy']:
                wl['links_greedy'].append(lien)
                await self.config.guild(guild).whitelist.set(wl)
                await ctx.send(
                    f"**Whitelisté** • Le lien `{lien}` ne pourra plus figurer dans les reposts.")
            else:
                wl['links_greedy'].remove(lien)
                await self.config.guild(guild).whitelist.set(wl)
                await ctx.send(
                    f"**Retiré de la whitelist** • Le lien `{lien}` n'est plus immunisé aux reposts.")

    @reposts_whitelist.command(name="list")
    async def immune_list(self, ctx):
        """Liste les éléments immunisés contre le détecteur de reposts"""
        guild = ctx.guild
        em = discord.Embed(title="Elements immunisés contre le détecteur de reposts", color=await ctx.embed_color())
        wl = await self.config.guild(guild).whitelist()
        if wl['users']:
            txt = ""
            for u in wl['users']:
                user = guild.get_member(u)
                txt += f"- {user.mention}\n"
            em.add_field(name="Membres", value=txt)
        if wl['roles']:
            txt = ""
            for r in wl['roles']:
                role = guild.get_role(r)
                txt += f"- {role.mention}\n"
            em.add_field(name="Rôles", value=txt)
        if wl['channels']:
            txt = ""
            for c in wl['channels']:
                channel = guild.get_channel(c)
                txt += f"- {channel.mention}\n"
            em.add_field(name="Salons écrits", value=txt)
        links = ""
        if wl['links_greedy']:
            for l in wl['links_greedy']:
                links += f"- `{l}`\n"
        if wl['links_lazy']:
            for l in wl['links_lazy']:
                links += f"- `{l}*`\n"
        if links:
            em.add_field(name="Liens", value=links)
            em.set_footer(text="* = Liens commençant par ...")
        await ctx.send(embed=em)

    @commands.command(name="links")
    async def disp_links(self, ctx, nb: typing.Optional[int] = 10, *, contain: str = None):
        """Affiche les X derniers liens détectés (reposts ou non)

        Il est possible de préciser un morceau de texte qui doit être contenu dans les liens recherchés"""
        guild = ctx.guild
        data = await self.config.guild(guild).cache()
        links = {}
        for url in data:
            if contain:
                if contain not in url.lower():
                    continue
            if data[url]:
                links[url] = datetime.now().fromisoformat(data[url][-1]['timestamp']).timestamp()

        if links:
            txt = ""
            for u in sorted(links, key=links.get, reverse=True)[:nb]:
                txt += f"• <{u}>\n"

            if contain:
                em = discord.Embed(title=f"{nb} Derniers liens postés contenant \"{contain}\"", description=txt,
                                   color=await self.bot.get_embed_color(ctx.channel))
            else:
                em = discord.Embed(title=f"{nb} Derniers liens postés", description=txt,
                                   color=await self.bot.get_embed_color(ctx.channel))
            em.set_footer(text="Données des 14 derniers jours seulement")
            await ctx.send(embed=em)
        else:
            await ctx.send(
                f"**Liste vide** • Aucun lien conforme à votre recherche n'a été posté récemment.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            scan = None
            guild = message.guild
            if await self.config.guild(guild).toggled():
                content = message.content
                if "http" in content:
                    scan = re.compile(r'(https?://\S*\.\S*)', re.DOTALL | re.IGNORECASE).findall(content)
                    if scan:
                        url = self.canon_link(scan[0])
                        if await self.is_whitelisted(message, url):
                            return
                        if message.author == self.bot.user:
                            return

                        r = {'message': message.id, 'jump_url': message.jump_url, 'author': message.author.id,
                             'timestamp': datetime.now().isoformat()}
                        if url in await self.config.guild(guild).cache():
                            repost = await self.config.guild(guild).cache.get_raw(url)
                            repost.append(r)
                            await self.config.guild(guild).cache.set_raw(url, value=repost)

                            dafter = await self.config.guild(guild).delete_after()
                            if dafter:
                                try:
                                    await message.delete(delay=dafter)
                                except:
                                    raise discord.DiscordException(f"Impossible de supprimer le message {message.id}")
                            else:
                                try:
                                    await message.add_reaction(self.repost_emoji)
                                except:
                                    raise discord.DiscordException(f"Impossible d'ajouter un emoji au message {message.id}")
                        else:
                            await self.config.guild(guild).cache.set_raw(url, value=[r])
                            
            autodel = await self.config.guild(guild).autodelete()
            if autodel['lazy'] or autodel['greedy']:
                if not scan:
                    scan = re.compile(r'(https?://\S*\.\S*)', re.DOTALL | re.IGNORECASE).findall(content)
                if scan:
                    for url in scan:
                        if url in autodel['greedy'] or [l for l in autodel['lazy'] if url.startswith(l)]:
                            try:
                                await message.delete()
                            except:
                                 raise discord.DiscordException(f"Impossible de supprimer le message {message.id}")
                

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        channel = self.bot.get_channel(payload.channel_id)
        emoji = payload.emoji
        if hasattr(channel, "guild"):
            guild = channel.guild
            data = await self.config.guild(guild).all()
            if data["toggled"] and emoji == self.repost_emoji:
                message = await channel.fetch_message(payload.message_id)
                user = guild.get_member(payload.user_id)
                if user == self.bot.user:
                    return

                rdata = await self.get_repost_by_message(message)
                if rdata:
                    txt = ""
                    repost = rdata.data
                    em = discord.Embed(title=f"{self.repost_emoji} Liste des reposts",
                                       description=box(rdata.url),
                                       color=await self.bot.get_embed_color(message.channel))
                    em.set_footer(text="Données des 14 derniers jours")
                    chunk = repost[1:] if len(repost) <= 9 else repost[-9:]

                    r = repost[0]
                    ts = datetime.now().fromisoformat(r.timestamp).strftime('%d/%m/%Y %H:%M')
                    author = guild.get_member(r.author)
                    author = f"**{author.name}**#{author.discriminator}" if author else f"ID: {r.author}"
                    em.add_field(name="Premier post", value=f"[Le {ts}]({r.jump_url}) par {author}",
                                 inline=False)
                    for s in chunk:
                        ts = datetime.now().fromisoformat(s.timestamp).strftime('%d/%m/%Y %H:%M')
                        author = guild.get_member(s.author)
                        author = f"**{author.name}**#{author.discriminator}" if author else f"ID: {s.author}"
                        txt += f"• [Le {ts}]({s.jump_url}) par {author}\n"

                    em.add_field(name="Re-posts", value=txt, inline=False)
                    try:
                        await user.send(embed=em)
                    except:
                        raise
                    else:
                        await message.remove_reaction(self.repost_emoji, user)
