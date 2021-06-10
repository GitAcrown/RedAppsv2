import json
import logging
import operator
import random
import time
import asyncio
from copy import copy
from datetime import datetime, timedelta
from typing import List, Union

import discord
from discord.ext import tasks
from fuzzywuzzy import process
from redbot.core import commands, Config, checks
from redbot.core.commands.requires import PermStateTransitions
from redbot.core.config import Value
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.Royale")

ROYALE_FOOTER, ROYALE_ICON, ROYALE_COLOR = 'Royale BETA', 'https://i.imgur.com/GVHrOHh.png', 0xFFC107

default_cache = {'game_status': 0,
                 'players': {}}


class RoyaleError(Exception):
    """Classe de base pour les erreurs Royale"""


class Royale(commands.Cog):
    """Simulateur de Battle Royale"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=736144321857978388, force_registration=True)
        
        default_guild = {
            'joining_fee': 50
        }

        default_member = {}

        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)
        
        self.cache = {}
    
    # Se charge avec __init__.py au chargement du module
    async def _load_bundled_data(self):
        events_data = bundled_data_path(self) / 'events.json'
        with events_data.open() as json_data:
            self.events = json.load(json_data)
        logger.info("Pack d'Event Royale d'origine chargé")
        
    def get_cache(self, channel: discord.TextChannel) -> dict:
        if channel.id not in self.cache:
            self.cache[channel.id] = default_cache
        return self.cache[channel.id]
    
    async def wait_for_players(self, ctx, embed: discord.Embed, price: int = 0):
        finance = self.bot.get_cog('Finance')

        msg = await ctx.send(embed=embed)
        conf_emoji = self.bot.get_emoji(812451214037221439)
        await msg.add_reaction(conf_emoji)
        await asyncio.sleep(60)
        msg = await ctx.channel.fetch_message(msg.id)
        reaction = [r for r in msg.reactions if r.emoji == conf_emoji][0]
        players = []
        async for user in reaction.users():
            if not user.bot:
                if await finance.enough_credits(user, price):
                    players.append(user)
                else:
                    await ctx.send(f"{user.mention} → Fonds insuffisants sur votre compte")

        if ctx.author not in players:
            if await finance.enough_credits(ctx.author, price):
                players.append(ctx.author)
            else:
                await ctx.send(f"{ctx.author.mention} → Fonds insuffisants sur votre compte")

        try:
            await msg.delete(delay=3)
        except Exception:
            pass
        return players
        
    # COMMANDES =========================================
    
    @commands.group(name='royale', invoke_without_command=True)
    @commands.guild_only()
    async def royale_main(self, ctx):
        """Battle Royale sur Discord"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.create_join_game)
        
    @royale_main.command(name='play')
    async def create_join_game(self, ctx):
        """Créer une partie de Royale ou en rejoindre une déjà ouverte sur ce salon"""
        author, channel, guild = ctx.author, ctx.channel, ctx.guild
        cache = self.get_cache(channel)
        sys = await self.config.guild(guild).all()
        finance = self.bot.get_cog('Finance')
        creds = await finance.get_currency(guild)
        
        if cache['game_status'] is 0: # Aucune partie en cours sur ce channel
            if not finance.enough_credits(author, sys['joining_fee']):
                await ctx.reply(f"**Fonds insuffisants** • Vous n'avez pas assez de crédits ({sys['joining_fee']}{creds}) pour jouer.")
            
            em = discord.Embed(description=f"{author.mention} **a lancé une partie de Royale sur ce salon.**\nPour s'inscrire à cette partie, cliquez sur la réaction ci-dessous.\nL'inscription coûte {sys['joining_fee']}{creds}.",
                               color=ROYALE_COLOR)
            em.set_footer(text=ROYALE_FOOTER + ' (60s)', icon_url=ROYALE_ICON)
            
            cache['players'] = {}
            plist = await self.wait_for_players(ctx, em, sys['joining_fee'])
            
            if len(plist) < 2:
                return await ctx.send("**Nombre de joueurs insuffisants** • Pour lancer une partie il faut minimum 2 joueurs. La partie est donc annulée.")
            
            for m in plist:
                await finance.remove_credits(m, sys['joining_fee'], reason="Frais d'inscription Royale")
                cache['players'][m.id] = {}
            
            cache['game_status'] = 1
            debem = discord.Embed(description="La partie va débuter dans peu de temps.\nVoici ci-dessous les participants, que le meilleur gagne !",
                                  color=ROYALE_COLOR)
            txt = " | ".join([m.mention for m in plist])
            debem.add_field(name="Participants", value=txt)
            em.set_footer(text=ROYALE_FOOTER, icon_url=ROYALE_ICON)
            await ctx.send(embed=debem)
        else:
            await ctx.send("**Une partie est déjà en cours** • Veuillez attendre la fin avant d'en lancer un sur ce salon, ou lancez-en une en parallèle sur un autre salon écrit autorisé.")
    
    @commands.group(name="royaleset")
    @checks.admin_or_permissions(manage_messages=True)
    async def royale_settings(self, ctx):
        """Commandes de gestion du jeu Royale"""
        
    @royale_settings.command(name="fee")
    async def joining_fee(self, ctx, value: int = 50):
        """Modifie la valeur des frais d'inscription pour rejoindre/lancer une partie Royale 
        
        Par défaut 50 crédits"""
        if value >= 0:
            await self.config.guild(ctx.guild).joining_fee.set(value)
            await ctx.send(f"**Valeur modifiée** • Il faudra désormais débourser {value} crédits pour rejoindre/créer une partie")
        else:
            await ctx.send("**Erreur** • La valeur ne peut être négative")
        
    @royale_settings.command(name="resetcache")
    async def reset_cache(self, ctx, channel: discord.TextChannel = None):
        """Reset le cache de la partie sur un channel défini"""
        channel = channel if channel else ctx.channel
        if channel.id in self.cache:
            self.cache[channel.id] = default_cache
        await ctx.send(f"**Reset effectué** • Le reset du cache de Royale sur {channel.mention} a été effectué")
    
    # TRIGGERS ==========================================
