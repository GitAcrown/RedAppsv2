import community
import logging
import operator
from pickle import EMPTY_DICT
import random
import re
import time
import asyncio
from datetime import datetime, timedelta
from typing import List, Union

import discord
from discord.ext import tasks
from redbot.core import commands, Config, checks
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.chat_formatting import box
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.Community")

class Community(commands.Cog):
    """Outils communautaires divers"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=736144321857978388, force_registration=True)
        
        default_channel = {'Polls': {}}
        self.config.register_channel(**default_channel)
        
        self.community_loop.start()
        
    @tasks.loop(seconds=30.0)
    async def community_loop(self):
        all_channels = await self.config.all_channels()
        for chan in all_channels:
            polls = all_channels[chan]['Polls']
            for p in polls:
                if polls[p]['exp'] <= time.time():
                    channel = self.bot.get_channel(chan)
                    em = discord.Embed().from_dict(polls[p]['embed'])
                    em.timestamp = discord.Embed.Empty
                    em.set_footer(text='Sondage terminé')
                    
                    reps, stats = polls[p]['reps'], polls[p]['stats']
                    total = sum([len(stats[r]) for r in stats])
                    dispstats = polls[p]['disp_stats']
                    em.description = box("\n".join([f'{reps[p]} › **{p}** ({round(100 * (len(stats[p]) / max(total, 1)), 2)}%)' for p in reps])) if dispstats \
                        else box("\n".join([f'{reps[p]} › **{p}**' for p in reps]))
                    
                    message = await channel.fetch_message(p)
                    if message:
                        try:
                            await message.clear_reactions()
                        except Exception:
                            logger.warning(f'Impossible de supprimer les réactions de {message.guild.id}/{message.id}')
                        else:
                            await message.reply(embed=em)
                        
                        if polls[p]['pin']:
                            try:
                                await message.unpin()
                            except Exception:
                                pass
                    
                    await self.config.channel(channel).Polls.clear_raw(p)
                    

    @community_loop.before_loop
    async def before_community_loop(self):
        logger.info('Starting Community loop...')
        await self.bot.wait_until_ready()
        
    
    @commands.command(name="poll")
    async def create_poll(self, ctx, *, args: str):
        """Créer un sondage dynamique avec réactions
        
        **Format :** `poll Question ?;Réponse 1;Réponse 2;Réponse N...`
        
        __Options__
        `-exp X` = Modifier la durée (en minutes) après lequel le sondage expire (par def. 10m)
        `-image URL` = Ajouter une image au sondage
        `-pin` = Epingler/désépingler auto. le sondage
        `-nostats` = Désactiver les statistiques en direct
        `-anonymous` = Ne pas afficher le créateur du sondage"""
        author, channel = ctx.author, ctx.channel
        letters = [u for u in '🇦🇧🇨🇩🇪🇫🇬🇭🇮']
        
        exp = 10
        anonyme = False
        pin = False
        dispstats = True
        sus = False
        
        emcolor = discord.Color.random()
        em = discord.Embed(color=emcolor)
        
        opts = re.compile(r'-(\w*)(?:\s?([\w:\/\.?=&\-]*))?', re.DOTALL | re.IGNORECASE).findall(args)
        if opts:
            args = args.split('-')[0]
            for opt, val in opts:
                if opt.lower() == 'image':
                    em.set_image(url=val)
                elif opt.lower() == 'exp':
                    try:
                        exp = int(val)
                    except Exception:
                        pass
                    
                    if exp < 1 or exp > 720:
                        return ctx.reply("**Temps invalide** › Le sondage ne peut durer qu'entre 1 et 720m (12h)", mention_author=False)
                    else:
                        pass
                    
                elif opt.lower() in ('anonymous', 'anonyme'):
                    anonyme = True
                elif opt.lower() == 'pin':
                    pin = True
                elif opt.lower() in ('nostats', 'nostat'):
                    dispstats = False
                elif opt.lower() == 'sus':
                    sus = True

        q, *r = [i.strip() for i in re.split(';|-', args)]
        if not r:
            r = ('Pour/Oui', 'Contre/Non')
            emojis = ['👍', '👎']
        elif len(r) <= 9:
            emojis = letters[:len(r)]
        else:
            return await ctx.reply("**Trop de réponses possibles** › Vous ne pouvez mettre que 9 réponses possibles au maximum.", mention_author=False)
        
        polls = await self.config.channel(channel).Polls()
        if polls:
            poll_id = max([polls[n]['id'] for n in polls]) + 1
        else:
            poll_id = 1
        
        reps = {i: emojis[r.index(i)] for i in r}
        stats = {i: [] for i in r}
        em.timestamp = datetime.utcnow() + timedelta(minutes=exp)
        em.title = f'`#{poll_id}` · ***{q}***'
        em.description = "\n".join([f'{reps[p]} › **{p}** (0%)' for p in reps]) if dispstats else "\n".join([f'{reps[p]} › **{p}**' for p in reps])
        
        if not anonyme:
            em.set_footer(text=author.name, icon_url=author.avatar_url)

        if sus: # Easter-egg AMONGUSSSSS
            em.set_footer(
                text='Imposteur', icon_url='https://cdn2.clc2l.fr/t/A/m/Among-Us-oAEaxX.png')
            
        poll_data = {
            'embed': em.to_dict(),
            'reps': reps,
            'stats': stats,
            'id': poll_id,
            
            'exp': time.time() + (60 * exp),
            'disp_stats': dispstats,
            'pin': pin
            }
            
        msg = await ctx.send(embed=em)
        
        await self.config.channel(channel).Polls.set_raw(msg.id, value=poll_data)
        start_adding_reactions(msg, emojis)
        
        if pin:
            try:
                await msg.pin()
            except Exception:
                await ctx.send("Impossible d'épingler auto. › Je n'ai pas les permissions nécessaires (`Gestion des messages`)")
                
    @commands.command(name="pollstop")
    async def stop_poll(self, ctx, id: int = None):
        """Arrête un sondage en cours sur ce channel (par N° du sondage)
        
        Si aucun identifiant n'est précisé, renvoie une liste des sondages en cours sur le channel"""
        channel = ctx.channel
        polls = await self.config.channel(channel).Polls()
        if id:
            if [i for i in polls if polls[i]['id'] == id]:
                p = [i for i in polls if polls[i]['id'] == id][0]
                
                em = discord.Embed().from_dict(polls[p]['embed'])
                em.timestamp = discord.Embed.Empty
                em.set_footer(text='Sondage terminé')

                reps, stats = polls[p]['reps'], polls[p]['stats']
                total = sum([len(stats[r]) for r in stats])
                dispstats = polls[p]['disp_stats']
                em.description = "\n".join([f'{reps[p]} › **{p}** ({round(100 * (len(stats[p]) / max(total, 1)), 2)}%)' for p in reps]) if dispstats \
                    else "\n".join([f'{reps[p]} › **{p}**' for p in reps])

                message = await channel.fetch_message(p)
                if message:
                    try:
                        await message.clear_reactions()
                    except Exception:
                        pass
                    else:
                        await message.reply(embed=em)

                    if polls[p]['pin']:
                        try:
                            await message.unpin()
                        except Exception:
                            pass

                await self.config.channel(channel).Polls.clear_raw(p)
            else:
                await ctx.reply("**Introuvable** › Vérifiez qu'un sondage avec ce numéro existe bien __sur ce salon__", mention_author=False)
        else:
            txt = ""
            for p in polls:
                title = polls[p]['embed']['title']
                txt += title + '\n'
            
            if txt:
                em = discord.Embed(title=f"Sondages en cours sur #{channel.name}", description=txt, color=ctx.author.color)
                await ctx.send(embed=em)
            else:
                await ctx.reply("**Aucun sondage en cours** › Vous pouvez en démarrer un avec `;poll`", mention_author=False)
        
        
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        message = reaction.message
        channel = message.channel
        if not user.bot:
            polls = await self.config.channel(channel).Polls()
            if polls.get(message.id, False):
                poll = polls[message.id]
                
                if user.id in [i for s in poll['stats'] for i in poll['stats'][s]]:
                    try:
                        await message.remove_reaction(reaction.emoji, user)
                    except:
                        pass
                
                is_rep = [e for e in poll['reps'] if poll['reps'][e] == reaction.emoji]
                logger.info(f'{str(is_rep)}')
                if is_rep:
                    rep = is_rep[0]
                    poll['stats'][rep].append(user.id)
                    
                    em = discord.Embed().from_dict(poll['embed'])
                    reps, stats = poll['reps'], poll['stats']
                    total = sum([len(stats[r]) for r in stats])
                    dispstats = poll['disp_stats']
                    
                    em.description = "\n".join([f'{reps[p]} › **{p}** ({round(100 * (len(stats[p]) / max(total, 1)), 2) or 0}%)' for p in reps]) if dispstats \
                        else "\n".join([f'{reps[p]} › **{p}**' for p in reps])
                    
                    await message.edit(embed=em)
                    
                    await self.config.channel(channel).Polls.set_raw(message.id, value=poll)
