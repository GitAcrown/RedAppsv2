import asyncio
import logging
import os
import random
import re
import string
import time
from copy import copy
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import aiofiles
import aiohttp
import discord
from discord.errors import HTTPException
from typing import Union, List, Tuple, Literal, Optional
from PIL import Image, ImageSequence
from bs4 import BeautifulSoup

from discord.ext import tasks
from redbot.core import Config, commands, checks
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils import AsyncIter
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box, humanize_number
from tabulate import tabulate

logger = logging.getLogger("red.RedAppsv2.imgedit")

FILES_LINKS = re.compile(
    r"(https?:\/\/[^\"\'\s]*\.(?:png|jpg|jpeg|gif|svg|mp4)(\?size=[0-9]*)?)", flags=re.I
)


class ImgEditError(Exception):
    """Classe de base pour les erreurs ImgEdit"""



class ImgEdit(commands.Cog):
    """Commandes d'édition d'images"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        self.temp = cog_data_path(self) / "temp"
        self.temp.mkdir(exist_ok=True, parents=True)

    async def search_for_files(self, ctx, nb: int = 1):
        urls = []
        async for message in ctx.channel.history(limit=10):
            if message.author == ctx.author or ctx.author.permissions_in(ctx.channel).manage_messages:
                if message.attachments:
                    for attachment in message.attachments:
                        urls.append([attachment.url, message])
                    break
                match = FILES_LINKS.match(message.content)
                if match:
                    urls.append((match.group(1), message))
        if urls:
            return urls[:nb]
        return []

    async def download(self, url: str, *, force_png: bool = False):
        seed = str(int(time.time()))
        file_name, ext = os.path.splitext(os.path.basename(urlsplit(url).path))
        if not force_png:
            filename = "{}_{}{}".format(seed, file_name, ext)
        else:
            filename = "{}_{}.png".format(seed, file_name)
        filepath = "{}/{}".format(str(self.temp), filename)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        f = await aiofiles.open(str(filepath), mode='wb')
                        await f.write(await resp.read())
                        await f.close()
                    else:
                        raise ConnectionError()
            return filepath
        except Exception:
            logger.error("Error downloading", exc_info=True)
            return False

    def get_avg_fps(self, PIL_Image_object):
        PIL_Image_object.seek(0)
        frames = duration = 0
        while True:
            try:
                frames += 1
                duration += PIL_Image_object.info['duration']
                PIL_Image_object.seek(PIL_Image_object.tell() + 1)
            except EOFError:
                return frames / duration * 1000

    def add_gun(self, input_image_path, output_image_path, watermark_image_path, position, proportion):
        watermark = Image.open(watermark_image_path).convert('RGBA')
        try:
            base_image = Image.open(input_image_path).convert('RGBA')
        except:
            base_image = Image.open(input_image_path).convert('RGB')
        width, height = base_image.size
        watermark.thumbnail((round(width / proportion), round(height / proportion)))
        position = (width - watermark.size[0] - position[0], height - watermark.size[1] - position[1])

        if input_image_path.endswith('gif') or input_image_path.endswith('gifv'):
            base_image = Image.open(input_image_path)
            dur = self.get_avg_fps(base_image)
            frames = []
            for frame in ImageSequence.Iterator(base_image):
                transparent = Image.new('RGBA', (width, height), (0, 0, 0, 0))
                transparent.paste(frame, (0, 0))
                transparent.paste(watermark, position, mask=watermark)
                frames.append(transparent)
            frames[0].save(output_image_path, format='GIF', append_images=frames[1:], save_all=True, optimize=False,
                           loop=0, duration=dur)
            return output_image_path
        else:
            transparent = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            transparent.paste(base_image, (0, 0))
            transparent.paste(watermark, position, mask=watermark)
            transparent.save(output_image_path)
            return output_image_path

    @commands.command()
    async def gun(self, ctx, size: Optional[float] = 2.0, *, url: str = None):
        """Ajoute un pistolet braqué sur l'image

        [url] = URL de l'image sur laquelle appliquer le filtre (optionnel)
        [size] = Proportion du pistolet, plus le chiffre est élevé plus il sera petit (1 = à la proportion de l'image fournie)"""
        if size <= 0:
            return await ctx.send("**Proportion invalide** • La valeur de proportion doit être supérieure à 0.")

        if not url:
            url = await self.search_for_files(ctx)
            if not url:
                return await ctx.send("**???** • Fournissez un fichier valide")
            else:
                url = url[0]
        elif url.startswith('http'):
            url = [url, ctx.message]
        else:
            return await ctx.send("**???** • Fournissez un fichier valide")
        async with ctx.channel.typing():
            gun = bundled_data_path(self) / "GunWM.png"
            if url[0].endswith('.gif') or url[0].endswith('.gifv'):
                filepath = await self.download(url[0])
            else:
                filepath = await self.download(url[0], force_png=True)

            result = self.add_gun(filepath, filepath, gun, (0, 0), size)
            file = discord.File(result)
            try:
                await ctx.send(file=file)
            except:
                await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image (prob. trop lourde)")
            os.remove(result)
        return