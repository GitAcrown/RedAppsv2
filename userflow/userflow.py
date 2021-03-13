import asyncio
import re
from copy import copy
from datetime import datetime, timedelta
from typing import Union

import discord
import logging

from urllib import parse
import requests
from discord.ext import tasks
from discord.ext.commands import Greedy
from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions, menu, DEFAULT_CONTROLS
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.userflow")


class UserFlow(commands.Cog):
    """Contrôle de l'entrée et sortie des membres du serveur"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {'messages_count': 0}
        default_guild = {'joining_roles': []}
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)

        self.userflow_loop.start()

    @tasks.loop(minutes=1)
    async def userflow_loop(self):
        all_guilds = await self.config.all_guilds()
        for g in all_guilds:
            guild = self.bot.get_guild(g)
            data = all_guilds[g]['joining_roles']
            if data:
                for r in data:
                    role = guild.get_role(r['role'])
                    if r['rules'].get('delay'):
                        tdel = self.parse_timedelta(r['rules']['delay'])
                        cond = lambda u: (u.joined_at + tdel) <= datetime.utcnow()
                        for member in guild.members:
                            if (datetime.now() - member.joined_at).days <= 14:
                                if r['role'] not in (mr.id for mr in member.roles):
                                    if cond(member):
                                        await member.add_roles(role, reason="Attribution auto. à l'arrivée | Condition de délai respectée")

    @userflow_loop.before_loop
    async def before_userflow_loop(self):
        logger.info('Starting userflow_loop...')
        await self.bot.wait_until_ready()

    def parse_timedelta(self, time_string: str) -> timedelta:
        """Renvoie un objet *timedelta* à partir d'un str contenant des informations de durée (Xj Xh Xm Xs)"""
        if not isinstance(time_string, str):
            raise TypeError("Le texte à parser est invalide, {} != str".format(type(time_string)))

        regex = re.compile('^((?P<days>[\\.\\d]+?)j)? *((?P<hours>[\\.\\d]+?)h)? *((?P<minutes>[\\.\\d]+?)m)? *$')
        rslt = regex.match(time_string)
        if not rslt:
            raise ValueError("Vérifiez les valeurs de temps fournies")

        parsed = rslt.groupdict()
        return timedelta(**{i: int(parsed[i]) for i in parsed if parsed[i]})

    @commands.group(name="joinset")
    @checks.admin_or_permissions(manage_messages=True)
    async def _joining_set(self, ctx):
        """Gestion de l'arrivée des membres"""

    @_joining_set.command()
    async def listrole(self, ctx):
        """Afficher les rôles du système et les règles attachées à ceux-ci"""
        data = await self.config.guild(ctx.guild).joining_roles()
        if not data:
            return await ctx.send("**Aucun rôle n'a été configuré** : utilisez `;joinset setrole` pour en configurer un.")
        embeds = []
        msg = ""
        for r in data:
            role = ctx.guild.get_role(r['role'])
            regles = []
            for u in r['rules']:
                regles.append(f"`{u}={r['rules'][u]}`")

            if len(msg) < 1000:
                rules = ' '.join(regles) if regles else "Aucune"
                msg += f"{role.mention} • {rules}\n"
            else:
                em = discord.Embed(color=ctx.author.color,
                                   description=msg,
                                   title="Rôles d'arrivée configurés")
                embeds.append(em)
                msg = ""
        if msg:
            em = discord.Embed(color=ctx.author.color,
                               description=msg,
                               title="Rôles d'arrivée configurés")
            embeds.append(em)
        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.send(f"**Aucun rôle** • Vous n'avez configuré aucun rôle d'arrivée sur ce serveur")

    @_joining_set.command()
    async def setrole(self, ctx, role: discord.Role, *rules: str):
        """Ajouter/modifier un rôle à donner à l'arrivée d'un membre

        <role> = Rôle concerné
        [rules] = Optionnel, ajoute des règles à respecter (séparés par un espace) pour l'attribution du rôle.
        Les conditions ne sont pas cumulables : le rôle est attribué lorsqu'une condition est respectée

        **Règles :**
        `delay=Xj/h/m` → Délai après l'arrivée sur le serveur pour recevoir le rôle, exs. `delay=5m` `delay=10h` `delay=3j`
        `messages=Y` → Nombre de messages sur le serveur pour recevoir le rôle, ex. `messages=50`
        `account=Z` → Nombre de jours que le compte Discord doit posséder pour avoir le rôle, ex. `account=30`"""
        guild = ctx.guild
        newrole = {'role': role.id, 'rules': {}}
        if rules:
            for r in rules:
                if r.startswith('delay='):
                    time = r.split('=')[1]
                    try:
                        self.parse_timedelta(time)
                    except Exception as e:
                        return await ctx.send(f"**Erreur** : {e}")
                    else:
                        newrole['rules']['delay'] = time
                elif r.startswith('messages='):
                    try:
                        nb = int(r.split('=')[1])
                    except:
                        return await ctx.send(f"**Erreur** : le nombre du paramètre `messages` est invalide")
                    else:
                        newrole['rules']['messages'] = abs(nb)
                elif r.startswith('account='):
                    try:
                        nb = int(r.split('=')[1])
                    except:
                        return await ctx.send(f"**Erreur** : le nombre du paramètre `account` est invalide")
                    else:
                        newrole['rules']['account'] = abs(nb)

        data = copy(await self.config.guild(guild).joining_roles())
        async with self.config.guild(guild).joining_roles() as guildroles:
            for r in data:
                if r['role'] == role.id:
                    guildroles.remove(r)
            guildroles.append(newrole)
        await ctx.send(f"**Rôle configuré** : Le rôle *{role.name}* sera donné aux nouveaux arrivants (avec les conditions définies s'il y en a)")

    @_joining_set.command()
    async def delrole(self, ctx, roles: Greedy[discord.Role]):
        """Retirer un ou plusieurs rôles à donner aux nouveaux arrivants"""
        guild = ctx.guild
        data = copy(await self.config.guild(guild).joining_roles())
        async with self.config.guild(guild).joining_roles() as guildroles:
            for r in data:
                if r['role'] in [rd.id for rd in roles]:
                    guildroles.remove(r)
        await ctx.send("**Rôles supprimés** : les rôles demandés ont été retirés du système d'attribution automatique à l'arrivée")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild:
            author = message.author

            cur = await self.config.member(author).messages_count()
            await self.config.member(author).messages_count.set(cur + 1)

            data = await self.config.guild(message.guild).joining_roles()
            if data:
                for r in data:
                    role = message.guild.get_role(r['role'])
                    if role not in author.roles:
                        if r['rules'].get('messages', False):
                            if cur + 1 >= r['rules']['messages']:
                                await author.add_roles(role, reason="Attribution auto. à l'arrivée | Condition de messages respectée")

    @commands.Cog.listener()
    async def on_member_join(self, user):
        guild = user.guild
        if user.pending:
            while user.pending:
                if user not in [m for m in self.bot.get_guild(guild.id).members]:
                    return
                await asyncio.sleep(5)

        data = await self.config.guild(user.guild).joining_roles()
        if data:
            for r in data:
                role = user.guild.get_role(r['role'])
                if not r['rules']:
                    if role not in user.roles:
                        await user.add_roles(role, reason="Attribution auto. à l'arrivée | Sans conditions")
                elif r['rules'].get('account', False):
                    if (datetime.now() - user.created_at).days >= r['rules']['account']:
                        if role not in user.roles:
                            await user.add_roles(role, reason="Attribution auto. à l'arrivée | Condition de jours respectée")
