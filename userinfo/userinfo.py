import asyncio
from copy import copy
from datetime import datetime, timedelta
from typing import Union

import aiohttp
import discord
import logging

from urllib import parse
import requests
from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.userinfo")


ACTIVITY_TYPES = {
    discord.ActivityType.playing: "Joue",
    discord.ActivityType.watching: "Regarde",
    discord.ActivityType.listening: "Écoute",
    discord.ActivityType.streaming: "Diffuse"
}

STATUS_COLORS = {
    discord.Status.online: 0x40AC7B,
    discord.Status.idle: 0xFAA61A,
    discord.Status.dnd: 0xF04747,
    discord.Status.offline: 0x747F8D
}


def is_streaming(user: discord.Member):
    if user.activities:
        return any([activity.type is discord.ActivityType.streaming for activity in user.activities])
    return False


def handle_custom(user):
    a = [c for c in user.activities if c.type == discord.ActivityType.custom]
    if not a:
        return None, discord.ActivityType.custom
    a = a[0]
    c_status = None
    if not a.name and not a.emoji:
        return None, discord.ActivityType.custom
    elif a.name and a.emoji:
        c_status = "{emoji} {name}".format(emoji=a.emoji, name=a.name)
    elif a.emoji:
        c_status = "{emoji}".format(emoji=a.emoji)
    elif a.name:
        c_status = "{name}".format(name=a.name)
    return c_status, discord.ActivityType.custom


def handle_playing(user):
    p_acts = [c for c in user.activities if c.type == discord.ActivityType.playing]
    if not p_acts:
        return None, discord.ActivityType.playing
    p_act = p_acts[0]
    act = "» Joue à {name}".format(name=p_act.name)
    return act, discord.ActivityType.playing


def handle_streaming(user):
    s_acts = [c for c in user.activities if c.type == discord.ActivityType.streaming]
    if not s_acts:
        return None, discord.ActivityType.streaming
    s_act = s_acts[0]
    if isinstance(s_act, discord.Streaming):
        act = "» Diffuse [{name}{sep}{game}]({url})".format(
            name=discord.utils.escape_markdown(s_act.name),
            sep=" | " if s_act.game else "",
            game=discord.utils.escape_markdown(s_act.game) if s_act.game else "",
            url=s_act.url,
        )
    else:
        act = "» Diffuse {name}".format(name=s_act.name)
    return act, discord.ActivityType.streaming


def handle_listening(user):
    l_acts = [c for c in user.activities if c.type == discord.ActivityType.listening]
    if not l_acts:
        return None, discord.ActivityType.listening
    l_act = l_acts[0]
    if isinstance(l_act, discord.Spotify):
        act = "» Écoute [{title}{sep}{artist}]({url})".format(
            title=discord.utils.escape_markdown(l_act.title),
            sep=" | " if l_act.artist else "",
            artist=discord.utils.escape_markdown(l_act.artist) if l_act.artist else "",
            url=f"https://open.spotify.com/track/{l_act.track_id}",
        )
    else:
        act = "» Écoute {title}".format(title=l_act.name)
    return act, discord.ActivityType.listening


def handle_watching(user):
    w_acts = [c for c in user.activities if c.type == discord.ActivityType.watching]
    if not w_acts:
        return None, discord.ActivityType.watching
    w_act = w_acts[0]
    act = "» Regarde {name}".format(name=w_act.name)
    return act, discord.ActivityType.watching


def get_status_string(user):
    string = ""
    for a in [
        handle_custom(user),
        handle_playing(user),
        handle_listening(user),
        handle_streaming(user),
        handle_watching(user),
    ]:
        status_string, status_type = a
        if status_string is None:
            continue
        string += f"{status_string}\n"
    return string

def shorten_link(link: str):
    key = 'a202f4f51e7d72c5826e2fcf649e6c3cc58e1'
    url = parse.quote(link)
    r = requests.get('http://cutt.ly/api/api.php?key={}&short={}'.format(key, url))
    result = r.json()['url']
    if result['status'] == 7:
        return result['shortLink']
    else:
        return None

class UserInfo(commands.Cog):
    """Informations sur les membres"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {'names': [],
                          'nicks': [],
                          'on_fire': {'last_seen': None,
                                      'cons_days': 0},
                          'logs': [],
                          'bio': ""}
        default_guild = {'user_records': {}}
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

        self.update_adv = {}

    async def append_logs(self, user: discord.Member, desc: str):
        member = self.config.member(user)
        async with member.logs() as logs:
            logs.append((datetime.utcnow().isoformat(), desc))
            if len(logs) > 10:
                await member.logs.set(logs[-10:])

    @commands.group(name='card', aliases=['c'], invoke_without_command=True)
    @commands.guild_only()
    async def user_card_commands(self, ctx, user: discord.Member = None):
        """Affichage et gestion de la carte de membre"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.display_user_card, user=user)

    @user_card_commands.command(name='get')
    @commands.bot_has_permissions(embed_links=True, manage_messages=True)
    async def display_user_card(self, ctx, user: Union[discord.Member, discord.User] = None):
        """Afficher un récapitulatif des informations d'un membre sous forme de carte de membre"""
        menu = None
        page = '📊'
        all_pages = ['📊', '📃', '👤', '🖼️']
        pages_footer = ['Infos', 'Logs', 'Bio', 'Avatar']
        user = user if user else ctx.author
        guild = ctx.guild

        if isinstance(user, discord.Member):
            base_title = user.name if not user.nick else f"{user.name} « {user.nick} »"
            userinfo = await self.config.member(user).all()
        else:
            base_title = user.name
            userinfo = await self.config.member_from_ids(guild.id, user.id).all()
        guild_records = await self.config.guild(guild).user_records()
        embed_color = STATUS_COLORS[user.status] if not is_streaming(user) else 0x6438AA

        while True:
            if page == '📊':  # INFOS
                title = base_title + " • *Infos*"
                try:
                    created_since, joined_since = (datetime.now() - user.created_at).days, \
                                                  (datetime.now() - user.joined_at).days
                    booster_since = (datetime.now() - user.premium_since).days if user.premium_since else False
                    voice_channel = user.voice.channel.mention if user.voice else None

                    try:
                        recorded = datetime.now().fromisoformat(guild_records[str(user.id)])
                    except KeyError:
                        recorded = user.joined_at
                    if recorded > user.joined_at:
                        recorded = user.joined_at
                except Exception as e:
                    logger.info(msg=e, exc_info=False)
                    em = discord.Embed(title=title, description=get_status_string(user), color=embed_color)
                    em.set_thumbnail(url=user.avatar_url)
                    created_since = (datetime.now() - user.created_at).days
                    em.add_field(name='Création',
                                 value=box("{} ({}j)".format(user.created_at.strftime("%d/%m/%Y"), created_since)))
                    em.add_field(name='Arrivée',
                                 value=box("Aucune donnée"))
                    try:
                        recorded = datetime.now().fromisoformat(guild_records[str(user.id)])
                    except KeyError:
                        em.add_field(name='1re Apparition',
                                     value=box("Aucune donnée"))
                    else:
                        em.add_field(name='1re Apparition',
                                     value=box("{} ({}j)".format(recorded.strftime("%d/%m/%Y"),
                                                                 (datetime.now() - recorded).days)))

                    on_fire, last_seen_data = userinfo['on_fire']['cons_days'], userinfo['on_fire']['last_seen']
                    last_seen = datetime.strptime(last_seen_data, '%Y.%m.%d').strftime('%d/%m/%Y') if last_seen_data else "Jamais"
                    em.add_field(name='Dernier message', value=box(f"{last_seen} [🔥X]"))
                else:
                    on_fire, last_seen_data = userinfo['on_fire']['cons_days'], userinfo['on_fire']['last_seen']
                    last_seen = datetime.strptime(last_seen_data, '%Y.%m.%d').strftime(
                        '%d/%m/%Y') if last_seen_data else "Jamais"

                    em = discord.Embed(title=title, description=get_status_string(user), color=embed_color)
                    em.set_thumbnail(url=user.avatar_url)
                    em.add_field(name='Création',
                                 value=box("{} ({}j)".format(user.created_at.strftime("%d/%m/%Y"), created_since)))
                    em.add_field(name='Arrivée',
                                 value=box("{} ({}j)".format(user.joined_at.strftime("%d/%m/%Y"), joined_since)))
                    em.add_field(name='1re Apparition',
                                 value=box("{} ({}j)".format(recorded.strftime("%d/%m/%Y"),
                                                             (datetime.now() - recorded).days)))
                    em.add_field(name='Dernier message', value=box("{} → 🔥{}".format(last_seen, on_fire)))

                    if booster_since:
                        em.add_field(name='Boost',
                                     value=box("{} ({}j)".format(user.premium_since.strftime("%d/%m/%Y"),
                                                                 booster_since)))

                    roles = user.roles[-1:0:-1]
                    if roles:
                        long, txt = 0, ""
                        for r in roles:
                            chunk = f"{r.mention} "
                            if long + len(chunk) > 1000:  # Pour les serveurs qui ont 300 rôles là
                                txt += "..."
                                break
                            txt += chunk
                            long += len(chunk)
                        em.add_field(name="Rôles possédés", value=txt, inline=False)

                    if voice_channel:
                        em.add_field(name="En vocal sur", value=voice_channel, inline=False)

            elif page == '📃':  # LOGS
                title = base_title + " • *Logs*"
                em = discord.Embed(title=title, color=embed_color)
                logs = userinfo['logs'][::-1]
                if logs:
                    tabl = []
                    for log in logs:
                        date = datetime.now().fromisoformat(log[0])
                        if date.date() == datetime.now().date():
                            timestring = "À l'instant" if date.strftime("%H:%M") == datetime.now().strftime("%H:%M") \
                                else f"Aujourd'hui à {date.strftime('%H:%M')}"
                            tabl.append((timestring, log[1]))
                        else:
                            tabl.append((date.strftime("%d/%m/%Y"), log[1]))
                    em.add_field(name="Logs des actions", value=box(tabulate(tabl, headers=["Date", "Action"])),
                                 inline=False)

                names, nicknames = userinfo["names"][::-1], userinfo["nicks"][::-1]
                if names:
                    em.add_field(name="Pseudos", value=box(", ".join(names[:5])))
                if nicknames:
                    em.add_field(name="Surnoms", value=box(", ".join(nicknames[:5])))

            elif page == '👤':
                title = base_title + " • *Bio*"
                desc = userinfo['bio'] if userinfo['bio'] else "**Description vide.**"
                em = discord.Embed(title=title, description=desc, color=embed_color)

            else:
                title = base_title + " • *Avatar*"
                avatar_url = str(user.avatar_url_as(size=1024))
                em = discord.Embed(title=title, color=embed_color, description="<" + avatar_url + ">")
                em.set_image(url=avatar_url)

            emojis, footer = copy(all_pages), copy(pages_footer)
            i = emojis.index(page)
            emojis.remove(page)
            footer.remove(footer[i])
            footer = ' · '.join(footer)

            em.set_footer(text=footer + f" | ID: {user.id}")

            if not menu:
                menu = await ctx.send(embed=em)
            else:
                await menu.edit(embed=em)

            start_adding_reactions(menu, emojis)
            try:
                react, ruser = await self.bot.wait_for("reaction_add",
                                                      check=lambda m, u: u == ctx.author and m.message.id == menu.id,
                                                      timeout=60)
            except asyncio.TimeoutError:
                await menu.clear_reactions()
                em.set_footer(text=f"ID: {user.id}")
                await menu.edit(embed=em)
                return
            else:
                page = react.emoji
                await menu.clear_reactions()

    @user_card_commands.command(name='bio')
    async def edit_user_bio(self, ctx, *text: str):
        """Modifier la bio de sa carte de membre

        Ne rien mettre permet de l'effacer"""
        if text:
            text = ' '.join(text)
            if len(text) > 2000:
                return await ctx.send("**Trop long** › Votre bio ne doit pas dépasser 2000 caractères.")
            await self.config.member(ctx.author).bio.set(text)
            await ctx.send("**Bio modifiée** › Elle s'affichera dans votre carte de membre dans la page correspondante")
        else:
            await self.config.member(ctx.author).bio.set("")
            await ctx.send("**Bio supprimée** › Votre bio a été réinitialisée")

    @commands.command(name="freshmeat")
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def disp_freshmeat(self, ctx, days: int = 0):
        """Afficher les derniers arrivés dans les X derniers jours (par défaut 0 -> aujourd'hui)"""
        members = ctx.guild.members
        l = ""
        pa = 1
        for member in members:
            if (datetime.now() - member.joined_at).days <= days:
                c = f"• {member}\n"
                if len(l + c) > 2000:
                    em = discord.Embed(title=f"Membres arrivés récemment (<= {days} jours)", description=l)
                    await ctx.send(embed=em)
                    l = c
                    pa += 1
                else:
                    l += c
        if l:
            em = discord.Embed(title=f"Membres arrivés récemment (<= {days} jours)", description=l)
            em.set_footer(text=f"Page n°{pa}")
            await ctx.send(embed=em)
        else:
            em = discord.Embed(title=f"Membres arrivés récemment (<= {days} jours)", description="**Aucun**")
            await ctx.send(embed=em)

    @commands.command(name="updateall")
    @checks.mod_or_permissions(administrator=True)
    @commands.bot_has_permissions(read_message_history=True)
    @commands.max_concurrency(1, commands.BucketType.guild)
    async def update_card_stats(self, ctx, days: int = 0):
        """Met à jour, du mieux que possible, les statistiques des membres rétroactivement (sur ce salon uniquement)

        <days> = Nombre de jours à regarder, par défaut tout ceux accessible (0)"""
        after = None
        members = {}
        await ctx.send(
            "📈 **Mise à jour des stats.** • Ce processus peut mettre plusieurs heures si le volume de messages est important (> 1 million)")
        if days > 0:
            after = datetime.today() - timedelta(days=days)
        n = 0
        self.update_adv[ctx.channel.id] = 1
        first = False
        try:
            async for message in ctx.channel.history(limit=None, after=after, oldest_first=True):
                if not first:
                    await ctx.send(f"📈 **Message de départ** : {message.content} "
                                   f"[{message.created_at.strftime('%d/%m/%Y %H:%M')}]")
                    first = True
                try:
                    author = message.author
                    if author.id not in members:
                        members[author.id] = message.created_at.isoformat()
                except:
                    pass
                n += 1
                if n / 1000 > 1:
                    self.update_adv[ctx.channel.id] = n

        except discord.Forbidden:
            return await ctx.send("Je n'ai pas accès à tous les messages demandés")
        except discord.HTTPException:
            return await ctx.send("Une erreur Discord m'empêche de continuer la mise à jour des statistiques")

        if members:
            records = await self.config.guild(ctx.guild).user_records()
            for member in members:
                records[member] = members[member]
            await self.config.guild(ctx.guild).user_records.set(records)
            await ctx.send("📈 **Mise à jour des stats.** • Réussie")
            del self.update_adv[ctx.channel.id]
        else:
            await ctx.send("📈 **Mise à jour des stats.** • Echec (aucune donnée n'a été traitée)")

    @commands.command(name="updateallinfo")
    async def update_stats_info(self, ctx):
        """Affiche des infos sur l'état d'avancement de la mise à jour des stats en cours"""
        if ctx.channel.id in self.update_adv:
            info = self.update_adv[ctx.channel.id]
            await ctx.send(f"📈 **Avancement de la MAJ des stats.** • {info} messages traités sur ce salon")
        else:
            await ctx.send(f"Aucune mise à jour n'a lieue sur ce salon")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            author = message.author
            today = datetime.now().strftime('%Y.%m.%d')
            yester = (datetime.now() - timedelta(days=1)).strftime('%Y.%m.%d')
            if isinstance(author, discord.Member):
                firedata = await self.config.member(author).on_fire()
                on_fire = copy(firedata)
                if on_fire['last_seen'] == yester:
                    on_fire['cons_days'] += 1
                elif on_fire['last_seen'] != today:
                    on_fire['cons_days'] = 0
                on_fire['last_seen'] = today

                if on_fire != firedata:
                    await self.config.member(author).on_fire.set(on_fire)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if isinstance(after, discord.Member):
            if after.display_name != before.display_name:
                if after.display_name == after.name:
                    await self.append_logs(after, f"A retiré son surnom ({before.nick})")
                else:
                    await self.append_logs(after, f"Changement de surnom › {after.display_name}")
                    async with self.config.member(after).nicknames() as nicknames:
                        if after.nick not in nicknames:
                            nicknames.append(after.nick)
                            if len(nicknames) > 5:
                                await self.config.member(after).nicknames.set(nicknames[-5:])

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        if isinstance(after, discord.Member):
            if after.name != before.name:
                await self.append_logs(after, f"Changement de pseudo › {after.name}")
                async with self.config.member(after).names() as names:
                    if after.name not in names:
                        names.append(after.name)
                        if len(names) > 5:
                            await self.config.member(after).names.set(names[-5:])

            if after.avatar_url != before.avatar_url:
                url = before.avatar_url.split("?")[0]
                await self.append_logs(after, f"Changement d'avatar › {shorten_link(url)}")

    @commands.Cog.listener()
    async def on_member_join(self, user):
        await self.append_logs(user, "A rejoint le serveur")
        records = await self.config.guild(user.guild).user_records()
        if user.id not in records:
            await self.config.guild(user.guild).user_records.set_raw(user.id, value=datetime.utcnow().isoformat())

    @commands.Cog.listener()
    async def on_member_remove(self, user):
        await self.append_logs(user, "A quitté le serveur")

    @commands.Cog.listener()
    async def on_member_ban(self, user):
        await self.append_logs(user, "A été banni")

    @commands.Cog.listener()
    async def on_member_unban(self, user):
        await self.append_logs(user, "A été débanni")

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        user = invite.inviter
        try:
            member = invite.guild.get_member(user.id)
            await self.append_logs(member, f"A créé une invitation › {invite.code}")
        except Exception as e:
            logger.info(msg=e, exc_info=False)

    @commands.Cog.listener()
    async def on_voice_state_update(self, user, before, after):
        if user.guild:
            if before.channel and after.channel:
                if before.self_stream > after.self_stream:
                    await self.append_logs(user, "A terminé un stream")
