from copy import copy
from datetime import datetime, timedelta
import time
import logging
import re
from typing import Union, cast

import aiohttp
import discord
from discord.ext import tasks
from redbot.core import Config, commands, checks
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.chat_formatting import box

logger = logging.getLogger("red.RedAppsv2.EmojiVote")


class EmojiVote(commands.Cog):
    """Channel de vote pour emojis proposés par la communauté"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'channel': None,
                         'booster_bonus': True,
                         'mods_immune': True,
                         
                         'props_users': {},
                         'props_expiration': None,
                         'props_duration': 604800} # Une semaine
        self.config.register_guild(**default_guild)

        self.check_emoji_votes.start()


    @tasks.loop(minutes=1)
    async def check_emoji_votes(self):
        all_guilds = await self.config.all_guilds()
        for g in all_guilds:
            if all_guilds[g]['channel']:
                if all_guilds[g]['props_expiration'] + all_guilds[g]['props_duration'] <= time.time():
                    guild = self.bot.get_guild(g)
                    channel = guild.get_channel(all_guilds[g]['channel'])
                    await self.config.guild(guild).props_users.clear()
                    await self.config.guild(guild).props_expiration.set(time.time())
                    duration = await self.config.guild(guild).props_duration()
                    
                    ow = channel.overwrites
                    for target in [t for t in ow if type(t) in (discord.Member, discord.User)]:
                        await channel.set_permissions(ow[target], overwrite=None)
                    
                    em = discord.Embed(title="Nouvelle période de propositions d'emojis", description="Les limites de propositions ont été réinitialisées.\n" \
                                    "N'oubliez pas que vous n'avez le droit qu'à un nombre limité de propositions et qu'elles doivent être réalisées dans des messages distincts.")
                    em.add_field(name="Fin de la période*", value=box((datetime.now() + timedelta(seconds=duration)).strftime("%d/%m/%Y %H:%M")))
                    em.set_footer(text="*Estimation, la période peut terminer avant ou après si un modérateur le décide")
                    await channel.send(embed=em)

    @check_emoji_votes.before_loop
    async def before_check(self):
        logger.info('Starting check_emoji_votes loop...')
        await self.bot.wait_until_ready()
        
        
    @commands.group(name="emojivoteset", aliases=['evset'])
    @checks.admin_or_permissions(manage_messages=True)
    async def emojivote_settings(self, ctx):
        """Groupe de commandes de configuration du salon de vote d'emojis"""
        
    @emojivote_settings.command(name="channel")
    async def props_channel(self, ctx, channel: discord.TextChannel = None):
        """Configurer le salon textuel reçevant les propositions d'emojis, activant de facto la fonctionnalité sur votre serveur
        
        Ne pas préciser de salon désactive la fonctionnalité sur votre serveur"""
        if channel:
            await self.config.guild(ctx.guild).channel.set(channel.id)
            await self.config.guild(ctx.guild).props_expiration.set(time.time())
            await ctx.send(f"**Channel de proposition configuré** • Vérifiez que {channel.mention} soit correctement paramétré en permissions, notamment en donnant l'accès en écriture aux membres ayant la possibilité de proposer les emojis.")
        else:
            await self.config.guild(ctx.guild).channel.clear()
            await ctx.send("**Proposition d'emojis désactivé** • Aucun channel n'est désormais dédié à cette fonctionnalité")
            
    @emojivote_settings.command(name="immunemods")
    async def mods_immune(self, ctx):
        """Activer/désactiver l'immunité des modérateurs à la suppression/mute (permissions `manage_messages` nécessaire)"""
        current = await self.config.guild(ctx.guild).mods_immune()
        if current is True:
            await ctx.send("**Désactivé** • Les modérateurs ne sont plus immunisés dans le salon de propositions/vote")
        else:
            await ctx.send("**Activé** • Les modérateurs sont immunisés à la suppression de propositions supperflues et au mute de salon")
        await self.config.guild(ctx.guild).mods_immune.set(not current)
            
    @emojivote_settings.command(name="periode")
    async def props_duration(self, ctx, value: int = 10080):
        """Modifie le temps (en minutes) après lequel la période de vote/propositions change
        
        Par défaut 10080 (1 semaine)
        La valeur ne peut être inférieure à 30 minutes"""
        if value < 30:
            await ctx.send("**Erreur** • La période ne peut être inférieure à 30 minutes")

        value *= 60
        await self.config.guild(ctx.guild).props_duration.set(value)
        await ctx.send(f"**Valeur modifiée** • Les périodes de propositions dureront désormais {value / 60} minutes")
            
    @emojivote_settings.command(name="manualreset")
    async def manual_reset(self, ctx):
        """Démarre manuellement une nouvelle période et reset les limites de propositions
        
        Attention, cette action est irréversible"""
        guild = ctx.guild
        channel = await self.config.guild(guild).channel()
        if channel:
            channel = guild.get_channel(channel)
            await self.config.guild(guild).props_users.clear()
            await self.config.guild(guild).props_expiration.set(time.time())
            duration = await self.config.guild(guild).props_duration()
            
            em = discord.Embed(title="Nouvelle période de propositions d'emojis", description="Les limites de propositions ont été réinitialisées.\n" \
                               "N'oubliez pas que vous n'avez le droit qu'à un nombre limité de propositions et qu'elles doivent être réalisées dans des messages distincts.")
            em.add_field(name="Fin de la période*", value=box((datetime.now() + timedelta(seconds=duration)).strftime("%d/%m/%Y %H:%M")))
            em.set_footer(text="*Estimation, la période peut terminer avant ou après si un modérateur le décide")
            
            ow = channel.overwrites
            for target in [t for t in ow if type(t) in (discord.Member, discord.User)]:
                await channel.set_permissions(ow[target], overwrite=None)
            
            await channel.send(embed=em)
        else:
            await ctx.send("**Erreur** • Le salon de proposition d'emojis n'est pas configuré. Consultez `;help evset channel` pour plus d'informations.")

    @emojivote_settings.command(name="booster")
    async def booster_bonus(self, ctx):
        """Activer/désactiver la possibilité pour les boosters du serveur de proposer 2 emojis plutôt qu'un seul"""
        current = await self.config.guild(ctx.guild).booster_bonus()
        if current is True:
            await ctx.send("**Désactivé** • Les boosters du serveur n'auront plus qu'une seule proposition possible")
        else:
            await ctx.send("**Activé** • Les boosters du serveur bénéficient désormais de la possibilité de proposer deux emojis")
        await self.config.guild(ctx.guild).booster_bonus.set(not current)


    @commands.Cog.listener()
    async def on_message(self, message):
        channel, guild, author = message.channel, message.guild, message.author
        setts = await self.config.guild(guild).all()
        
        if channel.id == setts.get('channel', False):
            prop_nb = setts['props_users'].get(str(author.id), 0)
            prop_limit = 1 if not author.premium_since else 2
            props = 0
            
            if prop_nb >= prop_limit and not all([author.permissions_in(channel).manage_messages and setts['mods_immune']]):
                errortxt = "‼️ **Limite de propositions atteinte** • Vous ne pouvez pas faire plus de propositions pour la période donnée."
                if setts['booster_bonus'] and prop_limit > 1:
                    errortxt += "\n💎 Boostez le serveur pour obtenir la possibilité de faire une seconde proposition."
                try:
                    await author.send(errortxt)
                except Exception:
                    pass
                return await message.delete()
            
            urls = re.compile(r'(https?://\S*\.\S*)', re.DOTALL | re.IGNORECASE).findall(message.content)
            if message.attachments:
                props += len(message.attachments)
            if urls:
                len(urls)
            
            if props > 1:
                try:
                    txt = f"‼️ **Impossible** • Vous avez tenté de faire plus d'une proposition à la fois. Veuillez poster vos propositions dans des messages sépares (URL ou téléchargements directs)."
                    await author.send(txt)
                except Exception:
                    pass
                return message.delete()
            
            await self.config.guild(guild).props_users(author.id, value=prop_nb + props)
            if prop_nb + props >= prop_limit and not all([author.permissions_in(channel).manage_messages and setts['mods_immune']]):
                await channel.set_permissions(author, send_messages=False, reason="Proposition(s) d'emoji réalisée(s)")
            
            start_adding_reactions(message, ['⬆️','⬇️'])
        
