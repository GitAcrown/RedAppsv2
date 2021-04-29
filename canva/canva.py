import asyncio
import logging
import logging
import os
import re
import time
import uuid
from io import BytesIO
from typing import Optional, Union
from urllib.parse import urlsplit

import aiofiles
import aiohttp
import discord
from PIL import Image, ImageSequence, ImageOps
import wand
import wand.color
import wand.drawing
from redbot.core import Config, commands, checks
from redbot.core.data_manager import cog_data_path, bundled_data_path

from .converters import ImageFinder

logger = logging.getLogger("red.RedAppsv2.Canva")

FILES_LINKS = re.compile(
    r"(https?:\/\/[^\"\'\s]*\.(?:png|jpg|jpeg|gif|svg|mp4)(\?size=[0-9]*)?)", flags=re.I
)


class Canva(commands.Cog):
    """Fusion d'images"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)
        
        default_guild = {'canvas': {}}
        
        self.config.register_guild(**default_guild)

        self.temp = cog_data_path(self) / "temp"
        self.temp.mkdir(exist_ok=True, parents=True)
        
        self.image_mimes = ["image/png", "image/pjpeg", "image/jpeg", "image/x-icon"]
        self.gif_mimes = ["image/gif"]
        
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
            logger.error(
                "Impossible de télécharger en bytes-like", exc_info=True)
            return False, False
        
    async def safe_send(self, ctx, text, file, file_size):
        if not ctx.channel.permissions_for(ctx.me).send_messages:
            file.close()
            return
        if not ctx.channel.permissions_for(ctx.me).attach_files:
            await ctx.send("Je n'ai pas les permissions pour envoyer des images.")
            file.close()
            return
        BASE_FILESIZE_LIMIT = 8388608
        if ctx.guild and file_size < ctx.guild.filesize_limit:
            await ctx.send(content=text, file=file)
        elif not ctx.guild and file_size < BASE_FILESIZE_LIMIT:
            await ctx.send(content=text, file=file)
        else:
            await ctx.send("Le contenu est trop lourd pour être envoyé")
        file.close()
    
    @commands.group(name='canva', aliases=['canvas'], invoke_without_command=True)
    @commands.guild_only()
    async def manage_canva(self, ctx, canva_id: str, urls: Optional[ImageFinder] = None, 
                           relative_scale: Optional[int] = 50, align: Optional[str] = None, margin_x: int = 0, margin_y: int = 0, transparency: Union[int, float] = 0):
        """Utilisation et gestion des canvas d'images"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.use_canva, canva_id=canva_id, urls=urls, 
                                    relative_scale=relative_scale, margin_x=margin_x, margin_y=margin_y, transparency=transparency)

    @manage_canva.command(name='use')
    @commands.cooldown(2, 10, commands.BucketType.user)
    @commands.bot_has_permissions(attach_files=True)
    async def use_canva(self, ctx, canva_id: str, urls: Optional[ImageFinder] = None,
                        relative_scale: Optional[int] = 50, align: Optional[str] = None, margin_x: int = 0, margin_y: int = 0, transparency: Union[int, float] = 0):
        """Appliquer un canva pré-enregistré sur l'image
        
        Par défaut utilise la dernière image de l'historique du salon et les paramètres du canva demandé"""
        canvas = await self.config.guild(ctx.guild).canvas()
        if canva_id.lower() not in canvas:
            return await ctx.reply("**Canva inconnu** • Vérifiez le nom du canva et réessayez.")
        
        mark = canvas[canva_id]['url']
        transparency = canvas[canva_id]['transparency'] if transparency == 0 else transparency
        rscale = canvas[canva_id]['rscale'] if relative_scale == 50 else relative_scale
        align = align if align else canvas[canva_id].get('align', 'top_left')
        x, y = margin_x, margin_y
        
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            if x > 100:
                x = 100
            if x < 0:
                x = 0
            if y > 100:
                y = 100
            if y < 0:
                y = 0
            if transparency > 1 and transparency < 100:
                transparency = transparency * 0.01
            if transparency < 0:
                transparency = 0
            if transparency > 100:
                transparency = 1
            if rscale > 100:
                rscale = 100
            if rscale < 1:
                rscale = 1
                
            b, mime = await self.bytes_download(url)
            if mime not in self.image_mimes + self.gif_mimes and not isinstance(
                url, discord.Asset
            ):
                return await ctx.reply("Ce n'est pas une image valide.", mention_author=False)
            
            wmm, mime = await self.bytes_download(mark)
            wm_gif = mime in self.gif_mimes
            if wmm is False or b is False:
                await ctx.send(":warning: **Téléchargement du canva échoué...**")
                return
            wmm.name = "watermark.png"
            if wm_gif:
                wmm.name = "watermark.gif"
                
            rscale = rscale / 100
            
        def align_wm(align: str, image_x, image_y, wm_x, wm_y):
            if align.lower() == 'bottom_left':
                pos = (0, image_y - wm_y)
            elif align.lower() == 'bottom_right':
                pos = (image_x - wm_x, image_y - wm_y)
            elif align.lower() == 'top_right':
                pos = (image_x - wm_x, 0)
            else:
                pos = (0, 0)
            return pos
            
        def apply_canva(b, wmm, x, y, transparency, wm_gif=False):
            final = BytesIO()
            with wand.image.Image(file=b) as img:
                is_gif = len(getattr(img, "sequence")) > 1
                if not is_gif and not wm_gif:
                    logger.debug("Aucun gif")
                    with img.clone() as new_img:
                        new_img.transform(resize="65536@")
                        final_x = int(new_img.height * (x * 0.01))
                        final_y = int(new_img.width * (y * 0.01))
                        with wand.image.Image(file=wmm) as wm:
                            wm.transform(resize=f"{round(new_img.height * rscale)}x{round(new_img.width * rscale)}")
                            pos = align_wm(
                                align, new_img.width, new_img.height, wm.width, wm.height)
                            new_img.watermark(
                                image=wm, left=pos[0], top=pos[1], transparency=transparency
                            )
                        new_img.save(file=final)

                elif is_gif and not wm_gif:
                    logger.debug("L'image de base est un gif")
                         
                    wm = wand.image.Image(file=wmm)
                    with wand.image.Image() as new_image:
                        with img.clone() as new_img:
                            
                            with wand.image.Image(file=wmm) as wm_mod:
                                wm_mod.transform(resize=f"{round(new_img.height / rscale)}x{round(new_img.width / rscale)}")
                                
                            for frame in new_img.sequence:
                                frame.transform(resize="65536@")
                                final_x = int(frame.height * (x * 0.01))
                                final_y = int(frame.width * (y * 0.01))
                                frame.watermark(
                                    image=wm,
                                    left=final_x,
                                    top=final_y,
                                    transparency=transparency,
                                )
                                new_image.sequence.append(frame)
                        new_image.save(file=final)
                else:
                    logger.debug("Le canva est un gif")
                         
                    with wand.image.Image() as new_image:
                        with wand.image.Image(file=wmm) as new_img:
                            
                            with wand.image.Image(file=wmm) as wm_mod:
                                wm_mod.transform(resize=f"{round(new_img.height / rscale)}x{round(new_img.width / rscale)}")
                            
                            for frame in new_img.sequence:
                                with img.clone() as clone:
                                    if is_gif:
                                        clone = clone.sequence[0]
                                    else:
                                        clone = clone.convert("gif")

                                    clone.transform(resize="65536@")
                                    final_x = int(
                                        clone.height * (x * 0.01))
                                    final_y = int(clone.width * (y * 0.01))
                                    clone.watermark(
                                        image=frame,
                                        left=final_x,
                                        top=final_y,
                                        transparency=transparency,
                                    )
                                    new_image.sequence.append(clone)
                                    new_image.dispose = "background"
                                    with new_image.sequence[-1] as new_frame:
                                        new_frame.delay = frame.delay

                        new_image.save(file=final)

            size = final.tell()
            final.seek(0)
            filename = f"{canva_id}.{'gif' if is_gif or wm_gif else 'png'}"

            file = discord.File(final, filename=filename)
            final.close()
            return file, size
        
        try:
            task = ctx.bot.loop.run_in_executor(
                None, apply_canva, b, wmm, x, y, transparency, wm_gif
            )
            file, file_size = await asyncio.wait_for(task, timeout=120)
        except asyncio.TimeoutError:
            return await ctx.reply("L'image a mis trop de temps à être traitée.", mention_author=False)
        await self.safe_send(ctx, None, file, file_size)
        
        
    @manage_canva.command(name='add')
    @commands.bot_has_guild_permissions(manage_messages=True)
    async def add_canva(self, ctx, canva_id: str, url: Optional[ImageFinder] = None,
                        relative_scale: Optional[int] = 50, align: str = 'top_left', transparency: Union[int, float] = 0):
        """Ajouter un canva pour l'appliquer sur des images
        
        `url` = Eventuelle URL de l'image (si elle n'a pas été uploadée)
        
        __Paramètres initiaux__
        `relative_scale` = Echelle relative du canva par rapport à la taille de l'image support
        `align` = Alignement du canva par rapport à l'image support (top_left, top_right, bottom_left, bottom_right)
        `transparency` = Pourcentage de transparence du canva (0-100%)"""
        if url is None:
            url = await ImageFinder().search_for_images(ctx)
            
        canva_id = canva_id.lower()
            
        canvas = await self.config.guild(ctx.guild).canvas()
        if canva_id in canvas:
            return await ctx.send(f"Un canva du nom de `{canva_id}` existe déjà sur ce serveur.\nUtilisez un autre nom ou supprimez l'actuel avec `;canva del {canva_id}`.")
        
        async with ctx.typing():
            url = url[0]
            # filename = urlsplit(url).path.rsplit('/')[-1]
            # filepath = str(self.temp / filename)
            # try:
            #     await self.download(url, filepath)
            # except:
            #     return await ctx.send("**Téléchargement échoué** • Donnez une URL valide ou uploadez-là directement dans Discord.")
            # else:
            new_canva = {'url': url, 'rscale': relative_scale, 'align': 'top_left', 'transparency': transparency}
            await self.config.guild(ctx.guild).canvas.set_raw(canva_id, value=new_canva)
        await ctx.send(f"**Canva ajouté** • Vous pouvez désormais l'utiliser avec `;canva {canva_id}`.")

    @manage_canva.command(name='del', aliases=['delete'])
    @commands.bot_has_guild_permissions(manage_messages=True)
    async def del_canva(self, ctx, canva_id: str):
        """Supprimer un canva"""
        canva_id = canva_id.lower()
            
        canvas = await self.config.guild(ctx.guild).canvas()
        if canva_id not in canvas:
            return await ctx.send(f"Aucun canva du nom de `{canva_id}` n'existe sur ce serveur.")
        
        await self.config.guild(ctx.guild).canvas.clear_raw(canva_id)
        await ctx.send(f"**Canva supprimé** • Le canva `{canva_id}` a été supprimé avec succès.")
    
    
