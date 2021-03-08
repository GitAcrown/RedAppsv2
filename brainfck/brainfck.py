import asyncio
import logging
import yaml
import random
import os
import string
import time
from datetime import datetime
from fuzzywuzzy import process

import discord
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.menus import start_adding_reactions, menu, DEFAULT_CONTROLS

from typing import Union, Tuple
from redbot.core import Config, commands, checks, errors
from redbot.core.utils.chat_formatting import box, humanize_number
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.brainfck")


class BrainfckError(Exception):
    """Erreurs liées au module Brainfck"""

class InvalidFile(BrainfckError):
    """Soulevée lorsque le fichier .yaml est mal formatté (clés manquantes)"""

class InvalidID(BrainfckError):
    """Soulevée lorsqu'un fichier avec le même ID a été déjà chargé"""

class ContentError(BrainfckError):
    """Soulevée lorsque la clef 'content' contient trop ou trop peu de questions"""

class ReaderError(BrainfckError):
    """Soulevée lorsqu'il y a une erreur de lecture du fichier"""



class Brainfck(commands.Cog):
    """Mesurez-vous aux autres dans une série de quiz customisables !"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_global = {"Global_Leaderboard": {},
                          "Packs_Leaderboard": {},
                          "Sessions": {}}
        default_user = {"stats": {"w": 0, "d": 0, "l": 0},
                        "receive_lb_notifs": False}
        self.config.register_global(**default_global)
        self.config.register_user(**default_user)

        self.packs = cog_data_path(self) / "packs"
        self.packs.mkdir(exist_ok=True, parents=True)

        self.loaded_packs = {}

    def read_pack_file(self, path: str) -> Tuple[str, dict]:
        """Extraire un Pack de questions depuis un fichier .yaml"""
        try:
            with open(path, 'rt', encoding='utf8') as f:
                pack = yaml.safe_load(f)
        except Exception as e:
            logger.info(msg=f"Erreur dans la lecture du fichier yaml : {e}", exc_info=True)
            raise ReaderError("Erreur lors de la lecture du fichier : `{}`".format(e))

        if all([i in pack for i in ("id", "name", "description", "author_id", "content")]):
            if len(pack['id']) > 10:
                raise InvalidFile("L'ID du pack est trop long (<= 10 caractères)")

            delay = pack.get('custom_delay', 10)
            if delay < 5:
                delay = 5
            color = pack.get('color', None)
            if color:
                if self.format_color(color):
                    color = int(self.format_color(color, "0x"), base=16)
                else:
                    color = None

            new = {"name": pack['name'],
                   "description": pack['description'],
                   "author": pack['author_id'],
                   "pack_thumbnail": pack.get('thumbnail', None),
                   "content": {},
                   "delay": delay,
                   "color": color}

            for q in pack['content']:
                if 'good' in pack['content'][q] and 'bad' in pack['content'][q]:
                    if len(pack['content'][q]['bad']) >= 3:
                        add_q = {'image': pack['content'][q].get('image', None),
                                 'good': pack['content'][q]['good'],
                                 'bad': pack['content'][q]['bad'],
                                 'show': pack['content'][q].get('show', '')}
                        new['content'][q] = add_q

            if len(new['content']) < 15:
                raise ContentError("Le pack ne contient pas assez de questions valides (< 15)")

            return pack['id'], new
        raise InvalidFile("Le pack n'est pas formatté correctement, il manque des champs obligatoires (v. exemple)")

    def filespaths(self, directory):
        paths = []
        for dirpath, _, filenames in os.walk(directory):
            for f in filenames:
                if f.endswith(".yaml"):
                    paths.append(os.path.abspath(os.path.join(dirpath, f)))
        return paths

    def load_packs(self):
        self.loaded_packs = {}
        for path in self.filespaths(str(self.packs)):
            pid, content = self.read_pack_file(path)
            self.loaded_packs[pid] = content
        return self.loaded_packs

    async def reset_sessions_for(self, packid):
        sessions = await self.config.Sessions()
        for sess in sessions:
            if sessions[sess]['pack_id'] == packid:
                await self.config.Sessions.clear_raw(sess)
        return sessions

    def get_random_pack(self):
        if self.loaded_packs:
            return random.choice([i for i in self.loaded_packs])
        return None

    def format_color(self, color: str, prefixe: str = None):
        """Vérifie que la couleur donnée est un hexadécimal et renvoie la couleur avec ou sans préfixe (0x ou #)"""
        if len(color) >= 6:
            color = color[-6:]
            try:
                int(color, base=16)
                return color.upper() if not prefixe else prefixe + color.upper()
            except ValueError:
                return None
        return None

    @commands.command(name="brainfck", aliases=["bf", "quiz"])
    @commands.max_concurrency(1, commands.BucketType.user)
    async def brainfck_play(self, ctx, theme_invite: str = None):
        """Faire un Quiz Brainfck

        <theme_invite> = Identifiant du pack ou invitation
        Ne rien mettre affiche la liste des thèmes disponibles"""
        emcolor = await ctx.embed_color()
        confirm, cancel = self.bot.get_emoji(812451214037221439), self.bot.get_emoji(812451214179434551)

        if not self.loaded_packs:
            self.load_packs()

        if not theme_invite:
            txt = ""
            em = discord.Embed(title="Liste des thèmes disponibles", color=emcolor)
            page = 1
            for p in self.loaded_packs:
                nb = len(self.loaded_packs[p]['content'])
                chunk = f"• `{p}` : {self.loaded_packs[p]['description']} (#{nb})\n"
                if len(txt + chunk) < 2000:
                    txt += chunk
                else:
                    em.description = txt
                    txt = chunk
                    em.set_footer(text=f"Page #{page}")
                    await ctx.send(embed=em)
                    page += 1
            if txt:
                em.description = txt
                em.set_footer(text=f"Page #{page}")
                await ctx.send(embed=em)
            else:
                await ctx.send("**Aucun thème n'est disponible**")
            return

        sessions = await self.config.Sessions()
        packid = theme_invite.upper() if theme_invite.upper() in self.loaded_packs else None
        invite = theme_invite if theme_invite in sessions else None

        if invite:
            sess_author = self.bot.get_user(int(sessions[invite]['author']))
            if ctx.author == sess_author:
                return await ctx.send(f"**Impossible de jouer** • Vous êtes l'auteur de ce défi, vous ne pouvez pas vous défier vous-même !")
            sess_pack_id = sessions[invite]['pack_id']
            sess_players = sessions[invite]['leaderboard']
            if ctx.author.id in [int(us) for us in sess_players]:
                return await ctx.send(f"**Impossible d'y rejouer** • Votre score ({sess_players[ctx.author.id]} points)"
                                      f" figure déjà dans le classement pour cette partie !")
            theme_invite = self.loaded_packs[sess_pack_id]
            packid = sess_pack_id
            packname = theme_invite['name']
            emcolor = theme_invite['color'] if theme_invite['color'] else emcolor
            em = discord.Embed(color=emcolor)
            em.set_footer(text="Accepter | Annuler")
            em.add_field(name=packname, value=theme_invite['description'])
            if theme_invite['pack_thumbnail']:
                em.set_thumbnail(url=theme_invite['pack_thumbnail'])

            if sess_author:
                desc = f"**{sess_author.name}** vous a défié sur ***{packname}***"
                em.description = desc
                em.set_author(name=sess_author, icon_url=sess_author.avatar_url)
            else:
                desc = f"Un joueur inconnu vous a défié sur ***{packname}***"
                em.description = desc
                em.set_author(name=self.bot.user.name, icon_url=self.bot.user.avatar_url)

            conf = await ctx.send(embed=em)
            start_adding_reactions(conf, [confirm, cancel])

            try:
                react, ruser = await self.bot.wait_for("reaction_add",
                                                       check=lambda m,
                                                                    u: u == ctx.author and m.message.id == conf.id,
                                                       timeout=30)
            except asyncio.TimeoutError:
                return await conf.delete()
            if react.emoji == cancel:
                return await conf.delete()

        elif packid:
            theme_invite = self.loaded_packs[packid]
            emcolor = theme_invite['color'] if theme_invite['color'] else emcolor
            em = discord.Embed(color=emcolor, description=theme_invite['description'], title=theme_invite['name'])
            em.set_footer(text="Jouer | Annuler")
            if theme_invite['pack_thumbnail']:
                em.set_thumbnail(url=theme_invite['pack_thumbnail'])
            conf = await ctx.send(embed=em)
            start_adding_reactions(conf, [confirm, cancel])

            try:
                react, ruser = await self.bot.wait_for("reaction_add",
                                                       check=lambda m,
                                                                    u: u == ctx.author and m.message.id == conf.id,
                                                       timeout=30)
            except asyncio.TimeoutError:
                return await conf.delete()
            if react.emoji == cancel:
                return await conf.delete()
        else:
            return await ctx.send("**Identifiant de thème ou code de partie invalide** • Consultez la liste des thèmes avec `;bf` ou vérifiez que l'invitation donnée est correcte (Attention aux 'O'/0)")

        seed = sessions[invite]['seed'] if invite else random.randint(1, 999999)
        rng = random.Random(seed)
        pack = theme_invite

        await ctx.send("**La partie va commencer ...**")
        await asyncio.sleep(3)

        manche = 1
        pts = 0
        letters = [i for i in '🇦🇧🇨🇩']
        present_session = {'author': ctx.author.id,
                           'pack_id': packid,
                           'answers': {},
                           'score': 0,
                           'seed': seed,
                           'leaderboard': {}}
        qlist = list(pack['content'].keys())
        timelimit = pack['delay']
        while manche <= 6:
            question = rng.choice(qlist)
            qlist.remove(question)
            good = pack['content'][question]['good']
            bad = rng.sample(pack['content'][question]['bad'], 3)
            reps = [good] + bad
            rng.shuffle(reps)

            if manche != 6:
                em = discord.Embed(title=f"{pack['name']} • Question #{manche}",
                                   description=box(question), color=emcolor)
                em.set_footer(text="Préparez-vous ...")
            else:
                em = discord.Embed(title=f"{pack['name']} • Question #{manche} (BONUS)",
                                   description=box(question), color=emcolor)
                em.set_footer(text="Préparez-vous ... (x2 points)")

            if pack['content'][question]['image']:
                em.set_image(url=pack['content'][question]['image'])

            start = await ctx.send(embed=em)
            await asyncio.sleep((0.075 * len(question)) + 1)

            rtxt = ""
            rdict = {}
            for rep in reps:
                rindex = reps.index(rep)
                rtxt += f"{letters[rindex]} → {rep}\n"
                rdict[letters[rindex]] = rep
            em.add_field(name="Réponses possibles", value=rtxt)
            em.set_footer(text=f"Répondez avec les emojis ci-dessous | {str(timelimit)}s")
            await start.edit(embed=em)

            start_adding_reactions(start, letters)
            starttime = time.time()

            try:
                react, ruser = await self.bot.wait_for("reaction_add",
                                                       check=lambda m,
                                                                    u: u == ctx.author and m.message.id == start.id,
                                                       timeout=timelimit)
            except asyncio.TimeoutError:
                react, ruser = None, None
            finally:
                timescore = time.time() - starttime
                if timescore > 10:
                    timescore = 10
                roundscore = round((10 - timescore) * 10)

                if manche != 6:
                    end = discord.Embed(title=f"{pack['name']} • Question #{manche}",
                                       description=box(question), color=emcolor)
                else:
                    end = discord.Embed(title=f"{pack['name']} • Question #{manche} (BONUS)",
                                       description=box(question), color=emcolor)
                    roundscore *= 2

                reptxt = ""
                waittime = 5

                if react:
                    if rdict.get(react.emoji, None) == good:
                        present_session['answers'][question] = {'answer': good,
                                                                'time': timescore}
                        pts += roundscore
                        reptxt += random.choice((f"Bravo ! La bonne réponse était **{good}** !",
                                                 f"Bien joué ! La réponse était évidemment **{good}** !",
                                                 f"Bonne réponse ! Il fallait répondre **{good}**"))
                    else:
                        present_session['answers'][question] = {'answer': rdict[react.emoji],
                                                                'time': timescore}
                        reptxt += random.choice((f"Dommage ! La bonne réponse était **{good}** !",
                                                 f"Manqué ! La réponse était **{good}** !",
                                                 f"Mauvaise réponse ! Il fallait répondre **{good}**"))

                    end.set_footer(text=f"Vous avez répondu en {round(timescore, 2)}s | Score actuel = {pts}")
                else:
                    present_session['answers'][question] = {'answer': None,
                                                            'time': timescore}
                    reptxt += random.choice((f"Une absence ? La bonne réponse était **{good}** !",
                                             f"Aucune réponse ? La réponse était **{good}** !"))

                    end.set_footer(text=f"Vous n'avez pas répondu | Score actuel = {pts}")

                if invite:
                    waittime += 3
                    reptxt += "\n"
                    sess_author = self.bot.get_user(int(sessions[invite]['author']))
                    sess_rep = sessions[invite]['answers'][question]['answer']
                    if sess_rep == None:
                        sess_rep = "[Aucune réponse]"
                    sess_time = round(sessions[invite]['answers'][question]['time'], 2)

                    is_good = "(Bonne réponse)" if sess_rep == good else "(Mauvaise réponse)"
                    advname = sess_author.name if sess_author else "Votre adversaire"
                    reptxt += f"***{advname}*** a répondu *{sess_rep}* {is_good} en {sess_time}s"

                end.add_field(name="Réponse", value=reptxt)

                if pack['content'][question].get('show', False):
                    end.add_field(name="Détails", value=pack['content'][question]['show'])
                    waittime += 0.03 * len(pack['content'][question]['show'])

                await start.edit(embed=end)

                manche += 1
                await asyncio.sleep(waittime)

        present_session['score'] = pts
        result = discord.Embed(title=f"{pack['name']} • Fin de la partie", color=emcolor)

        if invite:
            sess_author = self.bot.get_user(int(sessions[invite]['author']))
            dvname = sess_author.name if sess_author else "Votre adversaire"
            sess_score = sessions[invite]['score']
            sessions[invite]['leaderboard'][ctx.author.id] = pts
            if pts > sess_score:
                result.description = f"Bravo, vous avez battu **{dvname}** !\n" \
                                     f"- __Votre score__ : {pts}\n" \
                                     f"- Son score : {sess_score}"
                notifdesc = f"**{ctx.author.name}** a participé à votre défi [{invite}] sur le thème ***{pack['name']}*** et a gagné :\n" \
                            f"- Son score : {pts}\n" \
                            f"- __Votre score__ : {sess_score}"
            elif pts == sess_score:
                result.description = f"Vous avez fait égalité avec **{dvname}** !\n" \
                                     f"- Vos scores : {pts}"
                notifdesc = f"**{ctx.author.name}** a participé à votre défi [{invite}] sur le thème ***{pack['name']}*** et a fait le même score que vous (égalité) :\n" \
                            f"- Vos scores : {pts}"
            else:
                result.description = f"Vous avez perdu face à **{dvname}** !\n" \
                                     f"- __Votre score__ : {pts}\n" \
                                     f"- Son score : {sess_score}"
                notifdesc = f"**{ctx.author.name}** a participé à votre défi [{invite}] sur le thème ***{pack['name']}*** et a perdu :\n" \
                            f"- Son score : {pts}\n" \
                            f"- __Votre score__ : {sess_score}"
            await self.config.Sessions.set_raw(invite, value=sessions[invite])
            result.set_footer(text=f"Votre score a été enregistré au leaderboard de ce défi. Consultez-le avec \";bfl {invite}\"")

            notif = discord.Embed(description=notifdesc, color=await ctx.embed_color())
            notif.set_author(name=ctx.author, icon_url=ctx.author.avatar_url)
            if pack['pack_thumbnail']:
                notif.set_thumbnail(url=pack['pack_thumbnail'])
            notif.set_footer(text="Notification de défi Brainfck")
            try:
                await sess_author.send(embed=notif)
            except:
                pass

        else:
            newinvite = lambda: "&" + str(''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(5)))
            sessinvite = newinvite()
            while newinvite in sessions:
                sessinvite = newinvite()
            await self.config.Sessions.set_raw(sessinvite, value=present_session)
            if pts >= 500: encour = " Excellent !"
            elif pts >= 350: encour = " Bien joué !"
            elif pts >= 200: encour = " Pas mal."
            else:
                encour = ""
            result.description = f"Vous avez fait un score de **{pts} points**.{encour}"
            result.add_field(name="Code de la partie", value=box(sessinvite))
            result.set_footer(text="Partagez ce code pour défier d'autres personnes sur ce thème !")
        await ctx.send(embed=result)

    @commands.command(name='bfleaderboard', aliases=['bfl'])
    async def brainfck_leaderboard(self, ctx, invite: str):
        """Affiche le leaderboard sur une partie (défi)"""
        sessions = await self.config.Sessions()
        if not self.loaded_packs:
            self.load_packs()

        if invite in sessions:
            lb = sessions[invite]['leaderboard']
            if lb:
                pack_id = sessions[invite]['pack_id']
                auteur = self.bot.get_user(int(sessions[invite]['author']))
                autname = auteur if auteur else "Inconnu"
                pack = self.loaded_packs.get(pack_id, None)
                sess_score = sessions[invite]['score']
                packname = pack['name'] if pack else f"SUPPR:{pack_id}"

                embeds = []
                tabl = []
                for u in lb:
                    if len(tabl) < 20:
                        tabl.append((self.bot.get_user(int(u)) if self.bot.get_user(int(u)) else str(u), lb[u]))
                    else:
                        em = discord.Embed(title=f"Partie [{invite}] sur le thème \"{packname}\"",
                                           color=await ctx.embed_color())
                        em.description = box(tabulate(tabl, headers=("Pseudo", "Score")))
                        em.set_footer(text=f"Auteur du défi : {autname} | Score : {sess_score}")
                        embeds.append(em)
                        tabl = []

                if tabl:
                    em = discord.Embed(title=f"Partie [{invite}] sur le thème \"{packname}\"",
                                       color=await ctx.embed_color())
                    em.description = box(tabulate(tabl, headers=("Nom", "Score")))
                    em.set_footer(text=f"Auteur : {autname} | Score : {sess_score}")
                    embeds.append(em)

                if embeds:
                    return await menu(ctx, embeds, DEFAULT_CONTROLS)
            return await ctx.send(f"**Aucun score** • Il n'y a aucun score à afficher pour ce code de partie")
        else:
            await ctx.send(f"**Code invalide** • Vérifiez que le code donné corresponde à un code de partie valide")

    @commands.command(name="brainfcknotif", aliases=['bfnotif'])
    async def brainfck_allow_notifs(self, ctx):
        """Active/Désactive la réception d'une notification quand quelqu'un termine votre défi"""
        base = await self.config.user(ctx.author).receive_lb_notifs()
        if base:
            await self.config.user(ctx.author).receive_lb_notifs.set(False)
            await ctx.send("**Notifications désactivées** • Vous ne recevrez plus de notifications lorsqu'un membre termine un de vos défis")
        else:
            await self.config.user(ctx.author).receive_lb_notifs.set(True)
            await ctx.send(
                "**Notifications activées** • Vous recevrez des notifications lorsqu'un membre termine un de vos défis")

    @commands.group(name="brainfckset", aliases=['bfset'])
    @checks.is_owner()
    async def _brainfuck_settings(self, ctx):
        """Gestion des paramètres Brainfck"""

    @_brainfuck_settings.command()
    async def getfile(self, ctx, name: str):
        """Charge sur Discord un Pack de questions"""
        name += ".yaml"
        path = self.packs / name
        try:
            await ctx.send("Voici votre fichier :", files=[discord.File(path)])
        except:
            await ctx.send("**Fichier introuvable**")

    async def save_file(self, msg: discord.Message):
        filename = msg.attachments[0].filename
        file_path = "{}/{}".format(str(self.packs), filename)
        await msg.attachments[0].save(file_path)
        self.load_packs()
        return file_path

    @_brainfuck_settings.command()
    async def addfile(self, ctx):
        """Ajoute un fichier aux packs"""
        files = ctx.message.attachments
        if files:
            path = await self.save_file(ctx.message)
            await ctx.send("**Fichier sauvegardé** • Chemin = `{}`".format(path))

        else:
            await ctx.send("**Erreur** • Aucun fichier attaché au message")

    @_brainfuck_settings.command()
    async def deletefile(self, ctx, name: str):
        """Supprime un fichier .yaml des packs"""
        name += ".yaml"
        path = self.packs / name
        try:
            os.remove(str(path))
            await ctx.send("**Fichier supprimé**")
            self.load_packs()
        except Exception as e:
            logger.error(msg=f"Fichier non supprimé ({path})", exc_info=True)
            await ctx.send(f"**Erreur** • Impossible de supprimer le fichier : `{e}`")

    @_brainfuck_settings.command()
    async def files(self, ctx):
        """Liste les fichiers dispos pour le Quiz"""
        arr_txt = [x for x in os.listdir(str(self.packs)) if x.endswith(".yaml")]
        if arr_txt:
            em = discord.Embed(title="Fichiers Brainfck disponibles", description="\n".join([f"*{n}*" for n in arr_txt]))
            await ctx.send(embed=em)
        else:
            await ctx.send(f"**Vide** • Aucun fichier n'est disponible")

    @_brainfuck_settings.command()
    async def reload(self, ctx):
        """Recharge manuellement la liste des packs chargés"""
        try:
            self.load_packs()
        except Exception as e:
            await ctx.send(f"**Erreur** : `{e}`")
            raise
        else:
            await ctx.send("**Pack de questions rechargés**")

    @_brainfuck_settings.command()
    async def resetsess(self, ctx, packid: str):
        """Reset les sessions d'un pack"""
        if packid in self.loaded_packs:
            await self.reset_sessions_for(packid)
            await ctx.send(f"**Reset des sessions de {packid} effectué**")
        else:
            await ctx.send("**Le pack demandé n'est pas chargé**")
