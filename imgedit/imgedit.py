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
from PIL import Image
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

    async def download(self, url: str):
        seed = str(int(time.time()))
        file_name, ext = os.path.splitext(os.path.basename(urlsplit(url).path))
        filename = "{}_{}{}".format(seed, file_name, ext)
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

    def add_gun(self, input_image_path, output_image_path, watermark_image_path, position, proportion):
        try:
            base_image = Image.open(input_image_path).convert('RGBA')
        except:
            base_image = Image.open(input_image_path).convert('RGB')
        watermark = Image.open(watermark_image_path).convert('RGBA')
        width, height = base_image.size
        watermark.thumbnail((round(width / proportion), round(height / proportion)))
        transparent = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        transparent.paste(base_image, (0, 0))
        position = (width - watermark.size[0] - position[0], height - watermark.size[1] - position[1])
        transparent.paste(watermark, position, mask=watermark)
        transparent.show()
        transparent.save(output_image_path)
        return output_image_path

    @commands.command()
    async def gun(self, ctx, url: Optional[str] = None, *, size: float = 2.0):
        """Ajoute un pistolet braqué sur l'image

        [url] = URL de l'image sur laquelle appliquer le filtre (optionnel)
        [size] = Proportion du pistolet, plus le chiffre est élevé plus il sera petit"""
        if not url:
            url = await self.search_for_files(ctx)
            if not url:
                return await ctx.send("**???** • Fournissez un fichier valide")
            else:
                url = url[0]
        else:
            url = [url, ctx.message]
        async with ctx.channel.typing():
            gun = bundled_data_path(self) / "GunWM.png"
            filepath = await self.download(url[0])
            result = self.add_gun(filepath, filepath, gun, (0, 0), size)
            file = discord.File(result)
            try:
                await ctx.send(file=file)
            except:
                await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image (prob. trop lourde)")
            os.remove(result)
        return