from copy import copy
from datetime import datetime
import logging
from typing import Union, cast

import aiohttp
import discord
from discord.ext import tasks
from redbot.core import Config, commands, checks

logger = logging.getLogger("red.RedAppsv2.msggallery")

class MsgGalleryError(Exception):
    pass


class ChannelUnavailable(MsgGalleryError):
    """Le channel dédié à la galerie n'est pas disponible"""

class NoMsgData(MsgGalleryError):
    """Les données du message donné sont inexistantes"""

class InvalidEmoji(MsgGalleryError):
    """L'emoji ne peut être affiché car il est invalide"""


class MsgGallery(commands.Cog):
    """Galerie des meilleurs messages du serveur"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {"channel": None,
                         "webhook_url": None,
                         "webhook_name": "Galerie des messages",

                         "emoji": "⭐",
                         "target": 5,
                         "mods_count_as": 1,
                         "embed_color": 0xffac33,

                         "cache": {}}
        self.config.register_guild(**default_guild)

        self.msgg_clear_loop.start()

    @tasks.loop(hours=12)
    async def msgg_clear_loop(self):
        await self.clear_msgg_caches()

    @msgg_clear_loop.before_loop
    async def before_msgg_loop(self):
        logger.info('Starting msgg_clear_loop...')
        await self.bot.wait_until_ready()

    async def clear_msgg_caches(self):
        all_guilds = await self.config.all_guilds()
        for g in all_guilds:
            cache = all_guilds[g]['cache']
            new = copy(cache)
            for fav in cache:
                if cache[fav]['created'] < datetime.utcnow().timestamp() - 86400:
                    del new[fav]
            if cache != new:
                await self.config.guild_from_id(g).cache.set(new)

    def encode_emoji(self, emoji: Union[discord.Emoji, discord.PartialEmoji, str]):
        """Enregistre un emoji"""
        if type(emoji) in (discord.Emoji, discord.PartialEmoji):
            return emoji.id
        return emoji

    def decode_emoji(self, emoji: str):
        """Décode l'emoji enregistré"""
        if emoji.isdigit():
            return self.bot.get_emoji(int(emoji))
        return emoji

    def get_emoji_repr(self, emoji: Union[discord.Emoji, discord.PartialEmoji, str]):
        """Retourne la représentation imagée de l'emoji"""
        if type(emoji) in (discord.Emoji, discord.PartialEmoji):
            d_emoji = cast(discord.Emoji, emoji)
            ext = "gif" if d_emoji.animated else "png"
            return "https://cdn.discordapp.com/emojis/{id}.{ext}?v=1".format(id=d_emoji.id, ext=ext)
        try:
            cdn_fmt = "https://twemoji.maxcdn.com/2/72x72/{codepoint:x}.png"
            return cdn_fmt.format(codepoint=ord(str(emoji)))
        except TypeError:
            raise InvalidEmoji('Emoji invalide')
        except:
            raise

    async def post_msg(self, message: discord.Message):
        guild = message.guild
        data = await self.config.guild(guild).all()
        channel = self.bot.get_channel(data['channel']) if data['channel'] else None
        if not channel:
            raise ChannelUnavailable('Salon textuel non disponible')

        try:
            msg_data = data['cache'][message.id]
        except:
            raise NoMsgData("Le message fourni n'a pas de données enregistrées")

        text = f"[→ *Aller au message*]({message.jump_url})\n"
        text += message.content
        votes = len(msg_data["votes"])
        emoji = self.decode_emoji(data['emoji'])
        color = data.get('embed_color', await self.bot.get_embed_color(channel))
        foot = f"{emoji} {votes}"

        em = discord.Embed(description=text, color=color, timestamp=message.created_at)
        em.set_author(name=message.author.name, icon_url=message.author.avatar_url)
        em.set_footer(text=foot)

        img, emimg, misc = None, None, None
        emtxt = ""
        if message.attachments:
            attach = message.attachments[0]
            ext = attach.filename.split(".")[-1]
            if ext.lower() in ["png", "jpg", "jpeg", "gif", "gifv", "webp"]:
                img = attach.url
            else:
                misc = attach.url
        if message.embeds:
            msg_em = message.embeds[0]
            emtxt = "> " + msg_em.description if msg_em.description else ""
            if msg_em.image:
                emimg = msg_em.image.url
            elif msg_em.thumbnail:
                emimg = msg_em.thumbnail.url
        if img:
            em.set_image(url=img)
            if emimg:
                emtxt = emtxt + f"\n{emimg}" if emtxt else emimg
        elif emimg:
            em.set_image(url=emimg)
        if misc:
            emtxt = emtxt + f"\n{misc}" if emtxt else misc
        if emtxt:
            em.add_field(name="Contenu ↓", value=emtxt, inline=False)

        if data['webhook_url']:
            webhook_img = self.get_emoji_repr(emoji)
            try:
                async with aiohttp.ClientSession() as session:
                    webhook = discord.Webhook.from_url(data['webhook_url'], adapter=discord.AsyncWebhookAdapter(session))
                    return await webhook.send(embed=em, username=data['webhook_name'], avatar_url=webhook_img, wait=True)
            except:
                raise
        else:
            return await channel.send(embed=em)

    async def edit_msg(self, source_message: discord.Message, dest_message: Union[discord.WebhookMessage, discord.Message]):
        guild = dest_message.guild
        data = await self.config.guild(guild).all()

        channel = self.bot.get_channel(data['channel']) if data['channel'] else None
        if not channel:
            raise ChannelUnavailable('Salon textuel non disponible')

        try:
            msg_data = data['cache'][source_message.id]
        except:
            raise NoMsgData("Le message fourni n'a pas de données enregistrées")

        votes = len(msg_data["votes"])
        emoji = self.decode_emoji(data['emoji'])
        foot = f"{emoji} {votes}"
        em = dest_message.embeds[0]
        em.set_footer(text=foot)
        try:
            return await dest_message.edit(embed=em)
        except discord.Forbidden:
            logger.info(f"Impossible d'accéder à MSG_ID={dest_message.id}")
        except:
            logger.info(
                f"Suppression des données de {source_message.id} car impossibilité définitive d'accéder à MSG_ID={dest_message.id} "
                f"(message probablement supprimé)")
            await self.config.guild(guild).favs.clear_raw(source_message.id)
            raise

    @commands.group(name="msgg")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_messages=True)
    async def _msggallery(self, ctx):
        """Paramètres de la galerie de messages favoris"""

    @_msggallery.command(name="channel")
    async def msgg_channel(self, ctx, channel: discord.TextChannel = None):
        """Configurer le salon receveur des messages favoris et activer la fonctionnalité

        Pour désactiver cette fonctionnalité, rentrez la commande sans aucun salon"""
        guild = ctx.guild
        if channel:
            await self.config.guild(guild).channel.set(channel.id)
            await ctx.send(f"**Salon réglé** • Le salon receveur des messages est {channel.mention}.")
        else:
            await self.config.guild(guild).channel.set(None)
            await ctx.send(f"**Salon retiré** • La fonctionnalité est désactivée.")

    @_msggallery.command(name="webhook")
    async def msgg_webhook(self, ctx, webhook_url: str = None):
        """Activer/Désactiver l'utilisation d'un webhook pour la galerie

        Si vous fournissez une URL de Webhook, le channel où se trouve le Webhook prime sur le channel réglé avec `[p]msgg channel`"""
        guild = ctx.guild
        prev = await self.config.guild(guild).webhook_url()
        if webhook_url:
            async with aiohttp.ClientSession() as session:
                try:
                    webhook = discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(session))
                    await webhook.send("Ce message a été envoyé pour tester l'URL de Webhook fournie\n"
                                              "Si ce message s'affiche correctement vous pouvez le supprimer.",
                                              username="Test", avatar_url=self.bot.user.avatar_url)
                except:
                    return await ctx.send("**Erreur** • L'URL fournie n'est pas valide, vérifiez le webhook créé.")
                else:
                    await self.config.guild(guild).webhook_url.set(webhook_url)
                    await ctx.send(f"**Webhook configuré** • Son URL est <{webhook_url}>")
        else:
            if prev:
                await self.config.guild(guild).webhook_url.set(None)
                await ctx.send(f"**Webhook retiré** • J'utiliserai désormais directement mes propres messages.")
            else:
                chan = await self.config.guild(guild).channel()
                channel = self.bot.get_channel(chan) if chan else None
                if channel:
                    try:
                        webhook_url = await channel.create_webhook(name=await self.config.guild(guild).webhook_name(),
                                                                   avatar=self.bot.user.avatar_url,
                                                                   reason=f"Création sur demande de {ctx.author} pour la galerie des messages")
                    except:
                        await ctx.send("**Webhook impossible à créer** • Je n'ai réussi à créer le webhook.\n"
                                              "Vérifiez mes permissions ou fournissez-moi directement une URL avec la commande.")
                        raise
                    else:
                        await self.config.guild(guild).webhook_url.set(webhook_url)
                        await ctx.send(f"**Webhook créé** • J'ai créé un webhook au salon configuré : {webhook_url}")
                else:
                    return await ctx.send("**Webhook impossible à créer** • Définissez d'abord un salon de destination avec la commande `[p]msgg channel`.")

    @_msggallery.command(name="emoji")
    async def msgg_emoji(self, ctx, emoji: Union[discord.Emoji, discord.PartialEmoji, str] = "⭐"):
        """Modifier l'emoji utilisé pour mettre un message en favori (et pour l'avatar si la fonction Webhook est utilisée)

        L'emoji peut-être un emoji Discord de base ou un emoji custom de votre serveur (le bot doit pouvoir l'utiliser)
        Par défaut l'emoji :star:."""
        guild = ctx.guild
        if type(emoji) in (discord.Emoji, discord.PartialEmoji):
            if not emoji.is_usable():
                return await ctx.send(f"**Emoji invalide** • Je ne peux pas utiliser l'emoji fourni, choisissez un emoji Discord ou un emoji customisé de ce serveur")
        await self.config.guild(guild).emoji.set(self.encode_emoji(emoji))
        await ctx.send(f"**Emoji modifié** • L'emoji de détection sera désormais {emoji}")

    @_msggallery.command(name="webhookname")
    async def msgg_whname(self, ctx, name: str):
        """Modifier le nom du Webhook utilisé pour afficher les messages

        Disponible seulement si la fonctionnalité Webhook est activée"""
        guild = ctx.guild
        if await self.config.guild(guild).webhook_url() and len(name) <= 32:
            await self.config.guild(guild).webhook_name.set(name)
            await ctx.send(f"**Nom modifié** • Le webhook utilisera le nom ***{name}***")
        else:
            await ctx.send(f"**Erreur** • La fonction webhook n'est pas activée (`[p]msgg webhook`) ou le nom donné est trop long (32 caractères max)")

    @_msggallery.command(name="target")
    async def msgg_target(self, ctx, limit: int = 5):
        """Modifier le nombre de votes qu'un message doit atteindre pour être mis en favori

        Un modérateur peut avoir un vote comptant pour plusieurs, voir `[p]msgg modsvote`
        Par défaut 5."""
        guild = ctx.guild
        if limit > 0:
            await self.config.guild(guild).target.set(limit)
            await ctx.send(
                f"**Valeur modifiée** • Il faudra {limit} votes pour qu'un message soit posté dans le salon des favoris")
        else:
            await ctx.send(f"**Valeur refusée** • Celle-ci doit être supérieure ou égale à 1.")

    @_msggallery.command(name="modsvote")
    async def msgg_modsvote(self, ctx, count_as: int = 1):
        """Modifier le nombre de votes qu'un modérateur peut attribuer à un message

        Concrètement, cela permet à un modérateur d'avoir un vote qui compte double, triple etc.
        Mettre la même valeur ou + que le target signifie qu'un seul vote d'un modérateur suffit à mettre le message visé en favori
        Par défaut 1."""
        guild = ctx.guild
        if count_as > 0:
            await self.config.guild(guild).mods_count_as.set(count_as)
            await ctx.send(
                f"**Valeur modifiée** • Un vote de modérateur comptera désormais pour {count_as}")
        else:
            await ctx.send(f"**Valeur refusée** • Celle-ci doit être supérieure ou égale à 1.")

    @_msggallery.command(name="color")
    async def msgg_color(self, ctx, color: str = None):
        """Modifie la couleur des Embeds des favoris postés sur le salon

        Pour remettre la couleur par défaut du bot il suffit de ne pas rentrer de couleur"""
        if color:
            try:
                color = color.replace("#", "0x")
                color = int(color, base=16)
                em = discord.Embed(title="Couleur modifiée",
                                   description=f"Ceci est une démonstration de la couleur des Embeds du salon des favoris.",
                                   color=color)
                await self.config.guild(ctx.guild).embed_color.set(color)
            except:
                return await ctx.send("**Erreur** • La couleur est invalide.\n"
                                      "Sachez qu'elle doit être fournie au format hexadécimal (ex. `D5D5D5` ou `0xD5D5D5`) et que certaines couleurs sont réservées par Discord.")
        else:
            em = discord.Embed(title="Couleur retirée",
                               description=f"Ceci est une démonstration de la couleur des Embeds du salon des favoris.",
                               color=color)
            await self.config.guild(ctx.guild).embed_color.set(None)
        await ctx.send(embed=em)

    @_msggallery.command(name="reset")
    async def msgg_reset(self, ctx, cache_only: bool = True):
        """Reset les données enregistrées des favoris sur le serveur

        Si vous précisez 'False' après la commande, effacera toutes les données MsgGallery"""
        if cache_only:
            await self.config.guild(ctx.guild).cache.clear()
            await ctx.send("**Reset effectué** • Les données des favoris ont été réset.\n"
                           "Notez que ça n'efface pas les messages déjà postés sur le salon, mais l'historique ayant été effacé un message peut être reposté.")
        else:
            await self.config.guild(ctx.guild).clear()
            await ctx.send("**Reset effectué** • Les données du serveur ont été reset.\n"
                           "Notez que ça n'efface pas les messages déjà postés sur le salon, mais l'historique ayant été effacé un message peut être reposté.\n"
                           "N'oubliez pas de rétablir vos paramètres si vous voulez réutiliser ce module.")


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        channel = self.bot.get_channel(payload.channel_id)
        emoji = payload.emoji
        if hasattr(channel, "guild"):
            guild = channel.guild
            data = await self.config.guild(guild).all()
            if data["channel"]:
                emoji = emoji.name if emoji.is_unicode_emoji() else str(emoji.id)
                logger.info(str(emoji))
                if emoji == data["emoji"]:
                    logger.info('Emoji détecté')
                    message = await channel.fetch_message(payload.message_id)
                    if message.created_at.timestamp() + 86400 > datetime.utcnow().timestamp():
                        user = guild.get_member(payload.user_id)
                        favchan = guild.get_channel(data["channel"])

                        try:
                            fav = await self.config.guild(guild).cache.get_raw(message.id)
                        except:
                            fav = {"votes": [], "embed": None, 'created': datetime.utcnow().timestamp()}
                            await self.config.guild(guild).cache.set_raw(message.id, value=fav)

                        if user.id not in fav["votes"]:
                            if user.permissions_in(channel).manage_messages:
                                fav["votes"].append([user.id] * data['mods_count_as'])
                            else:
                                fav["votes"].append(user.id)

                            if len(fav["votes"]) >= data["target"]:
                                if not fav["embed"]:
                                    try:
                                        embed_msg = await self.post_msg(message)
                                    except Exception as e:
                                        logger.error(msg=e, exc_info=True)
                                    else:
                                        fav["embed"] = embed_msg.id
                                else:
                                    try:
                                        embed_msg = await favchan.fetch_message(fav["embed"])
                                    except Exception as e:
                                        logger.error(msg=e, exc_info=True)
                                    else:
                                        await self.edit_msg(message, embed_msg)
                            await self.config.guild(guild).cache.set_raw(message.id, value=fav)
