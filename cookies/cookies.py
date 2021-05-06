import asyncio
import json
import logging
import operator
import re

import random
import os
import string
import time
from datetime import datetime, timedelta
from fuzzywuzzy import process

import discord
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils.menus import start_adding_reactions, menu, DEFAULT_CONTROLS

from typing import Union, Tuple, List
from redbot.core import Config, commands, checks, errors
from redbot.core.utils.chat_formatting import box, humanize_number, humanize_timedelta
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.Cookies")


class Cookies(commands.Cog):
    """Simulateur de Fortune cookies"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'Cookies': {},
                         
                         'price': 30,
                         'reward': 10,
                         'cookie_life': 3,
                         'cooldown': 3600,
                         'cookie_delay': 86400,
                         
                         'report_channel': None,
                         'reports': []}

        default_member = {'last_cookie': {}}
        
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

    async def import_old_data(self):
        """Attention : écrase les données présentes sur le serveur"""
        try:
            fortune_config = Config.get_conf(None, identifier=736144321857978388, cog_name="Fortune")
            guilds = self.bot.guilds
            n = 1
            for guild in guilds:
                imported = {}
                logger.info(msg=f"{n}. Importation des données Fortune de : {guild.id}")
                cookies = await fortune_config.guild(guild).COOKIES()
                for c in cookies:
                    cookie = {'text': cookies[c]['text'], 'author': cookies[c]['author'], 'posts': cookies[c]['logs'], 'score': 1}
                    imported[c] = cookie
                await self.config.guild(guild).Cookies.set(imported)
                n += 1
        except:
            return False
        return True
    
    async def get_random_cookie(self, guild: discord.Guild, filter_users: List[discord.Member]):
        cookies = await self.config.guild(guild).Cookies()
        weighted = {}

        def last_posted(k):
            try:
                return k[-1]
            except IndexError:
                return 0
            
        for c in cookies:
            if cookies[c]['author'] in [m.id for m in filter_users] or last_posted(cookies[c]['posts']) + await self.config.guild(guild).cookie_delay() > time.time():
                continue
            
            weighted[c] = cookies[c]['score']
            
        if weighted:
            return random.choices(list(weighted.keys()), weights=list(weighted.values()), k=1)[0]
        return None
                    
    
    @commands.command(name='cookie', aliases=['f'])
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def get_fortune_cookie(self, ctx):
        """Obtenir un fortune cookie aléatoire"""
        guild, author = ctx.guild, ctx.author
        config = await self.config.guild(guild).all()
        cookie_id = await self.get_random_cookie(guild, [author])
        like, dislike = '👍', '👎'
        if not cookie_id:
            return await ctx.reply("**Réserve vide** › Il n'y a actuellement aucun cookie disponible.\nVous pouvez contribuer à en ajouter avec `;addf` !",
                                   mention_author=False)
        
        finance = self.bot.get_cog('Finance')
        currency = await finance.get_currency(guild)
        
        lc = await self.config.member(author).last_cookie()
        if lc:
            cooldown = lc['timestamp']
            if cooldown + config['cooldown'] > time.time():
                td = humanize_timedelta(seconds=int(
                    (cooldown + config['cooldown']) - time.time()))
                return await ctx.reply(f"**Cooldown** › Vous devez attendre encore "
                                    f"*{td}* avant de pouvoir acheter un autre cookie.", mention_author=False)
        
        if not await finance.enough_credits(author, config['price']):
            return await ctx.reply(f"**Solde insuffisant** › Il vous faut {config['price']}{currency} pour acheter un cookie.", mention_author=False)
    
        cookie = config['Cookies'][cookie_id]
        async with ctx.typing():
            await finance.remove_credits(author, config['price'], reason="Achat d'un fortune cookie")
            
            em = discord.Embed(description=cookie['text'], color=author.color)
            em.set_footer(
                text=f"Vous avez payé {config['price']}{currency}", icon_url='https://i.imgur.com/Lv9E1uL.png')
            
            if 'http' in cookie['text']:
                scan = re.compile(r'(https?://\S*\.\S*)', re.DOTALL | re.IGNORECASE).findall(cookie['text'])
                if scan:
                    em.set_image(url=scan[0])
                    name = scan[0].split('/')[-1]
                    if "?" in name:
                        name = name.split('?')[0]
                    if not name:
                        name = "URL"
                    txt = cookie['text'].replace(scan[0], f"[[{name}]]({scan[0]})")
                    em.description = txt

            cookie_author = guild.get_member(cookie['author'])
            msg = await ctx.reply(embed=em, mention_author=False)
            
            await self.config.member(author).last_cookie.set({'author': cookie_author.id if cookie_author else None, 'text': em.description, 
                                                              'tipped': False, 'timestamp': time.time(), 'cookie_id': cookie_id})
        
        start_adding_reactions(msg, [like, dislike])
        try:
            react, _ = await self.bot.wait_for("reaction_add",
                                                    check=lambda m,
                                                                u: u == ctx.author and m.message.id == msg.id,
                                                    timeout=60)
        except asyncio.TimeoutError:
            await msg.clear_reactions()
        
        rfooter = ""
        if cookie_author:
            rfooter += f"{cookie_author.name}"
            if react.emoji == like:
                cookie['score'] *= 2
                rfooter += f" {config['reward']:+}{currency}"
                await finance.deposit_credits(cookie_author, config['reward'], reason="Like d'un de vos fortune cookie")
                
            elif react.emoji == dislike:
                cookie['score'] /= 2
        
            if cookie['posts']:
                rfooter += ' ♻️'
            cookie['posts'].append(time.time())
            
            await self.config.guild(guild).Cookies.set_raw(cookie_id, value=cookie)
            
            if cookie['score'] <= 0.25:
                rfooter += ' 🗑️'
                await self.config.guild(guild).Cookies.clear_raw(cookie_id)
            
            if len(cookie['posts']) >= config['cookie_life']:
                rfooter += ' ⌛'
                await self.config.guild(guild).Cookies.clear_raw(cookie_id)
            
            em.set_footer(text=rfooter, icon_url=cookie_author.avatar_url)
        else:
            rfooter += f'Auteur inconnu'
            await self.config.guild(guild).Cookies.clear_raw(cookie_id)
            
            em.set_footer(text=rfooter)
        
        await msg.edit(embed=em, mention_author=False)
        
    @commands.command(name='cookieadd', aliases=['addf', 'fadd'])
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def add_new_cookie(self, ctx, *, texte: str):
        """Ajouter un nouveau fortune cookie sur ce serveur
        
        - Vous êtes récompensé lorsqu'un membre like votre cookie
        - Les URL sont formattés automatiquement et les images peuvent s'afficher directement dans l'embed
        - Les cookies expirent automatiquement au bout d'un certain nombre d'apparitions
        - Un cookie peut être supprimé si son score est trop bas (<= 0.25)
        - Vous ne pouvez pas tomber sur vos propres cookies"""
        guild, author = ctx.guild, ctx.author
        config = await self.config.guild(guild).all()
        finance = self.bot.get_cog('Finance')
        curr = await finance.get_currency(guild)
        
        if len(texte) < 10 or len(texte) > 1000:
            return await ctx.reply("**Longueur invalide** › Le message du cookie doit faire entre 10 et 1000 caractères, liens compris.", mention_author=False)
        
        if len(ctx.message.mentions) > 3:
            return await ctx.reply("**Spam de mentions** › Votre message comporte trop de mentions de membres.", mention_author=False)
        
        is_flood = lambda t: bool([m for m in t.split() if t.split().count(m) > len(t.split()) / 2] if len(t.split()) >= 4 else False)
        if is_flood(texte):
            return await ctx.reply("**Flood** › Votre message comporte trop de répétitions et s'apparente à du flood.", mention_author=False)
        
        all_cookies = [config['Cookies'][c]['text'].lower() for c in config['Cookies']]
        dist = process.extractOne(texte.lower(), all_cookies, score_cutoff=85)
        if dist:
            return await ctx.reply("**Doublon** › Votre message est trop proche (> 85% de similiarité) avec un cookie déjà présent.", mention_author=False)
        
        cookie = {'text': texte, 'author': author.id, 'posts': [], 'score': 1}
        cookie_id = f"{int(time.time())}-{author.id}"
        await self.config.guild(guild).Cookies.set_raw(cookie_id, value=cookie)
        await ctx.reply(f"**Cookie ajouté** › Votre cookie a été ajouté, vous recevrez une récompense de {config['reward']}{curr} si un membre like votre message.", 
                        mention_author=False, delete_after=20)
        try:
            await ctx.message.delete(delay=10)
        except Exception:
            pass
        
    @commands.command(name='tip', aliases=['tips'])
    @commands.guild_only()
    async def tip_cookie_author(self, ctx, somme: int = None):
        """Permet de donner un tip à l'auteur du dernier cookie acheté
        
        Par défaut le tip prendra la valeur définie comme récompense lors des like de cookie"""
        author, guild = ctx.author, ctx.guild
        if not somme:
            somme = await self.config.guild(guild).reward() if await self.config.guild(guild).reward() > 0 else 1
            
        last_cookie = await self.config.member(author).last_cookie()
        finance = self.bot.get_cog('Finance')
        currency = await finance.get_currency(guild)
        confirm, cancel = self.bot.get_emoji(
            812451214037221439), self.bot.get_emoji(812451214179434551)
        
        if not last_cookie:
            return await ctx.send("**Aucun cookie acheté** › Vous n'avez aucun cookie dans votre historique d'achats.")
        
        cookie_price = await self.config.guild(guild).price()
        if somme <= 0 or somme > cookie_price:
            return await ctx.send(f"**Valeur invalide** › Le tip doit être compris entre 1 et la valeur d'achat ({cookie_price}{currency}).")
        
        if not await finance.enough_credits(author, somme):
            return await ctx.send("**Solde insuffisant** › Vous n'avez pas les moyens de tipper cette somme.")
        
        if last_cookie['tipped']:
            return await ctx.send("**Déjà tippé** › Vous ne pouvez pas donner plus d'un seul tip par cookie.")
        
        if last_cookie['author']:
            lc_author = guild.get_member(last_cookie['author'])
            em = discord.Embed(title=f"Envoyer un tip à **{lc_author.name}**", color=author.color)
            em.add_field(name="Texte du cookie", value=box(last_cookie['text']))
            em.set_footer(text=f"Voulez-vous envoyer {somme}{currency} à l'auteur de ce cookie pour le récompenser ?")
            msg = await ctx.reply(embed=em, mention_author=False)
            
            start_adding_reactions(msg, [confirm, cancel])
            try:
                react, _ = await self.bot.wait_for("reaction_add",
                                                        check=lambda m,
                                                                    u: u == ctx.author and m.message.id == msg.id,
                                                        timeout=30)
            except asyncio.TimeoutError:
                return await msg.delete()

            if react.emoji == confirm:
                await msg.clear_reactions()
                await self.config.member(author).last_cookie.set_raw('tipped', value=True)
                await finance.transfert_credits(author, lc_author, somme, reason="Tip d'un fortune cookie")
                em.set_footer(text=f"Vous avez envoyé {somme}{currency} à {lc_author.name}")
                return await msg.edit(embed=em, mention_author=False)
            else:
                return await msg.delete()
        else:
            await ctx.send("**Auteur inconnu** › L'auteur de votre dernier cookie acheté ne semble plus être sur ce serveur et ne peut donc recevoir de tips.")

    @commands.command(name='report')
    @commands.guild_only()
    async def report_cookie(self, ctx):
        """Signaler le contenu du dernier cookie obtenu"""
        author, guild = ctx.author, ctx.guild
        last_cookie = await self.config.member(author).last_cookie()
        config = await self.config.guild(guild).all()
        confirm, cancel = self.bot.get_emoji(
            812451214037221439), self.bot.get_emoji(812451214179434551)
        
        if not last_cookie:
            return await ctx.send("**Aucun cookie acheté** › Vous n'avez aucun cookie dans votre historique d'achats.")
        
        cookies = await self.config.guild(guild).Cookies()
        try:
            cookie_id = last_cookie['cookie_id']
            _c = cookies[cookie_id]
        except:
            return await ctx.send("**Cookie inexistant** › Le cookie en question n'existe déjà plus dans la base de données, il a peut-être expiré ou a déjà été supprimé.")
        
        em = discord.Embed(title=f"Signaler le cookie *{cookie_id}*", color=author.color)
        em.add_field(name="Texte du cookie", value=box(last_cookie['text']))
        em.set_footer(text=f"Voulez-vous signaler ce cookie aux modérateurs ?")
        msg = await ctx.reply(embed=em, mention_author=False)
            
        start_adding_reactions(msg, [confirm, cancel])
        try:
            react, _ = await self.bot.wait_for("reaction_add",
                                                    check=lambda m,
                                                                u: u == ctx.author and m.message.id == msg.id,
                                                    timeout=30)
        except asyncio.TimeoutError:
            return await msg.delete()

        if react.emoji == confirm:
            await msg.clear_reactions()
            if config['report_channel']:
                chan = self.bot.get_channel(config['report_channel'])
                if chan:
                    r = discord.Embed(title="Signalement d'un cookie", description=f"**ID :** `{cookie_id}`", color=discord.Color.red())
                    r.add_field(name="Texte du cookie signalé", value=box(last_cookie['text']))
                    r.set_footer(text=f"Supprimer : \";cookieset delete {cookie_id}\"\nVoir tous les signalements : \";reports\"")
                    await chan.send(embed=r)
            
            async with self.config.guild(guild).reports() as reports:
                if cookie_id not in reports:
                    reports.append(cookie_id)
                    
            em.set_footer(text=f"Votre signalement a bien été enregistré")
            await msg.edit(embed=em, mention_author=False)
            await msg.delete(delay=20)
        else:
            return await msg.delete()
        
    @commands.command(name='reports')
    @commands.guild_only()
    @checks.admin_or_permissions(manage_messages=True)
    async def list_reports(self, ctx):
        """Liste tous les cookies signalés
        
        Pour en supprimer, utilisez ';cookieset delete'"""
        guild = ctx.guild
        reports = await self.config.guild(guild).reports()
        cookies = await self.config.guild(guild).Cookies()
        tabl = []
        to_del = []
        if not reports:
            return await ctx.send("**Aucun signalement** › Aucun cookie n'a été signalé.")
        
        for r in reports:
            try:
                cookie = cookies[r]
                tabl.append((r, cookie['text'] if len(cookie['text']) < 40 else cookie['text'][:37] + '...'))
            except:
                to_del.append(r)
                
        new_cookies = cookies
        for d in to_del:
            new_cookies.remove(d)
        await self.config.guild(guild).Cookies.set(new_cookies)
        
        if tabl:
            rem = discord.Embed(title="Cookies signalés", description="```py\n" + tabulate(tabl, headers=('ID', 'Texte')) + "```"), color=discord.Color.red())
            rem.set_footer(text="Supprimez-en avec ';cookieset delete <ID>'")
            await ctx.send(embed=rem)
        else:
            await ctx.send("**Liste vide** › Aucun cookie présentement en circulation n'est signalé.")
    
    
    @commands.group(name="cookieset")
    @checks.admin_or_permissions(manage_messages=True)
    async def _cookie_settings(self, ctx):
        """Groupe des commandes de gestion des fortune cookies"""
        
    @_cookie_settings.command()
    async def price(self, ctx, val: int = 30):
        """Modifie le prix des cookies
        
        C'est aussi la valeur maximale d'un tip
        Par défaut 30 crédits"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).price.set(val)
            await ctx.send(f"**Valeur modifiée** • Les fortunes cookies coûteront désormais {val} crédits.")
        else:
            await ctx.send(f"**Valeur invalide** • Le prix du fortune cookie doit être supérieur ou égal à 0 crédits.")

    @_cookie_settings.command()
    async def reward(self, ctx, val: int = 10):
        """Modifie la valeur de la récompense attribuée lors d'un like
        
        Par défaut 10 crédits"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).reward.set(val)
            await ctx.send(f"**Valeur modifiée** • Les fortunes cookies coûteront désormais {val} crédits.")
        else:
            await ctx.send(f"**Valeur invalide** • Le prix du fortune cookie doit être supérieur ou égal à 0 crédits.")
    
    @_cookie_settings.command()
    async def cooldown(self, ctx, val: int = 3600):
        """Modifie le temps en secondes entre l'achat de deux cookies
        
        Par défaut 1h (3600s)"""
        guild=ctx.guild
        if val >= 0:
            await self.config.guild(guild).cooldown.set(val)
            await ctx.send(f"**Valeur modifiée** • Les fortunes cookies pourront désormais être achetés toutes les {val}s.")
        else:
            await ctx.send(f"**Valeur invalide** • La valeur doit être supérieure ou égale à 0s.")
        
    @_cookie_settings.command()
    async def delay(self, ctx, val: int = 86400):
        """Modifie le temps minimal en secondes qu'il faut à un cookie pour réapparaitre une nouvelle fois
        
        Par défaut 1j (86400s)"""
        guild=ctx.guild
        if val >= 0:
            await self.config.guild(guild).cookie_delay.set(val)
            await ctx.send(f"**Valeur modifiée** • Un même fortune cookie pourra désormais réapparaitre toutes les {val}s.")
        else:
            await ctx.send(f"**Valeur invalide** • La valeur doit être supérieure ou égale à 0s.")
            
    @_cookie_settings.command()
    async def life(self, ctx, val: int = 3):
        """Modifie le nombre d'apparitions maximales d'un cookie (durée de vie)
        
        Par défaut 3x"""
        guild=ctx.guild
        if val >= 1:
            await self.config.guild(guild).cookie_life.set(val)
            await ctx.send(f"**Valeur modifiée** • Les cookies pourront désormais apparaître {val}x.")
        else:
            await ctx.send(f"**Valeur invalide** • La valeur doit être supérieure ou égale à 1.")
    
    @_cookie_settings.command()
    async def reportchannel(self, ctx, channel: discord.TextChannel = None):
        """Configure un channel écrit pour recevoir les signalements, ne rien mettre désactive cette fonctionnalité
        
        Si aucun salon n'est configuré, vous pouvez toujours voir les signalements avec ';reports'"""
        guild=ctx.guild
        if channel:
            await self.config.guild(guild).report_channel.set(channel.id)
            await ctx.send(f"**Salon modifiée** • Les signalements seront envoyés sur {channel.mention}.")
        else:
            await ctx.send(f"**Salon retiré** • Les signalements ne seront pas envoyés sur un salon. Utilisez `;reports` pour voir les signalements.")
    
    @_cookie_settings.command()
    async def deletetext(self, ctx, *, texte: str):
        """Supprimer un cookie - par une recherche de texte"""
        config = await self.config.guild(ctx.guild).all()
        all_cookies = [config['Cookies'][c]['text'].lower() for c in config['Cookies']]
        dist = process.extractOne(texte.lower(), all_cookies, score_cutoff=70)
        emcolor = discord.Color.red()
        confirm, cancel = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)
        if dist:
            txt = dist[0]
            for cook in config['Cookies']:
                if config['Cookies'][cook]['text'].lower() == txt:
                    cookie = config['Cookies'][cook]
                    em = discord.Embed(title="Supprimer un fortune cookie", description=box(cookie['text']),
                                       color=emcolor)
                    seller = ctx.guild.get_member(cookie['author'])
                    seller = str(seller) if seller else str(cookie['author'])
                    em.set_footer(text=f"Confirmez-vous la suppression de ce cookie de {seller} ?")
                    msg = await ctx.send(embed=em)

                    start_adding_reactions(msg, [confirm, cancel])
                    try:
                        react, _ = await self.bot.wait_for("reaction_add",
                                                               check=lambda m,
                                                                            u: u == ctx.author and m.message.id == msg.id,
                                                               timeout=30)
                    except asyncio.TimeoutError:
                        return await msg.clear_reactions()

                    if react.emoji == confirm:
                        await msg.clear_reactions()
                        await self.config.guild(ctx.guild).Cookies.clear_raw(cook)
                        em.set_footer(text="Le cookie a été supprimé avec succès")
                        
                        async with self.config.guild(ctx.guild).reports() as reports:
                            if cook in reports:
                                reports.remove(cook)
                        
                        return await msg.edit(embed=em, mention_author=False)
                    else:
                        return await msg.delete()
        await ctx.send("**Introuvable** • Donnez une partie plus importante du texte du cookie pour que je puisse le trouver")
        
    @_cookie_settings.command()
    async def delete(self, ctx, cookie_id: str):
        """Supprimer un cookie - par l'identifiant"""
        guild = ctx.guild
        confirm, cancel = self.bot.get_emoji(
            812451214037221439), self.bot.get_emoji(812451214179434551)
        
        cookies = await self.config.guild(guild).Cookies()
        try:
            cookie = cookies[cookie_id]
        except:
            return await ctx.send("**Cookie inexistant** › Le cookie en question n'existe déjà plus dans la base de données, il a peut-être expiré ou a déjà été supprimé.")
        
        em = discord.Embed(title="Supprimer un fortune cookie", description=box(cookie['text']), color=discord.Color.red())
        seller = guild.get_member(cookie['author'])
        seller = str(seller) if seller else str(cookie['author'])
        em.set_footer(text=f"Confirmez-vous la suppression de ce cookie de {seller} ?")
        msg = await ctx.send(embed=em)

        start_adding_reactions(msg, [confirm, cancel])
        try:
            react, _ = await self.bot.wait_for("reaction_add",
                                                    check=lambda m,
                                                                u: u == ctx.author and m.message.id == msg.id,
                                                    timeout=30)
        except asyncio.TimeoutError:
            return await msg.clear_reactions()

        if react.emoji == confirm:
            await msg.clear_reactions()
            await self.config.guild(ctx.guild).Cookies.clear_raw(cookie_id)
            em.set_footer(text="Le cookie a été supprimé avec succès")
            
            async with self.config.guild(guild).reports() as reports:
                if cookie_id in reports:
                    reports.remove(cookie_id)
            
            return await msg.edit(embed=em, mention_author=False)
        else:
            await msg.delete()
            
    @_cookie_settings.command()
    async def deleteuser(self, ctx, users: commands.Greedy[discord.Member]):
        """Supprime tous les cookies créées par les utilisateurs visés"""
        guild = ctx.guild
        cookies = await self.config.guild(guild).Cookies()
        nb = 0
        for c in cookies:
            if cookies[c]['author'] in [u.id for u in users]:
                await self.config.guild(guild).Cookies.clear_raw(c)
                nb += 1
        await ctx.send(f"**Cookies supprimés** • {nb} cookies des membres visés ont été supprimés avec succès.")

    @_cookie_settings.command()
    async def resetlast(self, ctx, users: commands.Greedy[discord.Member]):
        """Reset les informations sur le dernier cookie des utilisateurs visés"""
        for user in users:
            await self.config.member(user).cookie_last.clear()
        await ctx.send(f"**Données reset** • Les membres sélectionnés n'ont plus aucun 'dernier cookie' enregistré.")

    @_cookie_settings.command()
    async def clearall(self, ctx):
        """Supprime tous les fortune cookies du serveur"""
        await self.config.guild(ctx.guild).clear_raw('Cookies')
        await ctx.send(
            f"**Fortune cookies supprimés** • La liste est désormais vide pour ce serveur.")
    