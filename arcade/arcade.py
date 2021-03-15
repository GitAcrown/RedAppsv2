import asyncio
import json
import logging
import random

import discord
from redbot.core import commands, Config
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.chat_formatting import box
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.arcade")

BOMBPARTY_WORDLIST = [
    'ENT', 'ONS', 'ASS', 'RAI', 'ION',
    'SSE', 'RON', 'SSI', 'IEN', 'AIS',
    'AIE', 'AIT', 'TER', 'ERI', 'ONN',
    'ANT', 'ERO', 'RAS', 'ISS', 'SER',
    'TES', 'REN', 'ONT', 'RIE', 'CON',
    'SES', 'LER', 'SIO', 'SEN', 'NER',
    'RIO', 'SIE', 'MES', 'ÈRE', 'QUE',
    'ISE', 'RER', 'CHA', 'TIO', 'NTE',
    'LIS', 'IER', 'ÉES', 'TRA', 'ATI',
    'NNE', 'RES', 'OUR', 'SSA', 'ÂTE',
    'ERE', 'ISA', 'ÂME', 'RIS', 'TAS',
    'LAS', 'SAI', 'CHE', 'RAN', 'IQU',
    'ALI', 'DÉC', 'SAS', 'TAI', 'UER',
    'INE', 'EME', 'LAI', 'NAS', 'PAR',
    'INT', 'AGE', 'BOU', 'PER', 'ESS',
    'EUR', 'PRO', 'LLA'
]


class Arcade(commands.Cog):
    """Ensemble de mini-jeux multijoueurs utilisant l'économie de 'Finance'"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'bombparty_game_price': 50}
        self.config.register_guild(**default_guild)

        self.games = []

    async def wait_for_players(self, ctx, embed: discord.Embed, price: int = 0):
        finance = self.bot.get_cog('Finance')

        msg = await ctx.send(embed=embed)
        conf_emoji = self.bot.get_emoji(812451214037221439)
        await msg.add_reaction(conf_emoji)
        await asyncio.sleep(30)
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
            players.append(ctx.author)

        try:
            await msg.delete(delay=3)
        except:
            pass
        return players

    @commands.command(name='bombparty')
    async def play_bombparty(self, ctx, hp: int = 3):
        """Lancer une partie de Bombparty"""
        channel = ctx.channel
        if channel.id in self.games:
            return await ctx.send("**Impossible** • Un jeu est déjà en cours sur ce salon !")
        self.games.append(channel.id)
        conf_emoji = self.bot.get_emoji(812451214037221439)
        price = await self.config.guild(ctx.guild).bombparty_game_price()
        finance = self.bot.get_cog('Finance')
        curr = await finance.get_currency(ctx.guild)

        em = discord.Embed(title="💣 **Bombparty**",
                           description=f"{ctx.author.mention} a lancé une partie de **Bombparty** !\n"
                                       f"Cliquez sur {conf_emoji} pour jouer ! (30s)",
                           color=await ctx.embed_color())
        em.set_footer(text=f"Coût d'inscription : {price} {curr}")
        players = await self.wait_for_players(ctx, em, price)
        if len(players) < 2:
            self.games.remove(channel.id)
            return await ctx.reply("**Nombre de joueurs insuffisants** • Ce jeu nécessite au moins 2 joueurs")

        for u in players:
            await finance.remove_credits(u, price, reason="Participation Bombparty")

        health = {p.id: hp for p in players}
        game = True
        used = []
        cagnotte = price * len(players)
        bombtime = 12
        manche = 1

        with open(bundled_data_path(self) / 'fr-FR.json') as f:
            wordlist = json.load(f)

        await ctx.send("**La partie va commencer ...**")
        await asyncio.sleep(5)

        while game:
            for p in players:
                if health[p.id] == 0:
                    continue
                char = random.choice(BOMBPARTY_WORDLIST)
                begin = await ctx.send(f"{p.mention} → Mot contenant **{char}**")
                try:
                    word = await self.bot.wait_for('message',
                                                   timeout=bombtime,
                                                   check=lambda m: (
                                                           m.channel == ctx.channel
                                                           and m.author.id == p.id
                                                           and char.lower() in m.content.lower()
                                                           and m.content.lower() in wordlist
                                                           and not m.content.lower() in used
                                                   )
                                                   )
                except asyncio.TimeoutError:
                    health[p.id] -= 1
                    if health[p.id] > 0:
                        await begin.reply(f"{p.mention} → Temps écoulé ! **-1 PV** ({health[p.id]}/{hp})")
                    else:
                        await begin.reply(f"{p.mention} → Temps écoulé ! **-1 PV** (éliminé)")
                        players.remove(p.id)
                        if len(players) == 1:
                            winner = players[0]
                            new_solde = await finance.deposit_credits(winner, cagnotte, reason="Bombparty remporté")
                            win = discord.Embed(description=f"{winner.mention} a remporté la partie !\n"
                                                            f"Crédits gagnés : **{cagnotte}** {curr}")
                            win.set_footer(text=f"Vous avez désormais {new_solde} {curr}")
                            game = False
                            break
                else:
                    await word.add_reaction('👍')
                    used.append(word.content.lower())
                await asyncio.sleep(3)

            table = []
            ordered = list(reversed(sorted(health, key=lambda m: health[m])))
            for uid in ordered:
                u = ctx.guild.get_member(uid)
                table.append((u.name, health[u]))

            bombtime = bombtime - 1 if bombtime > 8 else 7
            rnd = discord.Embed(title="💣 Bombparty • Joueurs restants",
                                description=box(tabulate(table, headers=["Membre", "Vies"])),
                                color=await ctx.embed_color())
            rnd.set_footer(text=f"Manche #{manche} | 💣 {bombtime}s")
            manche += 1
            await ctx.send(embed=rnd)
            await asyncio.sleep(8)

        if channel.id in self.games:
            self.games.remove(channel.id)


    @commands.group(name='arcadeset', aliases=['arcset'])
    async def _arcadeset(self, ctx):
        """Paramètres des jeux Arcade"""

    @_arcadeset.command()
    async def bombprice(self, ctx, val: int = 50):
        """Modifier la somme que coûte la participation à une partie Bombparty

        Par défaut 50 crédits"""
        finance = self.bot.get_cog('Finance')
        curr = await finance.get_currency(ctx.guild)
        if val >= 0:
            await self.config.guild(ctx.guild).bombparty_game_price.set(val)
            await ctx.send(f"**Valeur modifiée** • S'inscrire à une partie Bombparty coûtera désormais {val} {curr}")
        else:
            await ctx.send(f"**Valeur invalide** • Le prix ne peut être inférieur à 0 {curr}")
