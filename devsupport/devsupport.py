import asyncio
import logging
import random
import re
from copy import copy
from datetime import datetime, timedelta

import discord
from typing import Union

from discord.ext import tasks
from redbot.core import Config, commands, checks
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions

logger = logging.getLogger("red.RedAppsv2.devsupport")

StatusInfo = {
    "bug": {
        0: "En attente d'examen",
        1: "Bug résolu",
        2: "Correction prévue dans une future MAJ",
        3: "Correction impossible",
        4: "Correction inutile"
    },
    "proposition": {
        0: "En attente d'examen",
        1: "Proposition publiée et disponible",
        2: "Développement en cours",
        3: "Proposition impossible à réaliser",
        4: "Proposition refusée"
    }
}

class DevSupport(commands.Cog):
    """Commandes dédiées du développement du bot"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_global = {"Tickets": {},
                          "TicketsChannel": None,
                          "TicketNumber": 1}
        self.config.register_global(**default_global)

    @commands.command(name="ticket")
    async def submit_ticket(self, ctx, ticket_type: str, *, msg: str):
        """Soumettre une proposition ou signaler un bug

        Faire une proposition = `;ticket suggest`
        Signaler un bug = `;ticket bug`"""
        submit_channel = self.bot.get_channel(await self.config.TicketsChannel())

        if ticket_type.lower() not in ("bug", "suggest", "suggestion", "proposition", "propose"):
            return await ctx.send(f"**Type du ticket inconnu** • Soumettez une proposition avec `;ticket suggest` "
                                  f"ou signalez un bug avec `;ticket bug`")
        ticket_type = "Bug" if ticket_type.lower() == "bug" else "Proposition"

        if submit_channel:
            if len(msg) >= 10:
                num = await self.config.TicketNumber()
                bid = f"T{num:04d}"
                color = 0xf04747 if ticket_type.lower() == "bug" else 0x7289da

                sub = discord.Embed(title=f"Ticket #{bid} • {ticket_type}", description=box(msg),
                                    color=color, timestamp=ctx.message.created_at)
                sub.add_field(name="Auteur", value=f"**{ctx.author}** ({ctx.author.id})")
                sub.set_footer(text=f"Statut : " + StatusInfo[ticket_type.lower()][0])
                submit_msg = await submit_channel.send(embed=sub)

                data = {'embed_msg': submit_msg.id, 'type': ticket_type.lower(), 'status': 0,
                        'text': msg, 'author': ctx.author.id}
                await self.config.Tickets.set_raw(bid, value=data)
                await self.config.TicketNumber.set(num + 1)

                em = discord.Embed(title=f"Soumettre un ticket » #{bid} ({ticket_type})", description=box(msg),
                                   color=color)
                em.set_footer(text=f"Consultez le statut de votre ticket avec \";ticketinfo {bid}\"")

                await ctx.send(embed=em)
            else:
                await ctx.send(f"**Trop court** • Veuillez donner plus de détails.")
        else:
            await ctx.send(f"**Fonctionnalité désactivée** • Soumettez plutôt une proposition/bug en utilisant `;contact`.")

    @commands.command(name="ticketinfo")
    async def ticket_info(self, ctx, ticket_id: str):
        """Vérifier le statut d'un ticket"""
        submit_channel = self.bot.get_channel(await self.config.TicketsChannel())
        ticket_id = ticket_id.upper()
        if submit_channel:
            if 'T' not in ticket_id:
                return await ctx.send(f"**ID invalide** • L'ID d'un ticket est sous le format `T0123`")

            data = await self.config.Tickets()
            if ticket_id in data:
                ticket = data[ticket_id]
                color = 0xf04747 if ticket['type'].lower() == "bug" else 0x7289da
                sub = discord.Embed(title=f"Ticket #{ticket_id}", description=box(ticket['text']), color=color)
                author = self.bot.get_user(ticket['author'])
                author = f"**{author}** ({ctx.author.id})" if author else "ID: " + ticket['author']
                sub.add_field(name="Auteur", value=f"{author}")
                sub.set_footer(text=f"Statut : " + StatusInfo[ticket['type'].lower()][ticket['status']])
                await ctx.send(embed=sub)
            else:
                await ctx.send(f"**Proposition introuvable** • Vérifiez l'identifiant.")
        else:
            await ctx.send(f"**Fonctionnalité désactivée** • Soumettez plutôt une proposition/bug en utilisant `;contact`.")

    @commands.command(name="ticketedit", aliases=["tedit"])
    @checks.is_owner()
    async def ticket_edit(self, ctx, ticket_id: str, status: int = None):
        """Editer le statut d'un ticket"""
        submit_channel = self.bot.get_channel(await self.config.TicketsChannel())
        ticket_id = ticket_id.upper()

        if submit_channel:
            data = await self.config.Tickets()
            if ticket_id in data:
                ticket = data[ticket_id]

                if not status:
                    txt = ""
                    for t in StatusInfo[ticket['type'].lower()]:
                        txt += "**{}** : {}\n".format(t, StatusInfo[ticket['type'].lower()][t])
                    em = discord.Embed(title=f"Statuts valides ({ticket['type']})", description=txt)
                    return await ctx.send(embed=em)

                if status != ticket['status'] and status in StatusInfo[ticket['type'].lower()]:
                    ticket['status'] = status
                    msg = await submit_channel.fetch_message(ticket['embed_msg'])
                    bem = msg.embeds[0]
                    bem.timestamp = ctx.message.created_at
                    bem.set_footer(text=f"Statut : " + StatusInfo[ticket['type'].lower()][ticket['status']])
                    await self.config.Tickets.set_raw(ticket_id, value=ticket)
                    await msg.edit(embed=bem)
                    await ctx.send(f"**Statut modifié** • Message : <{msg.jump_url}>")
                else:
                    await ctx.send(f"**Statut invalide** • Vérifiez que ce num. de statut existe "
                                   f"et que c'est pas déjà le statut actuel du ticket.")
            else:
                await ctx.send(f"**Proposition introuvable** • Vérifiez l'identifiant.")
        else:
            await ctx.send(f"**Fonctionnalité désactivée** • Activez-là en définissant un salon d'arrivée.")

    @commands.command(name="ticketchannel")
    @checks.is_owner()
    async def ticket_channel_set(self, ctx, channel: discord.TextChannel = None):
        """Configure un salon textuel pour la réception des tickets

        Ne rien mettre désactive la fonctionnalité"""
        if not channel:
            await self.config.TicketsChannel.set(None)
            await ctx.send("**Fonctionnalité désactivée** • Vous ne recevrez plus de tickets par cette voie.")
        else:
            await self.config.TicketsChannel.set(channel.id)
            await ctx.send(f"**Fonctionnalité activée** • Les tickets arriveront sur {channel.mention}.")


    @commands.group(name="publictest", aliases=['pt'])
    async def _public_testing(self, ctx):
        """Ensemble de commandes à tester (Public)"""
        
    @_public_testing.command(name='radargame')
    async def test_radar_minigame(self, ctx):
        """Mini-jeu où on doit faire passer un satellite d'un côté à l'autre
        
        Intégration prévue dans le prochain jeu 'Astral'"""
        user, guild = ctx.author, ctx.guild
        arrows = ['➡️', '⬅️', '⬆️', '⬇️', '↗️', '↘️', '↙️', '↖️']
        goods = random.sample(arrows, k=3)
        affs = [f"🛰️ {goods[0]} · {goods[1]} · {goods[2]} ✅",
                f"· {goods[0]} 🛰️ {goods[1]} · {goods[2]} ✅",
                f"· {goods[0]} · {goods[1]} 🛰️ {goods[2]} ✅",
                f"· {goods[0]} · {goods[1]} · {goods[2]} 🛰️"]

        affnb = 0
        random.shuffle(arrows)
        msg = None
        while affnb < 3:
            em = discord.Embed(description=box(
                affs[affnb]), color=user.color)
            em.set_footer(
                text="› Cliquez sur les bonnes réactions dans l'ordre (5s)")
            if not msg:
                msg = await ctx.send(embed=em)
                start_adding_reactions(msg, arrows)
            else:
                await msg.edit(embed=em)

            try:
                react, _ = await self.bot.wait_for("reaction_add", check=lambda m, u: u == ctx.author and m.message.id == msg.id,
                                                   timeout=5)
            except asyncio.TimeoutError:
                em.description = affs[affnb].replace('🛰️', '💥')
                txt = ["Loupé", "Manqué", "Echec"]
                nrg = random.randint(4, 8)
                em.set_footer(
                    text=f"{random.choice(txt)} › Vous perdez {nrg}x ⚡")
                return await msg.edit(embed=em)

            if react.emoji == goods[affnb]:
                affnb += 1
                continue
            else:
                em.description = affs[affnb].replace('🛰️', '💥')
                txt = ["Loupé", "Manqué", "Echec"]
                nrg = random.randint(2, 5)
                em.set_footer(
                    text=f"{random.choice(txt)} › Vous perdez {nrg}x ⚡")
                return await msg.edit(embed=em)
            
        em = discord.Embed(description=box(affs[affnb]), color=user.color)
        em.set_footer(text="Vous avez réussi !")
        await msg.edit(embed=em)
