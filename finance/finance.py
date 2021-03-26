import asyncio
import logging
import random
import re
import string
import time
from copy import copy
from datetime import datetime, timedelta

import discord
from discord.errors import HTTPException
from typing import Union, List, Tuple, Literal

from discord.ext import tasks
from redbot.core import Config, commands, checks
from redbot.core.utils import AsyncIter
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box, humanize_number
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.finance")


class FinanceError(Exception):
    """Classe de base pour les erreurs Finance"""


class BalanceTooHigh(FinanceError):
    """Soulevée lorsque le balance dépasse le seuil fixé"""


class UnauthorizedMember(FinanceError):
    """Soulevée lorsqu'un membre n'est pas autorisé à réaliser une action"""


class UserNotFound(FinanceError):
    """Soulevée lorsqu'un membre n'est pas retrouvé sur le serveur"""


class InvalidCurrency(FinanceError):
    """Soulevée lorsqu'il a été impossible de récupérer la monnaie d'un serveur"""


class FinanceAccount:
    def __init__(self, user: discord.Member, balance: int, logs: list, config: dict):
        self.user, self.guild = user, user.guild
        self.balance = balance
        self.logs = logs
        self.config = config

    def __str__(self):
        return self.user.mention

    def __int__(self):
        return self.balance


class FinanceLog:
    def __init__(self, user: discord.Member, content: str, timestamp: str, delta: int):
        self.user = user
        self.guild = user.guild
        self.content = content
        self.timestamp = timestamp
        self.delta = delta

    def __str__(self):
        return self.content

    def __int__(self):
        return self.timestamp

    def formatted_date(self):
        return datetime.now().fromisoformat(self.timestamp).strftime('%d/%m/%Y %H:%M')

    def formatted_time(self):
        return datetime.now().fromisoformat(self.timestamp).strftime('%H:%M')


class Finance(commands.Cog):
    """Système centralisé d'économie virtuelle"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_member = {"balance": 0,
                          "logs": [],
                          "config": {"daily_bonus": ''}}

        default_guild = {"currency": "Ꞥ",
                         "daily_bonus": 100,
                         "booster_bonus": 100,
                         "lb_role": None}

        default_global = {"max_balance": 10**9}
        self.config.register_member(**default_member)
        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)

        self.finance_loop.start()

    @tasks.loop(minutes=30)
    async def finance_loop(self):
        guilds = await self.config.all_guilds()
        for g in guilds:
            if guilds[g]['lb_role']:
                guild = self.bot.get_guild(g)
                role = guild.get_role(guilds[g]['lb_role'])
                old = [m for m in guild.members if role in m.roles]
                first = await self.get_guild_leaderboard(guild, 1)
                if old:
                    old_first = old[0]
                    if old_first != first[0].user:
                        try:
                            await old_first.remove_roles(role, reason="N'est plus 1er du classement économique")
                        except:
                            pass
                if role not in first[0].user.roles:
                    try:
                        await first[0].user.add_roles(role, reason="Est premier du classement économique")
                    except:
                        logger.error(f"Impossible d'attribuer le rôle pour {first[0].user}", exc_info=True)

    @finance_loop.before_loop
    async def before_finance_loop(self):
        logger.info('Starting finance_loop...')
        await self.bot.wait_until_ready()


    async def migrate_from_cash(self):
        """Tente l'importation des données depuis Cash"""
        try:
            cash_config = Config.get_conf(None, identifier=736144321857978388, cog_name="Cash")
            guilds = self.bot.guilds
            n = 1
            for guild in guilds:
                logger.info(msg=f"{n} Importation des données Cash de : {guild.id}")
                old_data = await cash_config.guild(guild).all()
                await self.config.guild(guild).currency.set(old_data['currency'])
                await self.config.guild(guild).daily_bonus.set(old_data['daily_bonus'])

                for member in guild.members:
                    user_old = await cash_config.member(member).all()
                    await self.config.member(member).balance.set(user_old['balance'])
                    await self.config.member(member).config.set_raw('daily_bonus', value=user_old['config']['cache_daily_bonus'])

                n += 1
        except:
            return False
        return True


    async def get_currency(self, guild: discord.Guild) -> Union[str, discord.Emoji]:
        """Obtenir le symbole de la monnaie du serveur"""
        c = await self.config.guild(guild).currency()
        if type(c) is int:
            try:
                emoji = self.bot.get_emoji(int(c))
            except:
                raise InvalidCurrency(f"Impossible de récupérer l'emoji {c} représentant le serveur {guild.id}")
            else:
                return emoji
        return c

    async def set_currency(self, guild: discord.Guild, currency: Union[discord.Emoji, str]) -> Union[str, discord.Emoji]:
        """Modifie le symbole ou emoji de la monnaie du serveur

        > Renvoie la nouvelle monnaie"""
        if isinstance(currency, str):
            if len(currency) > 5:
                raise ValueError("Le symbole de la monnaie ne peut pas faire plus de 5 caractères de long")
            await self.config.guild(guild).currency.set(currency)
        elif isinstance(currency, discord.Emoji):
            await self.config.guild(guild).currency.set(currency.id)
        else:
            raise ValueError("Le type de monnaie est invalide : ce n'est ni un emoji ni une suite de caractères valides")
        return currency


    async def get_account(self, member: discord.Member) -> FinanceAccount:
        """Obtenir l'objet FinanceAccount du membre demandé"""
        userdata = await self.config.member(member).all()
        return FinanceAccount(member, **userdata)

    async def get_balance(self, member: discord.Member) -> int:
        """Renvoie la valeur actuelle du solde d'un membre"""
        account = await self.get_account(member)
        return account.balance

    async def enough_credits(self, member: discord.Member, cost: int) -> bool:
        """Vérifie si le membre possède assez de fonds pour une dépense"""
        if not isinstance(cost, int):
            raise TypeError("Type de la dépense invalide, {} != int".format(type(cost)))
        if cost < 0:
            return False
        return await self.get_balance(member) >= cost

    async def set_balance(self, member: discord.Member, value: int, *, reason: str = '') -> int:
        """Modifier le solde d'un membre

        > Renvoie le nouveau solde du compte"""
        if not isinstance(value, int):
            raise TypeError("Type du dépôt invalide, {} != int".format(type(value)))
        if value < 0:
            raise ValueError("Le solde ne peut être négatif")
        max_balance = await self.config.max_balance()
        if value > max_balance:
            raise BalanceTooHigh(f"Il est impossible de dépasser le seuil fixé de {max_balance} crédits")

        old_value = await self.config.member(member).balance()

        await self.config.member(member).balance.set(value)
        await self.append_log(member, value - old_value, content=reason)

        return value

    async def deposit_credits(self, member: discord.Member, value: int, *, reason: str = '') -> int:
        """Ajouter des crédits au solde d'un membre

        > Renvoie le nouveau solde du compte"""
        if not isinstance(value, int):
            raise TypeError("Type du dépôt invalide, {} != int".format(type(value)))
        if value < 0:
            raise ValueError(f"Valeur de dépôt invalide, {value} < 0")

        current = await self.get_balance(member)
        return await self.set_balance(member, current + value, reason=reason)

    async def remove_credits(self, member: discord.Member, value: int, *, reason: str = '') -> int:
        """Retirer des crédits au solde d'un membre

        Renvoie le nouveau solde du compte"""
        if not isinstance(value, int):
            raise TypeError("Type de retrait invalide, {} != int".format(type(value)))
        if value < 0:
            raise ValueError(f"Valeur de retrait invalide, {value} < 0")

        current = await self.get_balance(member)
        if value > current:
            raise ValueError(f"Fonds insuffisants, {value} > {current}")

        return await self.set_balance(member, current - value, reason=reason)

    async def transfert_credits(self, from_: discord.Member,
                                to_: discord.Member,
                                value: int,
                                *, reason: str = '') -> Tuple[FinanceAccount, FinanceAccount]:
        """Transfère des crédits d'un membre à un autre

        > Renvoie un tuple contenant les comptes des deux membres (FROM, TO)"""
        if not isinstance(value, int):
            raise TypeError("Type du transfert invalide, {} != int".format(type(value)))
        if value < 0:
            raise ValueError(f"Valeur du transfert invalide, {value} < 0")

        max_balance = await self.config.max_balance()
        if await self.get_balance(to_) + value > max_balance:
            raise BalanceTooHigh(f"Il est impossible de dépasser le seuil fixé de {max_balance} crédits lors d'une "
                                 f"transaction")

        await self.remove_credits(from_, value, reason=reason)
        await self.deposit_credits(to_, value, reason=reason)
        return await self.get_account(from_), await self.get_account(to_)


    async def get_log(self, member: discord.Member, timestamp: datetime) -> Union[FinanceLog, None]:
        """Renvoie le 1er log partageant le timestamp (UTC) donné"""
        if not isinstance(timestamp, datetime):
            raise TypeError("Type du timestamp invalide, {} != datetime".format(type(timestamp)))

        acc = await self.get_account(member)
        for log in acc.logs:
            if datetime.now().fromisoformat(log['timestamp']) == timestamp:
                return FinanceLog(**log)
        return None

    async def get_member_logs(self, member: discord.Member) -> Union[List[FinanceLog], list]:
        """Renvoie tous les logs (sous forme d'objets FinanceLog) d'un membre

        Renvoie une liste vide si aucun log n'est présent"""
        acc = await self.get_account(member)
        all_logs = []
        if acc.logs:
            today = datetime.now().date()
            if datetime.now().fromisoformat(acc.logs[0]['timestamp']).date() == today:
                for log in acc.logs:
                    all_logs.append(FinanceLog(member, **log))
        return all_logs

    async def get_member_delta(self, member: discord.Member) -> int:
        """Renvoie le total des opérations d'aujourd'hui"""
        acc = await self.get_account(member)
        if acc.logs:
            today = datetime.now().date()
            if datetime.now().fromisoformat(acc.logs[0]['timestamp']).date() == today:
                return sum([log['delta'] for log in acc.logs])
        return 0

    async def append_log(self, member: discord.Member, delta: int, *, content: str = '') -> dict:
        """Enregistre une opération dans les logs du membre

        > Retourne le log créé"""
        if not isinstance(content, str):
            raise TypeError("Type du contenu du log invalide, {} != str".format(type(content)))
        if not isinstance(delta, int):
            raise TypeError("Type de somme du log invalide, {} != int".format(type(delta)))

        log = {'content': content, 'timestamp': datetime.now().isoformat(), 'delta': delta}

        today = datetime.now().date()
        acc = await self.get_account(member)
        if acc.logs:
            if datetime.now().fromisoformat(acc.logs[0]['timestamp']).date() != today:
                await self.wipe_logs(member)

        async with self.config.member(member).logs() as logs:
            logs.append(log)

        return log

    async def remove_log(self, member: discord.Member, timestamp: datetime) -> list:
        """Retire un log (ou plusieurs s'ils ont un timestamp UTC identique) au membre visé

        > Renvoie le nouvel état des logs"""
        if not isinstance(timestamp, datetime):
            raise TypeError("Type du timestamp du log invalide, {} != datetime".format(type(timestamp)))
        if not await self.get_log(member, timestamp):
            raise ValueError(f"Log avec le timestamp {timestamp} pour USERID={member.id} introuvable")

        async with self.config.member(member).logs() as logs:
            _logs = copy(logs)
            for log in _logs:
                if datetime.now().fromisoformat(log['timestamp']) == timestamp:
                    logs.remove(log)

        return _logs


    async def wipe_logs(self, member: discord.Member) -> None:
        """Supprime tous les logs d'un membre"""
        await self.config.member(member).clear_raw('logs')

    async def wipe_guild(self, guild: discord.Guild) -> None:
        """Supprime les données bancaires des membres d'un serveur"""
        await self.config.clear_all_members(guild)

    async def wipe_account(self, member: discord.Member) -> None:
        """Supprime les données bancaires d'un membre"""
        await self.config.member(member).clear()

    async def raw_delete_account(self, user_id: int, guild: discord.Guild) -> None:
        """Supprime un compte bancaire par ID du membre"""
        await self.config.member_from_ids(guild.id, user_id).clear()

    async def get_max_balance(self) -> int:
        """Renvoie la valeur maximale que peut atteindre un solde de membre (sur n'importe quel serveur)"""
        return self.config.max_balance()

    async def set_max_balance(self, value: int) -> None:
        """Modifie la valeur maximale qu'un solde de membre peut atteindre"""
        if not isinstance(value, int):
            raise TypeError("Type de la valeur maximale invalide, {} != int".format(type(value)))
        if value <= 0:
            raise ValueError("Valeur invalide, le maximum ne peut pas être négatif ou nul")

        await self.config.max_balance.set(value)


    async def get_guild_leaderboard(self, guild: discord.Guild, cutoff: int = None) -> Union[list, List[FinanceAccount]]:
        """Renvoie le top des membres les plus riches du serveur (liste d'objets FinanceAccount)

        Renvoie une liste vide si aucun top n'est générable"""
        users = await self.config.all_members(guild)
        sorted_users = sorted(list(users.items()), key=lambda u: u[1]['balance'], reverse=True)
        top = []
        for uid, acc in sorted_users:
            user = guild.get_member(uid)
            if user:
                top.append(FinanceAccount(user, **acc))
        return top[:cutoff] if cutoff else top

    async def get_leaderboard_position_for(self, member: discord.Member) -> int:
        """Renvoie la position du membre dans le classement de son serveur

        Renvoie la dernière place du classement si le membre n'est pas trouvé"""
        top = await self.get_guild_leaderboard(member.guild)
        for acc in top:
            if acc.user == member:
                return top.index(acc) + 1
        return len(top)

    async def get_guild_total_credits(self, guild: discord.Guild) -> int:
        """Renvoie la valeur totale des crédits en circulation sur le serveur visé"""
        users = await self.config.all_members(guild)
        return sum([users[u]['balance'] for u in users])


    async def utils_parse_timedelta(self, time_string: str) -> timedelta:
        """Renvoie un objet *timedelta* à partir d'un str contenant des informations de durée (Xj Xh Xm Xs)"""
        if not isinstance(time_string, str):
            raise TypeError("Le texte à parser est invalide, {} != str".format(type(time_string)))

        regex = re.compile('^((?P<days>[\\.\\d]+?)j)? *((?P<hours>[\\.\\d]+?)h)? *((?P<minutes>[\\.\\d]+?)m)? *((?P<seconds>[\\.\\d]+?)s)? *$')
        sch = regex.match(time_string)
        if not sch:
            raise ValueError("Aucun timedelta n'a pu être déterminé des valeurs fournies")

        parsed = sch.groupdict()
        return timedelta(**{i: int(parsed[i]) for i in parsed if parsed[i]})

    # COMMANDES ----------------------------------V

    @commands.command(name="bank", aliases=['b'])
    @commands.guild_only()
    async def bank_info(self, ctx, user: discord.Member = None):
        """Afficher les infos son compte bancaire"""
        user = user if user else ctx.message.author
        acc = await self.get_account(user)
        curr = await self.get_currency(ctx.guild)

        hum_balance = humanize_number(acc.balance)
        em = discord.Embed(color=user.color, timestamp=ctx.message.created_at)
        em.set_author(name="Compte de " + str(user), icon_url=user.avatar_url)
        em.add_field(name="💰 Solde", value=box(f"{hum_balance} {curr}"))
        delta = await self.get_member_delta(user)
        delta_emoji = "📉" if delta < 0 else "📈"
        em.add_field(name=f"{delta_emoji} Aujourd'hui", value=box(f"{delta:+}"))
        top = await self.get_leaderboard_position_for(user)
        em.add_field(name="🏅 Position", value=box(f"#{top}"))

        logs = await self.get_member_logs(user)
        if logs:
            txt = "\n".join([f"{log.delta:+} · {log.content[:50]}" for log in logs if log.content][::-1][:3])
            em.add_field(name="📃 Dernières opérations*", value=box(txt))
        em.set_footer(text="*Opérations détaillées seulement")
        await ctx.send(embed=em)

    @commands.command(name="give")
    @commands.guild_only()
    @commands.cooldown(1, 60, commands.BucketType.member)
    async def bank_give(self, ctx, receveur: discord.Member, somme: int):
        """Transférer de l'argent à un receveur tiers"""
        try:
            await self.transfert_credits(ctx.author, receveur, int(somme), reason=f"Don {ctx.author.name} → {receveur.name}")
        except ValueError:
            return await ctx.message.reply("**Impossible** • Vous ne pouvez pas transférer une somme nulle ou négative")
        except BalanceTooHigh:
            plaf = humanize_number(await self.config.max_balance())
            return await ctx.send(f"**Limite atteinte** • {receveur.mention} ne peut pas recevoir cette somme car "
                                  f"il dépasserait le plafond fixé de {plaf}")
        else:
            curr = await self.get_currency(ctx.guild)
            await ctx.message.reply(f"**Transfert réalisé** • {receveur.mention} a reçu **{somme}** {curr}")

    @commands.command(name="operations", aliases=['opes'])
    @commands.guild_only()
    async def bank_logs(self, ctx, user: discord.Member = None):
        """Affiche les opérations détaillées d'un membre

        Seules les opérations du jour même sont disponibles"""
        user = user if user else ctx.message.author

        logs = await self.get_member_logs(user)
        if not logs:
            return await ctx.send(f"**Aucune opération** • Il n'y a aucune opération enregistrée pour aujourd'hui")

        embeds = []
        tabl = []
        for log in logs[::-1]:
            if len(tabl) < 20:
                if log.content:
                    tabl.append((log.formatted_time(), f"{log.delta:+}", f"{log.content[:50]}"))
                else:
                    tabl.append((log.formatted_time(), f"{log.delta:+}", "..."))
            else:
                em = discord.Embed(color=user.color, description=box(tabulate(tabl, headers=["Heure", "Somme", "Détails"])))
                em.set_author(name=f"Opérations de {user}*", icon_url=user.avatar_url)
                em.set_footer(text="*Opérations de ce jour seulement")
                embeds.append(em)
                tabl = []

        if tabl:
            em = discord.Embed(color=user.color, description=box(tabulate(tabl, headers=["Heure", "Somme", "Détails"])))
            em.set_author(name=f"Opérations de {user}*", icon_url=user.avatar_url)
            em.set_footer(text="*Opérations de ce jour seulement")
            embeds.append(em)

        if embeds:
            await menu(ctx, embeds, DEFAULT_CONTROLS)
        else:
            return await ctx.send(f"**Aucune opération** • Il n'y a aucune opération à afficher pour aujourd'hui")

    @commands.command(name="bonus")
    @commands.guild_only()
    async def cash_bonus(self, ctx):
        """Recevoir son bonus quotidien de crédits"""
        author = ctx.author
        today = datetime.now().strftime("%Y.%m.%d")
        acc = await self.get_account(author)
        curr = await self.get_currency(ctx.guild)
        bonus = await self.config.guild(ctx.guild).daily_bonus()
        booster = await self.config.guild(ctx.guild).booster_bonus()
        if bonus:
            if acc.config["daily_bonus"] != today:
                await self.config.member(author).config.set_raw("daily_bonus", value=today)
                if ctx.author.premium_since and booster:
                    new = await self.deposit_credits(author, bonus + booster, reason="Bonus quotidien + Boost")
                    em = discord.Embed(color=author.color,
                                       description=f"**+{bonus}** {curr} ont été ajoutés à votre compte au titre du bonus quotidien.\n"
                                                   f"**+{booster}** {curr} sont offerts en supplément du fait de votre titre de booster du serveur.",
                                       timestamp=ctx.message.created_at)
                else:
                    new = await self.deposit_credits(author, bonus, reason="Bonus quotidien")
                    em = discord.Embed(color=author.color,
                                       description=f"**+{bonus}** {curr} ont été ajoutés à votre compte au titre du bonus quotidien.",
                                       timestamp=ctx.message.created_at)
                em.set_author(name=str(author), icon_url=author.avatar_url)
                em.set_footer(text=f"Vous avez désormais {new} {curr}")
                await ctx.send(embed=em)
            else:
                await ctx.send("**Déjà récupéré** • Revenez demain pour obtenir votre bonus !")
        else:
            await ctx.send("**Désactivé** • Ce serveur n'offre pas de bonus quotidien")

    @commands.command(name="leaderboard", aliases=["lb"])
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def display_leaderboard(self, ctx, top: int = 10):
        """Affiche le top des membres les plus riches du serveur

        Vous pouvez modifier la longueur du top en précisant le paramètre *<top>*"""
        lbd = await self.get_guild_leaderboard(ctx.guild, top)
        if lbd:
            tbl = []
            found = False
            for acc in lbd:
                tbl.append([str(acc.user), acc.balance])
                if acc.user == ctx.author:
                    found = True
            em = discord.Embed(color=await self.bot.get_embed_color(ctx.channel),
                               description=box(tabulate(tbl, headers=["Membre", "Solde"])))
            if not found:
                invok =
                em.add_field(name="Votre rang",
                             value=box("#" + str(await self.get_leaderboard_position_for(ctx.author)) +
                                       f" ({int(await self.get_account(ctx.author))})"))
            em.set_author(name=f"🏆 Leaderboard de {ctx.guild.name}", icon_url=ctx.guild.icon_url)
            em.set_footer(text=f"Total : {await self.get_guild_total_credits(ctx.guild)} {await self.get_currency(ctx.guild)}")
            try:
                await ctx.send(embed=em)
            except HTTPException:
                await ctx.send("**Erreur** • Le top est trop grand pour être affiché, utilisez une "
                               "valeur de <top> plus réduite")
        else:
            await ctx.send("Il n'y a aucun top à afficher.")

    @commands.group(name="bankset", aliases=["bset"])
    @checks.admin_or_permissions(manage_messages=True)
    async def _bank_set(self, ctx):
        """Commandes de gestion de la banque"""

    @_bank_set.command(name="monnaie", aliases=["currency"])
    async def _bank_currency(self, ctx, monnaie: str):
        """Changer le symbole utilisé pour la monnaie sur le serveur"""
        try:
            await self.set_currency(ctx.guild, monnaie)
        except ValueError as e:
            await ctx.send(f"**Erreur** • `{e}`")
        else:
            await ctx.send(f"**Changement réalisé** • Le nouveau symbole de la monnaie sera \"{monnaie}\"")

    @_bank_set.command(name="lbrole")
    async def _bank_lb_role(self, ctx, role: discord.Role = None):
        """Attribuer un rôle au premier du classement (MAJ. toutes les 30m)

        Ne rien mettre désactive cette fonctionnalité"""
        guild = ctx.guild
        if role:
            await self.config.guild(guild).lb_role.set(role.id)
            await ctx.send(f"**Rôle configuré** • Le membre le plus riche recevra automatiquement le rôle ***{role.name}***")
        else:
            await self.config.guild(guild).lb_role.set(None)
            await ctx.send(
                f"**Rôle retiré** • Le membre le plus riche ne recevra plus de rôle")

    @_bank_set.command(name='booster')
    async def _bank_booster_bonus(self, ctx, somme: int = 100):
        """Permet de définir l'attribution d'un bonus quotidien aux boosters du serveur

        Mettre 0 désactive ce bonus"""
        guild = ctx.guild
        curr = await self.get_currency(guild)
        if somme > 0:
            await self.config.guild(guild).booster_bonus.set(somme)
            await ctx.send(
                f"**Bonus ajouté** • Les boosters du serveur auront un bonus quotidien de {somme} {curr}")
        else:
            await self.config.guild(guild).booster_bonus.set(0)
            await ctx.send(
                f"**Bonus retiré** • Les boosters du serveur n'auront plus de bonus quotidien")

    @_bank_set.command(name="dailybonus")
    async def _bank_daily_bonus(self, ctx, somme: int = 100):
        """Modifier le bonus quotidien octroyé aux membres (par défaut 100)

        Mettre 0 désactive le bonus quotidien"""
        guild = ctx.guild
        if somme >= 0:
            await self.config.guild(guild).daily_bonus.set(somme)
            curr = await self.get_currency(guild)
            if somme > 0:
                await ctx.send(f"**Somme modifiée** • Les membres auront le droit à {somme} {curr} par jour")
            else:
                await ctx.send(
                    "**Bonus désactivé** • Les membres ne pourront plus demander un bonus quotidien de crédits")
        else:
            await ctx.send(
                "**Impossible** • La valeur du bonus doit être positif, ou nulle si vous voulez désactiver la fonctionnalité")

    @_bank_set.command(name="edit")
    async def _bank_edit_account(self, ctx, user: discord.Member, value: int = None):
        """Modifie le solde d'un compte de membre

        Ne rien mettre affiche le solde actuel du membre"""
        acc = await self.get_account(user)
        curr = await self.get_currency(user.guild)
        if value:
            try:
                solde = await self.set_balance(user, value, reason=f"Modification manuelle ({ctx.author})")
                await ctx.send(f"**Succès** • Le solde de {user.mention} est désormais de **{solde}** {curr}")
            except ValueError:
                await ctx.send("**Erreur** • Le solde d'un membre ne peut être négatif")
        else:
            await ctx.send(f"**Info** • Le solde de {str(user)} est de **{humanize_number(acc.balance)}** {curr}")

    @_bank_set.command(name="resetuser")
    async def _bank_reset_account(self, ctx, user: discord.Member):
        """Reset les données bancaires d'un membre (cache compris)"""
        await self.config.member(user).clear()
        await ctx.send(f"**Succès** • Le compte de {user.mention} a été réinitialisé")

    @_bank_set.command(name="resetcache")
    async def _bank_reset_account_cache(self, ctx, user: discord.Member):
        """Reset seulement les données du cache du compte bancaire du membre

        Cela réinitialise les délais des bonus"""
        await self.config.member(user).config.clear_raw("daily_bonus")
        await ctx.send(f"**Succès** • Le cache du compte de {user.mention} a été réinitialisé")

    async def red_delete_data_for_user(
        self, *, requester: Literal["discord", "owner", "user", "user_strict"], user_id: int
    ):
        await self.config.user_from_id(user_id).clear()
        all_members = await self.config.all_members()
        async for guild_id, guild_data in AsyncIter(all_members.items(), steps=100):
            if user_id in guild_data:
                await self.config.member_from_ids(guild_id, user_id).clear()
