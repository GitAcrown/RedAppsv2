import asyncio
import logging

import discord
import wikipedia
from fuzzywuzzy import process
from redbot.core import Config, commands
from redbot.core.utils.menus import start_adding_reactions

logger = logging.getLogger("red.RedAppsv2.web")


class Web(commands.Cog):
    """Compilation de commandes de recherche"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'wiki_default_lang': 'fr'}
        self.config.register_guild(**default_guild)

    def redux(self, string: str, separateur: str = ".", limite: int = 2000):
        n = -1
        while len(separateur.join(string.split(separateur)[:n])) >= limite:
            n -= 1
        return separateur.join(string.split(separateur)[:n]) + separateur

    async def wiki_search(self, ctx, query: str, lang: str):
        wikipedia.set_lang(lang)
        results, suggestions = wikipedia.search(query, suggestion=True)
        if results:
            if results[0].lower() != query.lower():
                best = process.extractOne(query, results, score_cutoff=95)
                if best:
                    page = best[0]
                    return wikipedia.page(title=page)
                else:
                    all_results = results + suggestions if suggestions else results
                    bests = process.extractBests(query, all_results, score_cutoff=79)
                    if bests:
                        letters = [i for i in "🇦🇧🇨🇩🇪"]
                        emojis = []
                        n = 0
                        txt = ""
                        choices = {}
                        for r in bests:
                            txt += f"**{letters[n]}** - {r[0]}\n"
                            choices[letters[n]] = r[0]
                            emojis.append(letters[n])
                            n += 1

                        em = discord.Embed(title=f"Suggestions pour : {query}", description=txt, color=ctx.author.color)
                        em.set_footer(text="Cliquez sur l'emoji correspondant à votre demande")
                        menu = await ctx.send(embed=em)

                        cancel = self.bot.get_emoji(812451214179434551)
                        emojis.append(cancel)
                        start_adding_reactions(menu, emojis)

                        try:
                            react, ruser = await self.bot.wait_for("reaction_add",
                                                                   check=lambda m,
                                                                                u: u == ctx.author and m.message.id == menu.id,
                                                                   timeout=30)
                        except asyncio.TimeoutError:
                            await menu.delete()
                            return None
                        else:
                            await menu.delete()
                            page = choices[react.em]
                            return wikipedia.page(title=page)
                    elif lang != 'en':
                        return await self.wiki_search(ctx, query, 'en')
                    else:
                        sugg = wikipedia.suggest(query)
                        if sugg:
                            await ctx.send("**Introuvable** › Essayez peut-être avec :\n" + "\n".join([f"*{s.title()}*"
                                                                                                       for s in sugg]))
                        else:
                            await ctx.send(f"**Aucun résultat** › Je n'ai rien trouvé pour *{query}*")
                        return None
            else:
                return wikipedia.page(title=results[0])
        elif lang != 'en':
            return await self.wiki_search(ctx, query, 'en')
        else:
            sugg = wikipedia.suggest(query)
            if sugg:
                await ctx.send("**Introuvable** › Essayez peut-être avec :\n" + "\n".join([f"*{s.title()}*"
                                                                                           for s in sugg]))
            else:
                await ctx.send(f"**Aucun résultat** › Je n'ai rien trouvé pour *{query}*")
            return None

    @commands.command(name="wikipedia", aliases=["wiki"])
    async def search_wikipedia(self, ctx, *, recherche: str):
        """Rechercher un sujet sur Wikipédia"""
        def_lang = await self.config.guild(ctx.guild).wiki_default_lang()
        result = await self.wiki_search(ctx, recherche, def_lang)
        if result:
            images = result.images
            image = [i for i in images if i.endswith(".png") or i.endswith(".gif") or i.endswith(".jpg") or i.endswith(".jpeg") or i.endswith('webp')][0]
            em = discord.Embed(color=0xeeeeee, description=self.redux(result.summary))
            em.add_field(name="En savoir plus", value=f"<{result.url}>")
            em.set_author(name=result.title,
                          icon_url="https://upload.wikimedia.org/wikipedia/commons/thumb/7/77/Wikipedia_svg_logo.svg/1024px-Wikipedia_svg_logo.svg.png")
            if image:
                em.set_thumbnail(url=image)

            wikipedia.set_lang(def_lang)
            sugg = wikipedia.search(recherche)
            if result.title in sugg:
                sugg.remove(result.title)
            if sugg:
                em.set_footer(text="Voir aussi : " + ", ".join(sugg))
            await ctx.send(embed=em)