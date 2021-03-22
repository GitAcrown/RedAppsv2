# Merci à Maglatranir#7175 d'avoir donné l'idée originelle du module

import asyncio
import os
from copy import copy
import logging
import random
from typing import List, Optional
from urllib.parse import urlsplit

import aiohttp
import webcolors
import extcolors

import discord
from PIL import Image, ImageDraw, ImageFont
from discord.utils import get as discord_get
from redbot.core import Config, commands, checks
from redbot.core.data_manager import cog_data_path, bundled_data_path
from .converters import ImageFinder


logger = logging.getLogger("red.RedAppsv2.HexColor")


class HexColorError(Exception):
    """Classe de base des erreurs HexColor"""


class ColorExtractError(HexColorError):
    """Soulevée lorsqu'il y a eu une erreur dans l'extraction des couleurs d'une image"""


class HexColor(commands.Cog):
    """Gestion automatisée des rôles colorés personnalisés"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'roles': {},
                         'delimiter': None,
                         'whitelist': []}
        default_global = {'extcolors_limit': 3,
                          'extcolors_tolerance': 30}
        default_user = {'colors': {}}
        self.config.register_guild(**default_guild)
        self.config.register_global(**default_global)
        self.config.register_user(**default_user)

        self.temp = cog_data_path(self) / "temp"  # Pour stocker l'img de profil temporairement
        self.temp.mkdir(exist_ok=True, parents=True)

        self.FONT = str(bundled_data_path(self) / "Pixellari.ttf")

    async def create_guild_color(self, guild: discord.Guild, color: str) -> discord.Role:
        """Crée un rôle avec la couleur demandée et le range si le délimiteur est configuré

        Retourne le rôle créé (ou trouvé si déjà présent)"""
        await self.bot.wait_until_ready()
        rolename = self.format_color(color, "#")
        role = discord_get(guild.roles, name=rolename)
        if not role:
            rolecolor = int(self.format_color(color, '0x'), base=16)
            await self.add_color_to_cache(guild, color)
            role = await guild.create_role(name=rolename, color=discord.Colour(rolecolor),
                                           reason="Création de rôle de couleur", mentionable=False)
            await self.sort_role(guild, role)
        return role

    async def replace_guild_color(self, target_role: discord.Role, color: str) -> discord.Role:
        """Recycle un ancien rôle coloré en lui attribuant une nouvelle couleur

        Retourne le rôle modifié"""
        await self.remove_color_from_cache(target_role.guild, str(target_role.color))
        rolename = self.format_color(color, "#")
        new_color = int(self.format_color(color, '0x'), base=16)
        await target_role.edit(name=rolename, color=new_color, reason="Recyclage du rôle coloré")
        await self.add_color_to_cache(target_role.guild, color)
        return target_role

    async def safe_clear_guild_color(self, guild: discord.Guild, color: str) -> bool:
        """Vérifie que des membres ne possèdent plus la couleur et supprime le rôle coloré"""
        name = self.format_color(color, "#")
        role = discord_get(guild.roles, name=name)
        if role:
            if not self.get_members_with(role):
                await role.delete(reason="Suppression de rôle de couleur obsolète")
                await self.remove_color_from_cache(guild, color)
                return True
        return False

    async def safe_bulk_clear_guild_colors(self, guild: discord.Guild, colors: list) -> list:
        """Vérifie que des membres ne possèdent pas les couleurs données et supprime les rôles obsolètes

        Retourne une liste des noms des rôles supprimés"""
        await self.bot.wait_until_ready()
        names = [self.format_color(c, '#') for c in colors]
        logs = []
        for name in names:
            role = discord_get(guild.roles, name=name)
            if role:
                if not self.get_members_with(role):
                    await role.delete(reason="Suppression de rôle de couleur obsolète")
                    await self.remove_color_from_cache(guild, name)
                    logs.append(name)
        return logs

    async def sort_role(self, guild: discord.Guild, role: discord.Role):
        """Range le rôle sous le délimiteur"""
        deid = await self.config.guild(guild).delimiter()
        if deid and role in guild.roles:
            delim = guild.get_role(deid)
            changes = {
                delim: delim.position,
                role: delim.position - 1,
            }
            return await guild.edit_role_positions(positions=changes)
        return None

    async def is_color_displayed(self, user: discord.Member, role: discord.Role = None):
        """Indique si la couleur du rôle est celle qui s'affiche sur le pseudo du membre"""
        all_colors = await self.config.guild(user.guild).roles()
        if not role:
            colors = [r for r in user.roles if r.name in all_colors]
            role = colors[0] if colors else None
        if role:
            return user.color == role.color
        return False

    def get_members_with(self, role: discord.Role) -> List[discord.Member]:
        """Renvoie les membres possédant le rôle demandé"""
        guild = role.guild
        members = []
        for member in guild.members:
            if role in member.roles:
                members.append(member)
        return members

    async def add_color_to_cache(self, guild: discord.Guild, hex_color: str):
        name = self.format_color(hex_color, "#")
        rolecolor = self.format_color(hex_color, "0x")
        await self.config.guild(guild).roles.set_raw(name, value=rolecolor)

    async def remove_color_from_cache(self, guild: discord.Guild, hex_color: str):
        name = self.format_color(hex_color, "#")
        try:
            await self.config.guild(guild).roles.clear_raw(name)
        except:
            logger.info(f"Impossible de supprimer {name} du cache de {guild.id}",
                        exc_info=True)

    async def extract_colors(self, image_path: str, tolerance: int = None, limit: int = None) -> list:
        """Extrait les X couleurs les plus dominantes de l'image

        Renvoie une liste des couleurs (en hexidécimal) extraites avec le pourcentage arrondi qu'ils représentent sur l'image"""
        tolerance = tolerance if tolerance else await self.config.extcolors_tolerance()
        limit = limit if limit else await self.config.extcolors_limit()

        try:
            colors, pixel_count = extcolors.extract_from_path(image_path, tolerance,
                                                              limit=limit)
        except:
            raise ColorExtractError("Erreur dans l'extraction des couleurs de l'image")
        else:
            colors = [(f"#{''.join(f'{hex(c)[2:].upper():0>2}' for c in clr)}", round(pixnb / pixel_count * 100, 2)) for
                      clr, pixnb in (k for k in colors)]
            return colors

    async def set_member_color(self, user: discord.Member, color: str) -> discord.Role:
        """Applique la couleur demandée au membre en supprimant les anciens qu'il pourrait posséder

        Renvoie le rôle désormais possédé"""
        await self.bot.wait_until_ready()
        guild = user.guild
        all_colors = await self.config.guild(guild).roles()
        rolename = self.format_color(color, '#')
        user_colored_roles = [r for r in user.roles if r.name in all_colors]
        if rolename not in (r.name for r in user.roles):
            del_roles = user_colored_roles
            role = None
            for r in user_colored_roles:
                if self.get_members_with(r) == [user]:
                    role = await self.replace_guild_color(r, color)
                    del_roles.remove(r)
                    break
            if del_roles:
                await user.remove_roles(*del_roles)
                await self.safe_bulk_clear_guild_colors(guild, [r.name for r in del_roles])

            if not role:
                role = await self.create_guild_color(guild, color)
                await user.add_roles(role, reason="Attribution d'un rôle coloré")
            return role
        return discord_get(guild.roles, name=self.format_color(color, "#"))

    async def user_in_whitelist(self, user: discord.Member):
        """Vérifie les permissions s'il y a une whitelist active"""
        guild = user.guild
        whitelist = await self.config.guild(guild).whitelist()
        if whitelist:
            verif = [r.id for r in user.roles]
            verif.append(user.id)
            if not [i for i in verif if i in whitelist] and not user.guild_permissions.manage_roles:
                return False
        return True

    def format_color(self, color: str, prefixe: str = None):
        """Vérifie que la couleur donnée est un hexadécimal et renvoie la couleur avec ou sans préfixe (0x ou #)"""
        if len(color) >= 6:
            color = color[-6:]
            try:
                int(color, base=16)
                return color.upper() if not prefixe else prefixe + color.upper()
            except ValueError:
                return False
        return False

    def css_name_hex(self, name: str):
        """Retrouve l'hex lié au nom de couleur (CSS3/HTML)"""
        try:
            hex = webcolors.name_to_hex(name)
            return self.format_color(hex, "0x")
        except:
            return False

    def color_representation(self, color: str, custom_text: str = None):
        color = self.format_color(color)
        text = color if not custom_text else custom_text
        return f"https://dummyimage.com/100x100/{color}.png&text=+{text}"

    async def get_prefix(self, message: discord.Message) -> str:
        content = message.content
        prefix_list = await self.bot.command_prefix(self.bot, message)
        prefixes = sorted(prefix_list, key=lambda pfx: len(pfx), reverse=True)
        for p in prefixes:
            if content.startswith(p):
                return p
        return "n."

    def show_palette(self, colors, outfile, *, swatchsize=200):
        num_colors = len(colors)
        palette = Image.new('RGB', (swatchsize * num_colors, swatchsize))
        draw = ImageDraw.Draw(palette)
        myFont = ImageFont.truetype(self.FONT, 20)

        posx = 0
        for color in colors:
            draw.rectangle([posx, 0, posx + swatchsize, swatchsize], fill=color)
            w, h = draw.textsize(str(color), font=myFont)
            draw.rectangle([posx + (swatchsize / 2) - w / 1.75, (swatchsize / 2) - h / 1.75, posx + (swatchsize / 2) + w / 1.75,
                            (swatchsize / 2) + h / 1.75], fill="black")
            draw.text((posx + (swatchsize / 2) - w / 2, (swatchsize / 2) - h / 2), str(color), fill="white", font=myFont)
            posx = posx + swatchsize

        del draw
        palette.save(outfile, "PNG")

    def repr_colors_inventory(self, colors_map: dict, outfile: str):
        swatchsize = 100
        colors = [c for c in colors_map]
        num_colors = len(colors)
        palette = Image.new('RGB', (swatchsize * num_colors, swatchsize))
        draw = ImageDraw.Draw(palette)
        myFont = ImageFont.truetype(self.FONT, 16)

        posx = 0
        for color in colors:
            draw.rectangle([posx, 0, posx + swatchsize, swatchsize], fill=color)
            w, h = draw.textsize(colors_map[color], font=myFont)
            draw.rectangle([posx + (swatchsize / 2) - w / 1.75, (swatchsize / 2) - h / 1.75, posx + (swatchsize / 2) + w / 1.75,
                            (swatchsize / 2) + h / 1.75], fill="white")
            draw.text((posx + (swatchsize / 2) - w / 2, (swatchsize / 2) - h / 2), colors_map[color], fill="black", font=myFont)
            posx = posx + swatchsize

        del draw
        palette.save(outfile, "PNG")

    @commands.group(name='colorme', aliases=['color'], invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.member)
    @commands.bot_has_guild_permissions(manage_roles=True, mention_everyone=True)
    async def set_user_color(self, ctx, couleur: str):
        """Gestion de votre rôle de couleur

        `colorme custom` : Changer la couleur selon un code hexadécimal (ex. *#fefefe*) ou un nom CSS3/HTML (ex. *lightgray*)
        `colorme avatar` : Applique la couleur dominante de votre avatar
        `colorme random` : Applique une couleur aléatoire
        `colorme copy` : Copie la couleur d'un autre membre
        --------
        `colorme save` : Sauvegarde une couleur sous un nom donné
        `colorme load` : Charger une couleur sauvegardée
        `colorme forget` : Retirer une couleur sauvegardée
        `colorme inv` : Affiche une représentation de votre inventaire de couleurs (commun sur tous vos serveurs)
        --------
        `colorme remove` : Retirer tous les rôles colorés que vous possédez (ceux attribués par le bot seulement)

        -> Utilisez `;help` devant ces options pour obtenir plus d'infos"""
        if ctx.invoked_subcommand is None:
            return await ctx.invoke(self.custom_color, color=couleur)

    @set_user_color.command(name="custom")
    async def custom_color(self, ctx, color: str):
        """Changer la couleur selon un code hexadécimal ou un nom CSS3/HTML"""
        user = ctx.author
        if not self.user_in_whitelist(user):
            return await ctx.reply(
                "**Interdit** • Vous ne figurez pas sur la whitelist des gens autorisés à utiliser cette commande.")

        async with ctx.channel.typing():
            if self.format_color(color):
                couleur = self.format_color(color, "0x")
            elif self.css_name_hex(color):
                couleur = self.css_name_hex(color)
            else:
                return await ctx.reply("**Couleur invalide** • La couleur donnée n'est ni une couleur en "
                                      "hexadécimal (ex. `#fefefe`) ni un nom de couleur CSS3/HTML (ex. *lightgray*)")
            role = await self.set_member_color(ctx.author, couleur)
            em = discord.Embed(description=f"Vous avez désormais la couleur **{role.name}**", color=role.color)
            if not await self.is_color_displayed(ctx.author, role):
                em.set_footer(
                    text="⚠️ Attention, la couleur demandée ne pourra s'afficher qu'après avoir retiré le rôle coloré hiérarchiquement supérieur !")
            await ctx.reply(embed=em, mention_author=False)

    @set_user_color.command(name="avatar", aliases=['auto'])
    async def avatar_color(self, ctx):
        """Applique la couleur dominante de votre avatar"""
        user = ctx.author
        if not self.user_in_whitelist(user):
            return await ctx.reply(
                "**Interdit** • Vous ne figurez pas sur la whitelist des gens autorisés à utiliser cette commande.")

        notif = await ctx.send("⏳ Veuillez patienter pendant l'extraction de la couleur dominante de votre avatar...")
        async with ctx.channel.typing():
            member = ctx.author
            path = str(self.temp)
            filename = path + "/avatar_{}.jpg".format(member.id)
            await member.avatar_url.save(filename)
            avatar_color = await self.extract_colors(filename, limit=1)
            await notif.delete()

            role = await self.set_member_color(user, avatar_color[0][0])
            em = discord.Embed(description=f"Vous avez désormais la couleur **{role.name}**", color=role.color)
            if not await self.is_color_displayed(ctx.author, role):
                em.set_footer(
                    text="⚠️ Attention, la couleur demandée ne pourra s'afficher qu'après avoir retiré le rôle coloré hiérarchiquement supérieur !")
            await ctx.reply(embed=em, mention_author=False)
        os.remove(filename)

    @set_user_color.command(name="random")
    async def random_color(self, ctx):
        """Applique une couleur aléatoire"""
        user = ctx.author
        if not self.user_in_whitelist(user):
            return await ctx.reply(
                "**Interdit** • Vous ne figurez pas sur la whitelist des gens autorisés à utiliser cette commande.")

        async with ctx.channel.typing():
            r = lambda: random.randint(0, 255)
            couleur = '%02X%02X%02X' % (r(), r(), r())
            role = await self.set_member_color(ctx.author, couleur)
            em = discord.Embed(description=f"Vous avez désormais la couleur **{role.name}**", color=role.color)
            if not await self.is_color_displayed(ctx.author, role):
                em.set_footer(
                    text="⚠️ Attention, la couleur demandée ne pourra s'afficher qu'après avoir retiré le rôle coloré hiérarchiquement supérieur !")
            await ctx.reply(embed=em, mention_author=False)

    @set_user_color.command(name="copy")
    async def copy_color(self, ctx, target: discord.Member):
        """Applique la même couleur que le membre visé"""
        user = ctx.author
        if not self.user_in_whitelist(user):
            return await ctx.reply(
                "**Interdit** • Vous ne figurez pas sur la whitelist des gens autorisés à utiliser cette commande.")

        async with ctx.channel.typing():
            couleur = self.format_color(str(target.color), '#')
            role = await self.set_member_color(ctx.author, couleur)
            em = discord.Embed(description=f"Vous avez désormais la couleur **{role.name}** (copiée sur {target.mention})",
                               color=role.color)
            if not await self.is_color_displayed(ctx.author, role):
                em.set_footer(
                    text="⚠️ Attention, la couleur demandée ne pourra s'afficher qu'après avoir retiré le rôle coloré hiérarchiquement supérieur !")
            await ctx.reply(embed=em, mention_author=False)

    @set_user_color.command(name="save")
    async def save_custom_color(self, ctx, name: str, color: str = None):
        """Sauvegarde une couleur sous un nom personnalisé

        Si aucune couleur (en hex.) n'est donnée, sauvegarde votre couleur actuelle

        __Commande globale__ : l'inventaire est commun à tous les serveurs"""
        user = ctx.author
        inv = copy(await self.config.user(user).colors())
        if name not in inv:

            if len(inv) == 10:
                return  await ctx.send("**Inventaire plein** • Vous avez déjà atteint le nombre maximal de couleurs enregistrées (10).\n"
                                       "Effacez-en quelques unes avec `colorme forget` !")

            color = color if color else str(user.color)
            if self.format_color(color):
                color = self.format_color(color, "#")
                inv[name] = color
                await self.config.user(user).colors.set(inv)

                em = discord.Embed(description=f"La couleur {color} a été ajoutée à votre inventaire sous le nom de ***{name}***",
                                   color=discord.Colour(int(self.format_color(color, '0x'), base=16)))
                await ctx.reply(embed=em, mention_author=False)
            else:
                await ctx.send("**Couleur invalide** • Entrez un code couleur hexadécimale pour l'enregistrer, "
                               "ou ne mettez rien pour sauvegarder votre couleur de pseudo actuelle.")
        else:
            await ctx.send("**Nom invalide** • Vous avez déjà une couleur sauvegardée sous ce nom.")

    @set_user_color.command(name="load")
    async def load_custom_color(self, ctx, name: str):
        """Charge une couleur sauvegardée et vous l'applique"""
        user = ctx.author
        if not self.user_in_whitelist(user):
            return await ctx.reply(
                "**Interdit** • Vous ne figurez pas sur la whitelist des gens autorisés à utiliser cette commande.")

        inv = await self.config.user(user).colors()
        async with ctx.channel.typing():
            if name in inv:
                couleur = inv[name]
                role = await self.set_member_color(ctx.author, couleur)
                em = discord.Embed(description=f"Vous avez désormais la couleur **{role.name}**", color=role.color)
                if not await self.is_color_displayed(ctx.author, role):
                    em.set_footer(
                        text="⚠️ Attention, la couleur demandée ne pourra s'afficher qu'après avoir retiré le rôle coloré hiérarchiquement supérieur !")
                await ctx.reply(embed=em, mention_author=False)
            else:
                await ctx.send("**Nom introuvable** • Aucune couleur avec ce nom n'existe dans votre inventaire.\n"
                               "Vérifiez l'orthographe, les noms sont sensibles à la casse.")

    @set_user_color.command(name="forget")
    async def forget_custom_color(self, ctx, name: str):
        """Retire une couleur sauvegardée de votre inventaire

        Ne vous retire pas le rôle avec la couleur supprimée

        __Commande globale__ : l'inventaire est commun à tous les serveurs"""
        user = ctx.author
        inv = copy(await self.config.user(user).colors())
        if name in inv:
            del inv[name]
            await self.config.user(user).colors.set(inv)
            await ctx.reply(f"**Couleur supprimée** • *{name}* ne figurera plus dans votre inventaire",
                            mention_author=False)
        else:
            await ctx.send("**Nom invalide** • Vous n'avez pas de couleur sauvegardée sous ce nom.")

    @set_user_color.command(name="inventory", aliases=['inv'])
    async def inventory_custom_color(self, ctx):
        """Affiche une représentation des couleurs de votre inventaire"""
        user = ctx.author
        notif = await ctx.send("⏳ Veuillez patienter pendant la génération d'une représentation des couleurs de votre inventaire...")
        async with ctx.channel.typing():
            inv = await self.config.user(user).colors()
            path = str(self.temp)
            filename = path + "/colorinventory_{}.png".format(user.id)
            self.repr_colors_inventory({inv[c]: c for c in inv}, filename)

            await notif.delete()
            file = discord.File(filename)
            try:
                await ctx.reply("**Voici votre inventaire :**", file=file, mention_author=False)
            except:
                await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image de l'inventaire, désolé.")
                logger.error(msg="Inventory_custom_color : Impossible d'upload l'image représentative de l'inventaire",
                             exc_info=True)
            os.remove(filename)

    @set_user_color.command(name="remove")
    async def remove_color(self, ctx):
        """Retire toutes les rôles colorés que vous possédez (attribués par le bot)"""
        user = ctx.author
        async with ctx.channel.typing():
            all_colors = await self.config.guild(ctx.guild).roles()
            user_colors = [r for r in user.roles if r.name in all_colors]

            if user_colors:
                await user.remove_roles(*user_colors, reason="Retrait du/des rôle(s) sur demande du membre")
                await ctx.send("**Couleur(s) retirée(s)** • Vous n'avez plus aucun rôle coloré provenant du bot")
                await asyncio.sleep(3)  # Eviter les limitations Discord
                await self.safe_bulk_clear_guild_colors(ctx.guild, [i.name for i in user_colors])
            else:
                await ctx.send("**Aucun rôle** • Aucun rôle coloré que vous possédez ne provient de ce bot")


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

    @commands.command(name="palette")
    async def get_image_palette(self, ctx, nb: Optional[int] = 5, url: ImageFinder = None):
        """Extrait une palette de X couleurs de l'image donnée"""
        if nb < 1 or nb > 10:
            return await ctx.send("**Impossible** • Vous ne pouvez générer qu'entre 1 et 10 couleurs")
        if url is None:
            url = await ImageFinder().search_for_images(ctx)
        msg = await ctx.message.channel.send("⏳ Veuillez patienter durant la génération de votre palette de couleurs (peut être long pour les grosses images)")
        async with ctx.typing():
            url = url[0]
            filename = urlsplit(url).path.rsplit('/')[-1]
            filepath = str(self.temp / filename)
            palette_path = str(self.temp) + "/palette_{}.png".format(filename.split('.')[0])
            try:
                await self.download(url, filepath)
            except:
                await ctx.send("**Téléchargement échoué** • Réessayez d'une autre façon")

            colors = await self.extract_colors(filepath, limit=nb)
            self.show_palette([i[0] for i in colors], palette_path)
            await msg.delete()
            file = discord.File(palette_path)
            try:
                await ctx.reply(file=file, mention_author=False)
            except:
                await ctx.send("**Impossible** • Je n'ai pas réussi à upload l'image de la palette.")
                logger.error(msg="palette : Impossible d'upload l'image palette",
                             exc_info=True)
            os.remove(filepath)
            os.remove(palette_path)


    @commands.group(name="colorset")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def _color_settings(self, ctx):
        """Paramètres de HexColor concernant les rôles colorés"""

    @_color_settings.command()
    async def delim(self, ctx, role: discord.Role = None):
        """Attribue le rôle de délimiteur à un rôle pour ranger auto. les rôles créés

        Les rôles créés seront automatiquement rangés sous le rôle délimiteur si celui-ci est défini
        Si le rôle donné est le même que celui enregistré précédemment, met à jour le positionnement des rôles"""
        guild = ctx.guild
        if role:
            if role.id != await self.config.guild(guild).delimiter():
                await self.config.guild(guild).delimiter.set(role.id)
                await ctx.send(
                        f"**Rôle délimiteur modifié** • Les rôles colorés se rangeront auto. sous ***{role.name}*** "
                        f"dans la liste de rôles lors de leur création")

            delimpos = role.position
            all_roles = await self.config.guild(guild).roles()
            for r in all_roles:
                check = discord_get(guild.roles, name=r)
                if check:
                    setpos = delimpos - 1 if delimpos > 1 else 1
                    await check.edit(position=setpos)
            await ctx.send(
                f"**Rôles rangés** • Les rôles ont été rangés conformément aux paramètres")

        else:
            await self.config.guild(guild).delimiter.set(None)
            await ctx.send(
                f"**Rôle délimiteur retiré** • Les rôles colorés ne se rangeront plus automatiquement (déconseillé)")

    @_color_settings.command(name="clear")
    async def clear_colors(self, ctx):
        """Lance manuellement une vérification et suppression des rôles de couleurs qui ne sont plus utilisés par personne"""
        guild = ctx.guild
        all_roles = await self.config.guild(guild).roles()
        roles = await self.safe_bulk_clear_guild_colors(guild, [r for r in all_roles])
        await ctx.send(f"**Vérification terminée** • {len(roles)} rôles obsolètes ont été supprimés")

    @_color_settings.command(name="deleteall")
    async def deleteall_colors(self, ctx):
        """Supprime tous les rôles colorés créés par le bot"""
        guild = ctx.guild
        aut = str(ctx.author)
        all_roles = await self.config.guild(guild).roles()
        count = 0
        for r in all_roles:
            role = discord_get(guild.roles, name=r)
            if role:
                await role.delete(reason=f"Suppression du rôle sur demande de {aut}")
                count += 1
        await self.config.guild(guild).clear_raw("roles")
        await ctx.send(f"**Suppression réalisée** • {count} rôles ont été supprimés")

    @_color_settings.command(name="give")
    async def give_color(self, ctx, user: discord.Member, couleur: str):
        """Donne la couleur voulue au membre, même si celui-ci n'est pas autorisé à le faire lui-même"""
        if self.format_color(couleur):
            couleur = self.format_color(couleur, "#")
            role = await self.set_member_color(user, couleur)
            if role:
                em = discord.Embed(description=f"{ctx.author.mention} a donné la couleur **{role.name}** à {user.mention}",
                                   color=role.color)
                em.set_author(name=str(ctx.author), icon_url=ctx.author.avatar_url)
                await ctx.send(embed=em)
            else:
                await ctx.send("**Erreur** • Impossible de lui donner cette couleur")

    @_color_settings.command(name="refresh")
    async def refresh_colors(self, ctx):
        """Rafraichit le cache des rôles manuellement si celui-ci est corrompu ou incomplet"""
        guild = ctx.guild
        count = 0
        await self.config.guild(guild).clear_raw("roles")
        for role in guild.roles:
            if role.name.startswith("#") and self.format_color(role.name):
                await self.add_color_to_cache(guild, role.name)
                count += 1
        await ctx.send(f"**Rafrachissement terminé** • {count} rôles ont été rajoutés au cache et sont maintenant considérés par le bot")


    @_color_settings.group(name="whitelist")
    async def _color_whitelist(self, ctx):
        """Gestion de la whitelist pour utiliser les commandes de rôles colorés"""

    @_color_whitelist.command(name="adduser")
    async def color_whitelist_adduser(self, ctx, user: discord.Member):
        """Ajouter un membre à la whitelist"""
        guild = ctx.guild
        liste = await self.config.guild(guild).whitelist()
        if user.id not in liste:
            liste.append(user.id)
            await self.config.guild(guild).whitelist.set(liste)
            await ctx.send(
                f"**Membre ajouté** • **{user.name}** pourra utiliser les commandes de rôles colorés.")
        else:
            await ctx.send(
                f"**Membre déjà présent** • Ce membre est déjà dans la whitelist, utilisez `;colorset whitelist deluser` pour le retirer.")

    @_color_whitelist.command(name="deluser")
    async def color_whitelist_deluser(self, ctx, user: discord.Member):
        """Retirer un membre de la whitelist"""
        guild = ctx.guild
        liste = await self.config.guild(guild).whitelist()
        if user.id in liste:
            liste.remove(user.id)
            await self.config.guild(guild).whitelist.set(liste)
            await ctx.send(
                f"**Membre retiré** • **{user.name}** ne pourra plus utiliser les commandes de rôles colorés.")
        else:
            await ctx.send(
                f"**Membre absent** • Ce membre n'est pas dans la whitelist, utilisez `;colorset whitelist adduser` pour l'ajouter.")

    @_color_whitelist.command(name="addrole")
    async def color_whitelist_addrole(self, ctx, role: discord.Role):
        """Ajouter un rôle à la whitelist

        Tous les membres possédant ce rôle pourront utiliser les commandes"""
        guild = ctx.guild
        liste = await self.config.guild(guild).whitelist()
        if role.id not in liste:
            liste.append(role.id)
            await self.config.guild(guild).whitelist.set(liste)
            await ctx.send(
                f"**Rôle ajouté** • Les membres possédant **{role.name}** pourront utiliser les commandes de rôles colorés.")
        else:
            await ctx.send(
                f"**Rôle déjà présent** • Ce rôle est déjà whitelisté, utilisez `;colorset whitelist delrole` pour le retirer.")

    @_color_whitelist.command(name="delrole")
    async def color_whitelist_delrole(self, ctx, role: discord.Role):
        """Retirer un rôle de la whitelist"""
        guild = ctx.guild
        liste = await self.config.guild(guild).whitelist()
        if role.id in liste:
            liste.remove(role.id)
            await self.config.guild(guild).whitelist.set(liste)
            await ctx.send(
                f"**Rôle retiré** • Les membres possédant **{role.name}** ne pourront pas utiliser les commandes de rôles colorés.")
        else:
            await ctx.send(
                f"**Rôle absent** • Ce rôle n'est pas whitelisté, utilisez `;colorset whitelist addrole` pour l'ajouter.")

    @_color_whitelist.command(name="clear")
    async def color_whitelist_clear(self, ctx):
        """Efface toute la whitelist (membres et rôles)"""
        guild = ctx.guild
        await self.config.guild(guild).clear_raw("whitelist")
        await ctx.send(
            f"**Reset effectué** • La whitelist a été reset.")

    @_color_settings.command(name="getcache")
    @checks.is_owner()
    async def get_colors_cache(self, ctx):
        """Affiche ce que contient le cache des rôles de couleur"""
        roles = await self.config.guild(ctx.guild).roles()
        txt = "\n".join([discord_get(ctx.guild.roles, name=r) for r in roles])
        if txt:
            await ctx.send(txt)
        else:
            await ctx.send("**Cache vide**")

    @_color_settings.command(name="extlimit")
    @checks.is_owner()
    async def set_extcolor_limit(self, ctx, value: int):
        """Modifie le nombre par défaut de couleurs extraites par Extcolor"""
        if value > 0:
            await self.config.extcolor_limit.set(value)
            await ctx.send(f"L'extracteur de couleurs pourra extraire par défaut {value} couleurs des images.")
        else:
            await ctx.send(f"Valeur invalide, elle doit être positive.")

    @_color_settings.command(name="exttolerance")
    @checks.is_owner()
    async def set_extcolor_tolerance(self, ctx, value: int):
        """Modifie la tolérance (en %) supporté par Extcolor, càd la qualité de détail d'extraction des couleurs"""
        if 0 <= value <= 100:
            await self.config.extcolor_tolerance.set(value)
            await ctx.send(f"L'extracteur de couleurs utilisera désormais une tolérance de {value}.")
        else:
            await ctx.send(f"Valeur invalide, elle doit être comprise entre 0 et 100 (%).")

    async def red_delete_data_for_user(self, **kwargs):
        """Nothing to delete."""
        return