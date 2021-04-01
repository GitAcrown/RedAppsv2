import asyncio
import logging
import logging
import os
import re
import time
import uuid
from io import BytesIO
from typing import Optional
from urllib.parse import urlsplit

import aiofiles
import aiohttp
import discord
from PIL import Image, ImageSequence, ImageOps
from redbot.core import Config, commands, checks
from redbot.core.data_manager import cog_data_path, bundled_data_path

from .converters import ImageFinder

logger = logging.getLogger("red.RedAppsv2.imgedit")

FILES_LINKS = re.compile(
    r"(https?:\/\/[^\"\'\s]*\.(?:png|jpg|jpeg|gif|svg|mp4)(\?size=[0-9]*)?)", flags=re.I
)


class ImgEdit(commands.Cog):
    """Commandes d'édition d'images"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        self.temp = cog_data_path(self) / "temp"
        self.temp.mkdir(exist_ok=True, parents=True)

    async def download(self, url: str, path: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        with open(path, "wb") as f:
                            f.write(data)
                        return resp.headers.get("Content-type", "").lower()
        except asyncio.TimeoutError:
            return False

    async def bytes_download(self, url: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        mime = resp.headers.get("Content-type", "").lower()
                        b = BytesIO(data)
                        b.seek(0)
                        return b, mime
                    else:
                        return False, False
        except asyncio.TimeoutError:
            return False, False
        except Exception:
            logger.error("Impossible de télécharger en bytes-like", exc_info=True)
            return False, False

    def paste_image(self, input_path: str, output_path: str, paste_img_path: str, *,
                    scale: float = 1.0, margin: tuple = (0, 0), mirror: bool = False, position: str = 'bottom_right'):
        paste = Image.open(paste_img_path).convert('RGBA')
        try:
            image = Image.open(input_path).convert('RGBA')
        except:
            image = Image.open(input_path).convert('RGB')
        image_width, image_height = image.size

        if mirror:
            paste = ImageOps.mirror(paste)

        paste.thumbnail((round(image_width / scale), round(image_width / scale)))

        if position.lower() == 'bottom_left':
            pos = (0 + margin[0], image_height - margin[1] - paste.size[1])
        elif position.lower() == 'top_left':
            pos = (0 + margin[0], 0 + margin[1])
        elif position.lower() == 'top_right':
            pos = (image_width - margin[0] - paste[0], 0 + margin[1])
        else:
            pos = (image_width - paste.size[0] - margin[0], image_height - paste.size[1] - margin[1])

        if input_path.endswith('gif') or input_path.endswith('gifv'):
            image = Image.open(input_path)
            dur = 1000 / image.info['duration']
            frames = []
            for frame in ImageSequence.Iterator(image):
                transparent = Image.new('RGBA', (image_width, image_height), (0, 0, 0, 0))
                transparent.paste(frame, (0, 0))
                transparent.paste(paste, pos, mask=paste)
                frames.append(transparent)
            frames[0].save(output_path, format='GIF', append_images=frames[1:], save_all=True,
                           loop=0, duration=round(dur * 0.90))
        else:
            transparent = Image.new('RGBA', (image_width, image_height), (0, 0, 0, 0))
            transparent.paste(image, (0, 0))
            transparent.paste(paste, pos, mask=paste)
            transparent.save(output_path, format='PNG')
        return output_path


    async def add_fp_gun(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                        margin_x: int = 0, margin_y: int = 0, *, mirrored: bool = False):
        if prpt <= 0:
            return await ctx.send("**Proportion invalide** • La valeur de proportion doit être supérieure à 0.")

        if url is None:
            url = await ImageFinder().search_for_images(ctx)
        msg = await ctx.message.channel.send("⏳ Patientez pendant la préparation de votre image")

        async with ctx.typing():
            url = url[0]
            filename = urlsplit(url).path.rsplit('/')[-1]
            filepath = str(self.temp / filename)
            try:
                await self.download(url, filepath)
            except:
                await ctx.send("**Téléchargement échoué** • Réessayez d'une autre façon")
            else:
                gun = bundled_data_path(self) / "GunWM.png"
                try:
                    task = self.paste_image(filepath, filepath, str(gun), scale=prpt, margin=(margin_x, margin_y),
                                            mirror=mirrored, position='bottom_right' if not mirrored else 'bottom_left')
                except:
                    os.remove(filepath)
                    logger.error("Impossible de faire gun_right/gun_left", exc_info=True)
                    return await ctx.send("**Erreur** • Impossible de créer l'image demandée.")

                file = discord.File(task)
                try:
                    await ctx.send(file=file)
                except:
                    await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image (probablement trop lourde)")
                    logger.error(msg="GUN : Impossible d'upload l'image", exc_info=True)
                os.remove(filepath)
            finally:
                await msg.delete()

    @commands.command(name='gunr', aliases=['gun'])
    async def gun_right(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                        margin_x: int = 0, margin_y: int = 0):
        """Ajoute un pistolet (1e personne) braqué sur la droite de l'image

        **[prpt]** = Proportion du pistolet, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image source)
        **[url]** = URL de l'image sur laquelle appliquer le filtre (optionnel)
        **[margin_x/margin_y]** = Marges à ajouter (en pixels) à l'image du pistolet par rapport aux bords de l'image source (nécéssite l'utilisation d'une URL)"""
        return await self.add_fp_gun(ctx, prpt, url, margin_x, margin_y)

    @commands.command(name='gunl')
    async def gun_left(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                       margin_x: int = 0, margin_y: int = 0):
        """Ajoute un pistolet (1e personne) braqué sur la gauche de l'image

        **[prpt]** = Proportion du pistolet, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image source)
        **[url]** = URL de l'image sur laquelle appliquer le filtre (optionnel)
        **[margin_x/margin_y]** = Marges à ajouter (en pixels) à l'image du pistolet par rapport aux bords de l'image source (nécéssite l'utilisation d'une URL)"""
        return await self.add_fp_gun(ctx, prpt, url, margin_x, margin_y, mirrored=True)


    async def add_tp_gun(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                         margin_x: int = 0, margin_y: int = 0, *, mirrored: bool = False):
        if prpt <= 0:
            return await ctx.send("**Proportion invalide** • La valeur de proportion doit être supérieure à 0.")

        if url is None:
            url = await ImageFinder().search_for_images(ctx)
        msg = await ctx.message.channel.send("⏳ Patientez pendant la préparation de votre image")

        async with ctx.typing():
            url = url[0]
            filename = urlsplit(url).path.rsplit('/')[-1]
            filepath = str(self.temp / filename)
            try:
                await self.download(url, filepath)
            except:
                await ctx.send("**Téléchargement échoué** • Réessayez d'une autre façon")
            else:
                gun = bundled_data_path(self) / "HoldUpWM.png"
                try:
                    task = self.paste_image(filepath, filepath, str(gun), scale=prpt, margin=(margin_x, margin_y),
                                            mirror=mirrored, position='bottom_left' if not mirrored else 'bottom_right')
                except:
                    os.remove(filepath)
                    logger.error("Impossible de faire tp_gun", exc_info=True)
                    return await ctx.send("**Erreur** • Impossible de créer l'image demandée.")

                file = discord.File(task)
                try:
                    await ctx.send(file=file)
                except:
                    await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image (probablement trop lourde)")
                    logger.error(msg="GUN : Impossible d'upload l'image", exc_info=True)
                os.remove(filepath)
            finally:
                await msg.delete()

    @commands.command(name='holdupr', aliases=['holupr'])
    async def holdup_right(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                        margin_x: int = 0, margin_y: int = 0):
        """Ajoute un pistolet (3e personne) braqué sur la droite de l'image

        **[prpt]** = Proportion du pistolet, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image source)
        **[url]** = URL de l'image sur laquelle appliquer le filtre (optionnel)
        **[margin_x/margin_y]** = Marges à ajouter (en pixels) à l'image du pistolet par rapport aux bords de l'image source (nécéssite l'utilisation d'une URL)"""
        return await self.add_tp_gun(ctx, prpt, url, margin_x, margin_y, mirrored=True)

    @commands.command(name='holdupl', aliases=['holdup', 'holup'])
    async def holdup_left(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                           margin_x: int = 0, margin_y: int = 0):
        """Ajoute un pistolet (3e personne) braqué sur la gauche de l'image

        **[prpt]** = Proportion du pistolet, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image source)
        **[url]** = URL de l'image sur laquelle appliquer le filtre (optionnel)
        **[margin_x/margin_y]** = Marges à ajouter (en pixels) à l'image du pistolet par rapport aux bords de l'image source (nécéssite l'utilisation d'une URL)"""
        return await self.add_tp_gun(ctx, prpt, url, margin_x, margin_y)

    async def add_vibecheck(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                         margin_x: int = 0, margin_y: int = 0, *, mirrored: bool = False):
        if prpt <= 0:
            return await ctx.send("**Proportion invalide** • La valeur de proportion doit être supérieure à 0.")

        if url is None:
            url = await ImageFinder().search_for_images(ctx)
        msg = await ctx.message.channel.send("⏳ Patientez pendant la préparation de votre image")

        async with ctx.typing():
            url = url[0]
            filename = urlsplit(url).path.rsplit('/')[-1]
            filepath = str(self.temp / filename)
            try:
                await self.download(url, filepath)
            except:
                await ctx.send("**Téléchargement échoué** • Réessayez d'une autre façon")
            else:
                gun = bundled_data_path(self) / "VibecheckWM.png"
                try:
                    task = self.paste_image(filepath, filepath, str(gun), scale=prpt, margin=(margin_x, margin_y),
                                            mirror=mirrored, position='bottom_left' if not mirrored else 'bottom_right')
                except:
                    os.remove(filepath)
                    logger.error("Impossible de faire vibcheck", exc_info=True)
                    return await ctx.send("**Erreur** • Impossible de créer l'image demandée.")

                file = discord.File(task)
                try:
                    await ctx.send(file=file)
                except:
                    await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image (probablement trop lourde)")
                    logger.error(msg="Vibecheck : Impossible d'upload l'image", exc_info=True)
                os.remove(filepath)
            finally:
                await msg.delete()

    @commands.command(name='vibecheckr', aliases=['vbr'])
    async def vibecheck_right(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                           margin_x: int = 0, margin_y: int = 0):
        """Ajoute la main Vibecheck à droite de l'image

        **[prpt]** = Proportion de la main, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image source)
        **[url]** = URL de l'image sur laquelle appliquer le filtre (optionnel)
        **[margin_x/margin_y]** = Marges à ajouter (en pixels) à l'image de la main par rapport aux bords de l'image source (nécéssite l'utilisation d'une URL)"""
        return await self.add_vibecheck(ctx, prpt, url, margin_x, margin_y, mirrored=True)

    @commands.command(name='vibecheckl', aliases=['vbl', 'vibecheck'])
    async def vibecheck_left(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None,
                              margin_x: int = 0, margin_y: int = 0):
        """Ajoute la main Vibecheck à gauche de l'image

        **[prpt]** = Proportion de la main, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image source)
        **[url]** = URL de l'image sur laquelle appliquer le filtre (optionnel)
        **[margin_x/margin_y]** = Marges à ajouter (en pixels) à l'image de la main par rapport aux bords de l'image source (nécéssite l'utilisation d'une URL)"""
        return await self.add_vibecheck(ctx, prpt, url, margin_x, margin_y)

    def paste_image_behind(self, input_path: str, output_path: str, paste_img_path: str, *, mirror: bool = False):
        front = Image.open(paste_img_path).convert('RGBA')
        try:
            image = Image.open(input_path).convert('RGBA')
        except:
            image = Image.open(input_path).convert('RGB')
        final_width, final_height = front.size

        if mirror:
            front = ImageOps.mirror(front)

        if input_path.endswith('gif') or input_path.endswith('gifv'):
            image = Image.open(input_path)
            image = image.resize((final_width, final_height))
            dur = 1000 / image.info['duration']
            frames = []
            for frame in ImageSequence.Iterator(image):
                frame.thumbnail((final_width, final_height), Image.ANTIALIAS)

                transparent = Image.new('RGBA', (final_width, final_height), (0, 0, 0, 0))
                transparent.paste(frame, (0, 0))
                transparent.paste(front, (0, 0), mask=front)
                frames.append(transparent)

            frames[0].save(output_path, format='GIF', append_images=frames[1:], save_all=True,
                           loop=0, duration=round(dur * 0.90))
        else:
            image = image.resize((final_width, final_height))
            transparent = Image.new('RGBA', (final_width, final_height), (0, 0, 0, 0))
            transparent.paste(image, (0, 0))
            transparent.paste(front, (0, 0), mask=front)
            transparent.save(output_path, format='PNG')
        return output_path

    @commands.command(name='zahando', aliases=['thehand'])
    async def za_hando(self, ctx, url: ImageFinder = None, mirror: bool = False):
        """Ajoute Za Hando sur l'image

        **[url]** = URL de l'image sur laquelle appliquer le filtre (optionnel)
        **[mirror]** = Inverse le sens de Za Hando"""

        if url is None:
            url = await ImageFinder().search_for_images(ctx)
        msg = await ctx.message.channel.send("⏳ Patientez pendant la préparation de votre image")

        async with ctx.typing():
            url = url[0]
            filename = urlsplit(url).path.rsplit('/')[-1]
            filepath = str(self.temp / filename)
            try:
                await self.download(url, filepath)
            except:
                await ctx.send("**Téléchargement échoué** • Réessayez d'une autre façon")
            else:
                gun = bundled_data_path(self) / "ZaHando.png"
                try:
                    task = self.paste_image_behind(filepath, filepath, str(gun), mirror=mirror)
                except:
                    os.remove(filepath)
                    logger.error("Impossible de faire za_hando", exc_info=True)
                    return await ctx.send("**Erreur** • Impossible de créer l'image demandée.")

                file = discord.File(task)
                try:
                    await ctx.send(file=file)
                except:
                    await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image (probablement trop lourde)")
                    logger.error(msg="GUN : Impossible d'upload l'image", exc_info=True)
                os.remove(filepath)
            finally:
                await msg.delete()

    @commands.command(name="nsfwswitch")
    @checks.mod_or_permissions(manage_messages=True)
    async def timed_nsfw(self, ctx):
        """Active temporairement la balise NSFW sur le channel actuel

        Vous avez 60s pour poster votre contenu, et 20s supplémentaires après chaque contenu"""
        channel = ctx.channel
        conf = self.bot.get_emoji(812451214037221439)
        inv = self.bot.get_emoji(812451214179434551)

        if type(channel) != discord.TextChannel:
            return await ctx.send("**Salon cible invalide** • Cette commande n'est valable que pour les salons écrits")

        if channel.is_nsfw():
            await channel.edit(nsfw=False, reason="Suppression de la balise NSFW (rétablissement)")
            return await ctx.reply(f"🔞{inv} {channel.mention} n'est plus **NSFW** (Rétablissement de son statut d'origine)",
                                   mention_author=None, delete_after=15)

        await channel.edit(nsfw=True, reason="Activation temporaire du NSFW (~60s)")
        await ctx.reply(f"🔞{conf} {channel.mention} est temporairement **NSFW**",
                        mention_author=None, delete_after=10)

        first = True
        while True:
            try:
                msg = await self.bot.wait_for('message',
                                               timeout=60 if first else 20,
                                               check=lambda m: m.channel == channel and m.author == ctx.author and m.attachments)
            except asyncio.TimeoutError:
                await channel.edit(nsfw=False, reason="Retour à la normale (Non-NSFW)")
                try:
                    await ctx.message.delete()
                except Exception:
                    pass
                return await ctx.reply(f"🔞{inv} {channel.mention} n'est plus **NSFW**",
                                       mention_author=None, delete_after=10)
