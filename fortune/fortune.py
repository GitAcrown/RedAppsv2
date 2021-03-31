import asyncio
import json
import logging
import operator
import re

import yaml
import random
import os
import string
import time
from datetime import datetime, timedelta
from fuzzywuzzy import process

import discord
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils.menus import start_adding_reactions, menu, DEFAULT_CONTROLS

from typing import Union, Tuple
from redbot.core import Config, commands, checks, errors
from redbot.core.utils.chat_formatting import box, humanize_number, humanize_timedelta
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.Fortune")


class Fortune(commands.Cog):
    """Comme au restaurant asiatique !"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'COOKIES': {},
                         'cookies': [], # OLD

                         'price': 50,
                         'rewards': (20, 5),

                         'cooldown': 3600,

                         'cookie_exp': 604800,
                         'cookie_delay': 86400}

        default_member = {'cookie_last': 0,
                          'stats': {'like': 0,
                                    'dislike': 0}}
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

    async def import_old_cookies(self):
        """Attention : écrase les données présentes sur le serveur"""
        guilds = await self.config.all_guilds()
        cache = {}
        for g in guilds:
            cache[g] = {}
            old = guilds[g].get('cookies', [])
            n = 0
            for k in old:
                key = f"{k['author']}-{int(time.time())}-{n}"
                n += 1
                new_cookie = {'text': k['text'], 'author': k['author'], 'created': time.time(), 'logs': [], 'malus': 0}
                cache[g][key] = new_cookie

        for s in cache:
            guild = self.bot.get_guild(s)
            if guild:
                await self.config.guild(guild).COOKIES.set(cache[s])

    @commands.command(name="fortune", aliases=['f'])
    @commands.cooldown(1, 5, commands.BucketType.member)
    async def get_fortune(self, ctx):
        """Acheter un fortune cookie parmis ceux ajoutés par les membres

        Vous pouvez en proposer avec `;addfortune`"""
        guild, author = ctx.guild, ctx.author
        finance = self.bot.get_cog('Finance')
        curr = await finance.get_currency(guild)
        approve, disapprove = self.bot.get_emoji(825055082076569679), self.bot.get_emoji(825055082084958218)

        config = await self.config.guild(guild).all()

        cooldown = await self.config.member(author).cookie_last()
        if cooldown + config['cooldown'] > time.time():
            td = humanize_timedelta(seconds=int((cooldown + config['cooldown']) - time.time()))
            return await ctx.send(f"**Cooldown** • Vous devez attendre encore "
                                  f"{td} avant de pouvoir acheter un autre fortune cookie.")

        def last_posted(k):
            try:
                return k[-1]
            except IndexError:
                return 0

        cookies = [c for c in config['COOKIES'] if last_posted(config['COOKIES'][c]['logs']) + config['cookie_delay'] <= time.time()]
        if cookies:
            if await finance.enough_credits(author, config['price']):
                key = random.choice(cookies)
                cookie = config['COOKIES'][key]

                em = discord.Embed(description=f"🥠 *{cookie['text']}*", color=author.color)

                if 'http' in cookie['text']:
                    scan = re.compile(r'(https?://\S*\.\S*)', re.DOTALL | re.IGNORECASE).findall(cookie['text'])
                    if scan:
                        em.set_image(url=scan[0])
                        name = scan[0].split('/')[-1]
                        if "?" in name:
                            name = name.split('?')[0]
                        if not name:
                            name = "média"
                        txt = cookie['text'].replace(scan[0], f"[[{name}]]({scan[0]})")
                        em.description = f"🥠 *{txt}*"

                em.set_footer(text=f"Vous avez payé {config['price']}{curr}")

                seller = guild.get_member(cookie['author'])

                msg = await ctx.reply(embed=em, mention_author=False)
                await self.config.member(author).cookie_last.set(time.time())
                await finance.remove_credits(author, config['price'], reason="Achat de fortune cookie")

                if cookie['created'] + config['cookie_exp'] < time.time():
                    await self.config.guild(guild).COOKIES.clear_raw(key)
                else:
                    cookie['logs'].append(time.time())

                start_adding_reactions(msg, [approve, disapprove])
                try:
                    react, ruser = await self.bot.wait_for("reaction_add",
                                                           check=lambda m,
                                                                        u: u == ctx.author and m.message.id == msg.id,
                                                           timeout=60)
                except asyncio.TimeoutError:
                    return await msg.clear_reactions()

                if react.emoji == approve and seller:
                    result_footer = str(seller) + f" +{config['rewards'][1]}{curr}"
                    await msg.clear_reactions()
                    if len(cookie['logs']) <= 1:
                        await finance.deposit_credits(seller, config['rewards'][0], reason="Upvote fortune cookie")
                    else:
                        await finance.deposit_credits(seller, config['rewards'][1],
                                                      reason="Upvote fortune cookie (repost)")
                        result_footer += " ♻️"

                    em.set_footer(text=str(seller) + f" +{config['rewards'][1]}{curr}",
                                  icon_url=seller.avatar_url)
                    await msg.edit(embed=em, mention_author=False)

                    seller_stats = await self.config.member(seller).stats()
                    seller_stats['like'] += 1
                    await self.config.member(seller).stats.set(seller_stats)

                elif react.emoji == disapprove and seller:
                    result_footer = str(seller)
                    if len(cookie['logs']) <= 1:
                        result_footer += " ♻️"

                    await msg.clear_reactions()
                    em.set_footer(text=str(seller), icon_url=seller.avatar_url)
                    await msg.edit(embed=em, mention_author=False)

                    seller_stats = await self.config.member(seller).stats()
                    seller_stats['dislike'] += 1
                    await self.config.member(seller).stats.set(seller_stats)

                    cookie['malus'] += 1
                    if cookie['malus'] >= 3:
                        await self.config.guild(guild).COOKIES.clear_raw(key)
                        em.set_footer(text=result_footer + " 🗑️",
                                      icon_url=seller.avatar_url)
                        await msg.edit(embed=em, mention_author=False)
                        return
                else:
                    await msg.clear_reactions()
                    em.set_footer(text=str(seller), icon_url=seller.avatar_url)
                    await msg.edit(embed=em, mention_author=False)

                await self.config.guild(guild).COOKIES.set_raw(key, value=cookie)
            else:
                await ctx.send(
                    f"**Solde insuffisant** • Un fortune cookie coûte **{config['price']}**{curr} sur ce serveur.")
        else:
            await ctx.send(f"**Stock vide** • Il n'y a plus de fortune cookie à acheter pour le moment.\n"
                           f"Contribuez à en ajouter de nouveaux avec `;addfortune` !")

    @commands.command(name="addfortune", aliases=['addf'])
    @commands.cooldown(1, 15, commands.BucketType.member)
    async def add_fortune(self, ctx, *, msg: str):
        """Ajouter un nouveau fortune cookie au serveur

        - Vous êtes récompensé lorsqu'un membre upvote votre message
        - Les URL sont formattés automatiquement et les images peuvent s'afficher directement dans l'embed
        - Les cookies expirent automatiquement au bout d'un certain délai (défini par les modérateurs)
        - Après 3 downvote, le cookie sera supprimé pour mauvaise qualité
        """
        guild, author = ctx.guild, ctx.author
        config = await self.config.guild(guild).all()
        finance = self.bot.get_cog('Finance')
        curr = await finance.get_currency(guild)

        if 5 <= len(msg) <= 1000:
            all_cookies = [config['COOKIES'][c]['text'].lower() for c in config['COOKIES']]
            dist = process.extractOne(msg.lower(), all_cookies, score_cutoff=91)
            if dist:
                return await ctx.send("**Doublon probable** • Un fortune cookie similaire existe déjà.\n"
                                      "Essayez d'être plus original dans votre message.")

            cookie = {'text': msg, 'author': author.id, 'created': time.time(), 'logs': [], 'malus': 0}
            key = f'{author.id}-{int(time.time())}'
            await self.config.guild(guild).COOKIES.set_raw(key, value=cookie)

            rep = await ctx.reply(f"**Fortune cookie ajouté** • Vous obtiendrez des crédits {curr} si un membre aime votre message.",
                                  mention_author=False)
            await ctx.message.delete(delay=15)
            await rep.delete(delay=20)
        else:
            await ctx.send("**Longueur invalide** • Le message doit faire entre 5 et 1000 caractères.")

    @commands.command(name="bestfortune", aliases=['bestf'])
    @commands.cooldown(1, 10, commands.BucketType.member)
    async def best_of_fortune(self, ctx, top: int = 10):
        """Affiche les meilleurs contributeurs aux fortune cookies du serveur"""
        guild = ctx.guild
        members = await self.config.all_members(guild)
        ratio = lambda m: round(members[m]['stats']['like'] / max((members[m]['stats']['dislike'], 1)), 2)
        clst = [(member, ratio(member)) for member in members]
        clst_sorted = sorted(clst, key=operator.itemgetter(1), reverse=True)

        tbl = []
        for l in clst_sorted[:top]:
            user = guild.get_member(l[0])
            if user:
                tbl.append([str(user), l[1]])

        if tbl:
            em = discord.Embed(title="Meilleurs contributeurs • Fortune cookies", color=await self.bot.get_embed_color(ctx.channel),
                               description=box(tabulate(tbl, headers=["Membre", "Ratio"])),
                               timestamp=ctx.message.created_at)
            em.set_footer(text="Ratio = upvote/downvote")
            try:
                await ctx.send(embed=em)
            except:
                await ctx.send(
                    "**Classement trop long** • Réduisez le paramètre [top] pour que je puisse l'afficher.")
        else:
            await ctx.send("**Aucun classement** • Il n'y a pas encore eu assez de statistiques pour créer un classement.")


    @commands.group(name="fortuneset")
    @checks.mod_or_permissions(manage_messages=True)
    async def fortune_settings(self, ctx):
        """Paramètres serveur de Fortune (Cookies)"""

    @fortune_settings.command()
    async def price(self, ctx, val: int = 50):
        """Changer le prix d'achat d'un fortune cookie

        Par défaut 50"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).price.set(val)
            await ctx.send(f"**Valeur modifiée** • Les fortunes cookies coûteront désormais {val} crédits.")
        else:
            await ctx.send(f"**Valeur invalide** • Le prix du fortune cookie doit être supérieur ou égal à 0 crédits.")

    @fortune_settings.command()
    async def rewards(self, ctx, first: int = 20, repost: int = 5):
        """Changer les sommes de récompense lors de l'upvote d'un fortune cookie

        <first> = Lors d'une première apparition (def. 20)
        <repost> = Lors d'une apparition postérieure (def. 5)"""
        guild = ctx.guild
        if first >= 0 and repost >= 0:
            await self.config.guild(guild).rewards.set((first, repost))
            await ctx.send(f"**Valeur modifiée** • Les fortunes cookies de qualité récompenseront leurs "
                           f"auteurs de {first} crédits à la première apparition puis {repost} crédits ensuite.")
        else:
            await ctx.send(f"**Valeurs invalides** • Les récompenses doivent être supérieures ou égales à 0 crédits.")

    @fortune_settings.command()
    async def cooldown(self, ctx, val: int = 3600):
        """Change le délai (en secondes) de cooldown entre deux achats de fortune cookie

        Par défaut 1h"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).cooldown.set(val)
            await ctx.send(
                f"**Valeur modifiée** • Il sera possible d'acheter un fortune cookie qu'une fois toutes les {val} secondes.")
        else:
            await ctx.send(f"**Valeur invalide** • Le délai doit être supérieur ou égal à 0 secondes.")

    @fortune_settings.command()
    async def expiration(self, ctx, val: int = 604800):
        """Change le délai (en secondes) d'expiration d'un fortune cookie

        Par défaut 7 jours"""
        guild = ctx.guild
        if val >= await self.config.guild(guild).cookie_delay():
            await self.config.guild(guild).cookie_exp.set(val)
            await ctx.send(
                f"**Valeur modifiée** • Un cookie expirera après {val} secondes.")
        else:
            await ctx.send(f"**Valeur invalide** • Le délai doit être supérieur ou égal au délai de réapparition d'un cookie.\n"
                           f"Modifiez ce paramètre avec `fortuneset delay`.")

    @fortune_settings.command()
    async def delay(self, ctx, val: int = 86400):
        """Change le délai (en secondes) de réapparition d'un cookie déjà apparu

        Par défaut 1 jour"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).cookie_delay.set(val)
            await ctx.send(
                f"**Valeur modifiée** • Un cookie pourra réapparaître après {val} secondes.")
        else:
            await ctx.send(
                f"**Valeur invalide** • Le délai doit être supérieur ou égal à 0s.")

    @fortune_settings.command()
    async def resetcd(self, ctx, users: commands.Greedy[discord.Member]):
        """Reset le cooldown de membres pour l'achat d'un fortune cookie"""
        for user in users:
            await self.config.member(user).cookie_last.set(0)
        await ctx.send(f"**Cooldowns reset** • Les membres sélectionnés peuvent dès à présent racheter un fortune cookie.")

    @fortune_settings.command()
    async def clearall(self, ctx):
        """Supprime tous les fortune cookies du serveur"""
        await self.config.guild(ctx.guild).clear_raw('cookies')
        await ctx.send(
            f"**Fortune cookies supprimés** • La liste est désormais vide.")
