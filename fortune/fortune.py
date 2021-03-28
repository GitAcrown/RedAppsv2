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

        default_guild = {'cookies': [],
                         'price': 50,
                         'reward': 20,
                         'delay': 21600}  # = 6 heures
        default_member = {'cookie_last': 0,
                          'stats': {'like': 0,
                                    'dislike': 0}}
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

    @commands.command(name="fortune", aliases=['f'])
    @commands.cooldown(1, 3, commands.BucketType.member)
    async def get_fortune(self, ctx):
        """Obtenez un fortune cookie parmis ceux ajoutés par la communauté (contre des crédits)

        Ils sont uniques et n'apparaîtront qu'une seule fois
        Vous pouvez en proposer avec `;addfortune`"""
        guild, author = ctx.guild, ctx.author
        finance = self.bot.get_cog('Finance')
        curr = await finance.get_currency(guild)
        config = await self.config.guild(guild).all()
        approve, disapprove = self.bot.get_emoji(825055082076569679), self.bot.get_emoji(825055082084958218)

        cooldown = await self.config.member(author).cookie_last()
        if cooldown + config['delay'] > time.time():
            td = humanize_timedelta(seconds=int((cooldown + config['delay']) - time.time()))
            return await ctx.send(f"**Cooldown** • Vous devez attendre encore "
                                  f"{td} avant de pouvoir acheter un autre fortune cookie.")

        cookies = config['cookies']
        if cookies:
            if await finance.enough_credits(author, config['price']):
                select = random.choice(cookies)
                async with self.config.guild(guild).cookies() as cks:
                    cks.remove(select)


                em = discord.Embed(description=f"🥠 *{select['text']}*", color=author.color)

                if 'http' in select['text']:
                    scan = re.compile(r'(https?://\S*\.\S*)', re.DOTALL | re.IGNORECASE).findall(select['text'])
                    if scan:
                        em.set_image(url=scan[0])

                em.set_footer(text=f"Vous avez payé {config['price']}{curr}")

                seller = guild.get_member(select['author'])

                msg = await ctx.reply(embed=em, mention_author=False)
                await self.config.member(author).cookie_last.set(time.time())
                await finance.remove_credits(author, config['price'], reason="Achat de fortune cookie")

                start_adding_reactions(msg, [approve, disapprove])
                try:
                    react, ruser = await self.bot.wait_for("reaction_add",
                                                           check=lambda m,
                                                                        u: u == ctx.author and m.message.id == msg.id,
                                                           timeout=60)
                except asyncio.TimeoutError:
                    return await msg.clear_reactions()

                if react.emoji == approve and seller:
                    await msg.clear_reactions()
                    await finance.deposit_credits(seller, config['reward'], reason="Upvote fortune cookie")
                    em.set_footer(text=str(seller) + f" +{config['reward']}{curr}", icon_url=seller.avatar_url)
                    await msg.edit(embed=em, mention_author=False)

                    seller_stats = await self.config.member(seller).stats()
                    seller_stats['like'] += 1
                    await self.config.member(seller).stats.set(seller_stats)
                elif react.emoji == disapprove and seller:
                    await msg.clear_reactions()
                    em.set_footer(text=str(seller), icon_url=seller.avatar_url)
                    await msg.edit(embed=em, mention_author=False)

                    seller_stats = await self.config.member(seller).stats()
                    seller_stats['dislike'] += 1
                    await self.config.member(seller).stats.set(seller_stats)
                else:
                    await msg.clear_reactions()
                    em.set_footer(text=str(seller), icon_url=seller.avatar_url)
                    await msg.edit(embed=em, mention_author=False)
            else:
                await ctx.send(f"**Solde insuffisant** • Un fortune cookie coûte **{config['price']}**{curr} sur ce serveur.")
        else:
            await ctx.send(f"**Stock vide** • Il n'y a plus de fortune cookie à acheter.\n"
                           f"Contribuez à en ajouter de nouveaux avec `;addfortune` !")

    @commands.command(name="addfortune", aliases=['addf'])
    @commands.cooldown(1, 10, commands.BucketType.member)
    async def add_fortune(self, ctx, *, msg: str):
        """Propose un nouveau fortune cookie unique à ajouter au serveur

        Vous serez récompensé d'un certain montant si la personne qui l'obtient décide d'Upvoter votre message
        Si vous mettez l'URL d'une image, celle-ci sera affichée directement"""
        guild, author = ctx.guild, ctx.author
        config = await self.config.guild(guild).all()
        finance = self.bot.get_cog('Finance')
        curr = await finance.get_currency(guild)

        if 10 <= len(msg) <= 1000:
            all_cookies = [c['text'].lower() for c in config['cookies']]
            dist = process.extractOne(msg.lower(), all_cookies, score_cutoff=91)
            if dist:
                return await ctx.send("**Message de basse qualité** • Un fortune cookie similaire se trouve déjà dans mes fichiers. "
                                      "Copier/coller des messages similaires en masse ne fonctionnera pas 🤡")

            async with self.config.guild(guild).cookies() as cks:
                cookie = {'text': msg, 'author': author.id}
                cks.append(cookie)
            rep = await ctx.reply(f"**Fortune cookie ajouté** • Vous obtiendrez {config['reward']}{curr} si le membre upvote votre message.", mention_author=False)
            await ctx.message.delete(delay=15)
            await rep.delete(delay=15)
        else:
            await ctx.send("**Longueur invalide** • Le message doit faire entre 10 et 1000 caractères.")

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
            em = discord.Embed(title="Meilleurs contributeurs", color=await self.bot.get_embed_color(ctx.channel),
                               description=box(tabulate(tbl, headers=["Membre", "Ratio"])),
                               timestamp=ctx.message.created_at)
            em.set_footer(text="Ratio = like / dislike")
            try:
                await ctx.send(embed=em)
            except:
                await ctx.send(
                    "**Classement trop long** • Réduisez le paramètre [top].")
        else:
            await ctx.send("**Aucun classement** • Il n'y a pas encore eu assez de statistiques pour créer un classement.")

    @commands.group(name="fortuneset")
    @checks.mod_or_permissions(manage_messages=True)
    async def fortune_settings(self, ctx):
        """Paramètres serveur de Fortune (Cookies)"""

    @fortune_settings.command()
    async def price(self, ctx, val: int = 50):
        """Changer le prix d'achat d'un fortune cookie"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).price.set(val)
            await ctx.send(f"**Valeur modifiée** • Les fortunes cookies coûteront désormais {val} crédits.")
        else:
            await ctx.send(f"**Valeur invalide** • Le prix du fortune cookie doit être supérieur ou égal à 0 crédits.")

    @fortune_settings.command()
    async def reward(self, ctx, val: int = 20):
        """Changer la somme de la récompense aux fortune cookies de qualité"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).reward.set(val)
            await ctx.send(f"**Valeur modifiée** • Les fortunes cookies de qualité récompenseront leurs auteurs de {val} crédits.")
        else:
            await ctx.send(f"**Valeur invalide** • La récompense doit être supérieure ou égale à 0 crédits.")

    @fortune_settings.command()
    async def delay(self, ctx, val: int = 21600):
        """Change le délai (en secondes) de cooldown entre deux achats de fortune cookie"""
        guild = ctx.guild
        if val >= 0:
            await self.config.guild(guild).delay.set(val)
            await ctx.send(
                f"**Valeur modifiée** • Il sera possible d'acheter un fortune cookie qu'une fois toutes les {val} secondes.")
        else:
            await ctx.send(f"**Valeur invalide** • Le délai doit être supérieur ou égal à 0 secondes.")

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
