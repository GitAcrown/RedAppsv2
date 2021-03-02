import logging
import random
import re
from typing import List, Union

import discord

from datetime import datetime, timedelta

from discord.ext import tasks
from discord.ext.commands import Greedy
from redbot.core import commands, Config, checks
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import box
from discord.utils import get as discord_get

logger = logging.getLogger("red.RedAppsv2.karma")


class KarmaError(Exception):
    pass


class InvalidSettings(KarmaError):
    pass


class NoUserData(KarmaError):
    pass



class Karma(commands.Cog):
    """Commandes de modération avancées"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'jail_settings': {'role': None,
                                           'exclude_channels': [],
                                           'default_time': 300},
                         'jail_users': {}}
        self.config.register_guild(**default_guild)

        self.karma_loop.start()

    @tasks.loop(seconds=20)
    async def karma_loop(self):
        all_guilds = await self.config.all_guilds()
        now = datetime.now()
        for guild_id in all_guilds:
            guild = self.bot.get_guild(guild_id)
            jail_role = guild.get_role(all_guilds[guild_id]['jail_settings']['role'])
            if jail_role:
                for user_id in all_guilds[guild_id]['jail_users']:
                    if all_guilds[guild_id]['jail_users'][user_id] != {}:
                        if datetime.now().fromisoformat(all_guilds[guild_id]['jail_users'][user_id]['time']) <= now:
                            user = guild.get_member(user_id) if guild.get_member(user_id) else self.bot.get_user(user_id)
                            await self.remove_user_from_jail(user)

                            if type(user) == discord.Member:
                                try:
                                    await user.remove_roles(jail_role, reason="Fin de peine (auto.)")
                                except:
                                    pass

    @karma_loop.before_loop
    async def before_karma_loop(self):
        logger.info('Starting karma_loop...')
        await self.bot.wait_until_ready()

    async def add_user_to_jail(self, user: discord.Member, time: datetime, notify_channel: discord.TextChannel,
                          author: discord.Member, *, reason: str = ''):
        """Ajoute un membre à la prison"""
        guild = user.guild
        time = time.replace(second=0)
        jail_role = guild.get_role(await self.config.guild(guild).jail_settings.get_raw('role'))
        if not jail_role:
            raise InvalidSettings("Le rôle de la prison n'a pas été configuré")

        async with self.config.guild(guild).jail_users() as jail:
            jail[str(user.id)] = {'time': time.isoformat(), 'channel': notify_channel.id}

        em = discord.Embed(color=await self.bot.get_embed_color(notify_channel))
        em.set_author(name=f"🔒 Peine de prison → {str(user)}", icon_url=user.avatar_url)
        em.add_field(name="Sortie prévue", value=box(time.strftime('%d/%m/%Y %H:%M')))
        em.add_field(name="Auteur", value=box(str(author)))
        if reason:
            em.description = f"**Raison :** {reason}"

        rtxt = f"Mise en prison par {author} | Raison : {reason}" if reason else f"Mise en prison par {author}"
        await user.add_roles(jail_role, reason=rtxt)

        return await notify_channel.send(embed=em)

    async def add_users_to_jail(self, users: List[discord.Member], time: datetime, notify_channel: discord.TextChannel,
                          author: discord.Member, *, reason: str = ''):
        """Ajoute plusieurs membres à la prison"""
        guild = users[0].guild
        time = time.replace(second=0)
        jail_role = guild.get_role(await self.config.guild(guild).jail_settings.get_raw('role'))
        if not jail_role:
            raise InvalidSettings("Le rôle de la prison n'a pas été configuré")

        async with self.config.guild(guild).jail_users() as jail:
            for user in users:
                jail[str(user.id)] = {'time': time.isoformat(), 'channel': notify_channel.id}

        txt = "" if not reason else f"**Raison :** {reason}\n"
        txt += "**Membres concernés :**\n"

        for user in users:
            txt += f"• **{user.name}**#{user.discriminator}\n"
            rtxt = f"Mise en prison par {author} (Groupe) | Raison : {reason}" if reason else f"Mise en prison par {author} (Groupe)"
            await user.add_roles(jail_role, reason=rtxt)

        em = discord.Embed(title="Peine de prison", color=await self.bot.get_embed_color(notify_channel))
        em.add_field(name="Sortie prévue", value=box(time.strftime('%d/%m/%Y %H:%M')))
        em.add_field(name="Auteur", value=box(str(author)))

        return await notify_channel.send(embed=em)

    async def edit_user_jail(self, user: discord.Member, new_time: datetime, author: discord.Member):
        """Edite les données de prison d'un membre"""
        guild = user.guild
        time = new_time.replace(second=0)
        msg = None

        try:
            data = await self.config.guild(guild).jail_users.get_raw(str(user.id))
        except KeyError:
            return NoUserData(f"Le membre {user.name} (ID:{user.id}) n'est pas en prison")
        else:
            notify_channel = self.bot.get_channel(data['channel'])
            em = discord.Embed(color=await self.bot.get_embed_color(notify_channel))
            em.set_author(name=f"🔏 Peine de prison → {str(user)}", icon_url=user.avatar_url)
            em.description = "Modification de la peine"
            em.add_field(name="Sortie prévue", value=box(time.strftime('%d/%m/%Y %H:%M')))
            em.add_field(name="Auteur", value=box(str(author)))

            msg = await notify_channel.send(embed=em)
        finally:
            async with self.config.guild(guild).jail_users() as jail:
                jail[str(user.id)]['time'] = time.isoformat()
        return msg

    async def get_user_jail(self, user: discord.Member):
        """Renvoie les données de prison du membre demandé"""
        guild = user.guild
        try:
            return await self.config.guild(guild).jail_users.get_raw(str(user.id))
        except KeyError:
            return {}

    async def remove_user_from_jail(self, user: Union[discord.Member, discord.User]):
        """Retire un membre de la prison"""
        msg = None
        if type(user) == discord.Member:
            guild = user.guild

            try:
                data = await self.config.guild(guild).jail_users.get_raw(str(user.id))
            except KeyError:
                pass
            else:
                notify_channel = self.bot.get_channel(data.get('channel', None))
                if notify_channel:
                    em = discord.Embed(color=await self.bot.get_embed_color(notify_channel))
                    em.set_author(name=f"🔓 Peine de prison → {str(user)}", icon_url=user.avatar_url)
                    em.description = random.choice((f"Peine terminée, {user.mention} est désormais libre",
                                                    f"{user.mention} a terminé sa peine de prison",
                                                    f"{user.mention} est désormais libre",
                                                    f"{user.mention} a purgé sa peine de prison"))

                    msg = await notify_channel.send(embed=em)
            finally:
                async with self.config.guild(guild).jail_users() as jail:
                    jail[str(user.id)] = {}
        else:
            all_guilds = await self.config.all_guilds()
            for g in all_guilds:
                if str(user.id) in all_guilds[g]['jail_users']:
                    try:
                        data = await self.config.guild_from_id(g).jail_users.get_raw(str(user.id))
                    except KeyError:
                        pass
                    else:
                        notify_channel = self.bot.get_channel(data.get('channel', None))
                        if notify_channel:
                            em = discord.Embed(color=await self.bot.get_embed_color(notify_channel))
                            em.set_author(name=f"🔓 Peine de prison → {str(user)}", icon_url=user.avatar_url)
                            em.description = f"La peine de {user.mention} ne s'est pas terminée correctement\n" \
                                             f"(Le membre a quitté le serveur avant la fin de la peine)"

                            msg = await notify_channel.send(embed=em)
                    finally:
                        await self.config.guild_from_id(g).jail_users.set_raw(str(user.id), value={})
        return msg



    def parse_timedelta(self, time_string: str) -> timedelta:
        """Renvoie un objet *timedelta* à partir d'un str contenant des informations de durée (Xj Xh Xm Xs)"""
        if not isinstance(time_string, str):
            raise TypeError("Le texte à parser est invalide, {} != str".format(type(time_string)))

        regex = re.compile('^((?P<days>[\\.\\d]+?)j)? *((?P<hours>[\\.\\d]+?)h)? *((?P<minutes>[\\.\\d]+?)m)? *((?P<seconds>[\\.\\d]+?)s)? *$')
        rslt = regex.match(time_string)
        if not rslt:
            raise ValueError("Aucun timedelta n'a pu être déterminé des valeurs fournies")

        parsed = rslt.groupdict()
        return timedelta(**{i: int(parsed[i]) for i in parsed if parsed[i]})

    @commands.command(name="prison", aliases=["p"])
    @checks.admin_or_permissions(manage_messages=True)
    async def _jail_users(self, ctx, users: Greedy[discord.Member], time: str = '', *, reason: str = ''):
        """Commande principale de la prison (Ajout/retrait/modification de peine)

        - Ajouter un/des membre(s) : `[p]prison <membre.s> <temps> [raison]`
        - Retirer un/des membre(s) : `[p]prison <membre.s>`
        - Editer un temps de prison : `[p]prison <membre> ±<temps>` (Un membre à la fois)

        La raison est optionnelle et peut être ajoutée après le temps

        **Formattage du temps de peine :**
        j = jours
        h = heures
        m = minutes
        s = secondes
        + = Ajouter du temps
        - = Retirer du temps
        Exs. `1h30m` | `+45m` | `-2h5m` | etc."""
        guild = ctx.guild
        author = ctx.author
        settings = await self.config.guild(guild).jail_settings()
        if not time:
            time = f"{settings['default_time']}s"

        if settings['role']:
            jail_role = guild.get_role(settings['role'])
            if time[0] in ('+', '-'):
                user = users[0]
                userdata = await self.get_user_jail(user)
                if userdata:
                    try:
                        tmdelta = self.parse_timedelta(time[1:])
                        if time[0] == "+":
                            dt = (datetime.now().fromisoformat(userdata['time']) + tmdelta)
                        else:
                            dt = (datetime.now().fromisoformat(userdata['time']) - tmdelta)
                    except Exception as e:
                        return await ctx.send(f"**Erreur** » `{e}`")
                    await self.edit_user_jail(user, dt, author)
                else:
                    return await ctx.send("**Impossible** » Vous ne pouvez pas éditer le temps de prison d'un "
                                          "membre non emprisonné")
            else:
                to_add, to_rem = [], []
                for user in users:
                    if not await self.get_user_jail(user):
                        to_add.append(user)
                    else:
                        to_rem.append(user)
                try:
                    tmdelta = self.parse_timedelta(time)
                    dt = (datetime.now() + tmdelta)
                except Exception as e:
                    return await ctx.send(f"**Erreur** » `{e}`")

                if to_add:
                    users = to_add
                    if len(users) == 1:
                        await self.add_user_to_jail(users[0], dt, ctx.channel, author, reason=reason)
                    else:
                        await self.add_users_to_jail(users, dt, ctx.channel, author, reason=reason)

                elif to_rem:
                    users = to_rem
                    for user in users:
                        await self.remove_user_from_jail(user)
                        await user.remove_roles(jail_role)

                else:
                    await ctx.send("**Erreur** » Les membres cités ne peuvent ni être retirés ni ajoutés à la prison")

        else:
            await ctx.send("**Non configurée** » La prison n'a pas encore été configurée (v. `[p]pset role`")

    async def check_jail_role_perms(self, role: discord.Role):
        to_apply = discord.Permissions(send_messages=False)
        await role.edit(permissions=to_apply, reason="Vérif. permissions de rôle")


    @commands.group(name="pset")
    @checks.admin_or_permissions(manage_messages=True)
    async def _jail_settings(self, ctx):
        """Paramètres de la prison"""

    @_jail_settings.command(name="role")
    async def jail_role(self, ctx, role: Union[discord.Role, bool] = None):
        """Définir le rôle de la prison

        Si aucun rôle n'est donné, celui-ci est créé automatiquement (si non déjà présent)
        Mettre 'False' désactive la prison"""
        guild = ctx.guild
        jail = await self.config.guild(guild).jail_settings()
        if type(role) == discord.Role:
            jail["role"] = role.id
            await ctx.send(f"**Rôle modifié** » Le rôle {role.mention} sera désormais utilisé pour la prison\n"
                           f"Faîtes `[p]pset check` pour régler automatiquement les permissions. "
                           f"Sachez que vous devez manuellement monter le rôle à sa place appropriée dans la hiérarchie.")
        elif role != False:
            maybe_role = discord_get(guild.roles, name="Prisonnier")
            if maybe_role:
                jail["role"] = maybe_role.id
                await ctx.send(
                    f"**Rôle détecté** » Le rôle {maybe_role.mention} sera désormais utilisé pour la prison\n"
                    f"Faîtes `[p]pset check` pour régler automatiquement les permissions. "
                    f"Sachez que vous devez manuellement monter le rôle à sa place appropriée dans la hiérarchie.")
            else:
                role = await guild.create_role(name="Prisonnier", color=discord.Colour.default(),
                                               reason="Création auto. du rôle de prisonnier")
                jail["role"] = role.id
                await ctx.send(f"**Rôle créé** » Le rôle {role.mention} sera désormais utilisé pour la prison\n"
                               f"Faîtes `[p]pset check` pour régler automatiquement les permissions. "
                               f"Sachez que vous devez manuellement monter le rôle à sa place appropriée dans la hiérarchie.")
        else:
            jail['role'] = None
            await ctx.send(f"**Rôle retiré** » La prison a été désactivée.")
        await self.config.guild(guild).jail_settings.set(jail)

        if jail["role"]:
            role = guild.get_role(jail["role"])
            await self.check_jail_role_perms(role)

    @_jail_settings.command(name="channels")
    async def jail_channels(self, ctx, *channels: discord.TextChannel):
        """Accorde un/des channel(s) écrits dans le(s)quel les prisonniers peuvent parler librement

        Régler un tel channel va faire en sorte de lock tous les autres salons du serveur pour le rôle de prisonnier
        Ne rien mettre retire ce salon des exceptions"""
        guild = ctx.guild
        jail = await self.config.guild(guild).jail_settings()
        if channels:
            if jail["role"]:
                role = guild.get_role(jail["role"])
                await self.check_jail_role_perms(role)
                tb = ""
                chans = []
                for channel in channels:
                    overwrite = discord.PermissionOverwrite(send_messages=True, read_messages=True)
                    try:
                        await channel.set_permissions(role, overwrite=overwrite,
                                                      reason="Réglage auto. des permissions pour la prison")
                        tb += f"- {channel.mention}\n"
                        chans.append(channel.id)
                    except:
                        pass
                if tb:
                    await ctx.send("**Channels adaptés pour la prison :**\n" + tb)
                    await self.config.guild(guild).jail.set_raw("exclude_channels", value=chans)
                else:
                    await ctx.send("Aucun channel n'a été modifié (manques de permissions ou channels déjà correctement configurés).")
            else:
                await ctx.send(
                    "**Impossible** » Configurez d'abord un rôle de prisonnier avant de lui accorder des exceptions")
        elif jail["role"]:
            role = guild.get_role(jail["role"])
            for channel in guild.text_channels:
                await channel.set_permissions(role, overwrite=None)
            await ctx.send("**Channels retirés** » Plus aucun channel n'accorde d'exception aux prisonniers")
            await self.config.guild(guild).jail.clear_raw("exclude_channels")
        else:
            await ctx.send(
                "**Impossible** » Je n'ai pas de permissions à retirer si je n'ai pas de rôle cible (configurez un rôle prisonnier d'abord)")

    @_jail_settings.command(name="delay")
    async def jail_default_delay(self, ctx, val: int = 300):
        """Règle le délai par défaut (en secondes) de la prison si aucune durée n'est spécifiée

        Doit être supérieure à 5 et inférieure à 86400 (1 jour)
        Par défaut 300s (5 minutes)"""
        guild = ctx.guild
        jail = await self.config.guild(guild).jail_settings()
        if 5 <= val <= 86400:
            jail["default_time"] = val
            await ctx.send(
                f"**Délai modifié** » Par défaut les prisonniers seront emprisonnés {val} secondes")
            await self.config.guild(guild).jail_settings.set(jail)
        else:
            await ctx.send(
                f"**Délai invalide** » La valeur du délai doit se situer entre 5 et 86400 secondes")

    @_jail_settings.command(name="check")
    async def jail_check_perms(self, ctx):
        """Vérifie auto. les permissions du rôle de prisonnier"""
        guild = ctx.guild
        jail = await self.config.guild(guild).jail_settings()
        if jail["role"]:
            role = guild.get_role(jail["role"])
            await self.check_jail_role_perms(role)
            overwrite = discord.PermissionOverwrite(send_messages=True, read_messages=True)
            prisons = jail["exclude_channels"]
            for channel in guild.text_channels:
                if channel.id in prisons:
                    try:
                        await channel.set_permissions(role, overwrite=overwrite,
                                                      reason="Réglage auto. des permissions pour la prison")
                    except Exception as e:
                        logger.error(e, exc_info=True)
                else:
                    try:
                        await channel.set_permissions(role, overwrite=None)
                    except Exception as e:
                        logger.error(e, exc_info=True)
            await ctx.send(
                "**Vérification terminée** » Les permissions du rôle ont été mis à jour en prenant en compte les exceptions des salons de prison")
        else:
            await ctx.send("**Vérification impossible** » Aucun rôle de prisonnier n'a été configuré")