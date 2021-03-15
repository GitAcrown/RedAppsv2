import asyncio
import logging
import logging
import os
import re
import time
from io import BytesIO
from typing import Optional
from urllib.parse import urlsplit

import aiofiles
import aiohttp
import discord
from PIL import Image, ImageSequence, ImageOps
from redbot.core import Config, commands
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
                    scale: float = 1, margin: tuple = (0, 0), mirror: bool = False, position: str = 'bottom_right'):
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
            ext = frames[0].format
        else:
            transparent = Image.new('RGBA', (image_width, image_height), (0, 0, 0, 0))
            transparent.paste(image, (0, 0))
            transparent.paste(paste, pos, mask=paste)
            transparent.save(output_path, format='PNG')
            ext = transparent.format
        return output_path, ext


    @commands.command(name='gunr', aliases=['gun'])
    async def gun_right(self, ctx, prpt: Optional[float] = 1.75, url: ImageFinder = None):
        """Ajoute un pistolet (1e personne) braqué sur la droite de l'image

        [size] = Proportion du pistolet, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image fournie)
        [url] = URL de l'image sur laquelle appliquer le filtre (optionnel)"""
        if prpt <= 0:
            return await ctx.send("**Proportion invalide** • La valeur de proportion doit être supérieure à 0.")

        if url is None:
            url = await ImageFinder().search_for_images(ctx)
        msg = await ctx.message.channel.send("Patientez SVP")

        async with ctx.typing():
            url = url[0]
            b, mime = await self.bytes_download(url)
            if b is False:
                await ctx.send("**Téléchargement échoué** • Réessayez d'une autre manière")
                return
            await msg.delete()

            gun = bundled_data_path(self) / "GunWM.png"
            filepath = await self.download(url, str(self.temp))

            try:
                task, ext = self.paste_image(filepath, filepath, str(gun), scale=prpt)
            except:
                os.remove(filepath)
                logger.error("Impossible de faire gun_right", exc_info=True)
                return await ctx.send("**Erreur** • Impossible de créer l'image demandée.")

            file = discord.File(task, filename=f"gun_right.{ext}")
            try:
                await ctx.send(file=file)
            except:
                await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image (prob. trop lourde)")
                logger.error(msg="GUN : Impossible d'upload l'image", exc_info=True)
            os.remove(filepath)
