import asyncio
import logging
from typing import Union
import discord
from redbot.core import Config, commands
import imdb
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import start_adding_reactions

logger = logging.getLogger("red.RedAppsv2.Lumen")

IMDB_Color = 0xEEC100
IMDB_Image = 'https://i.imgur.com/KzDQlv5.png'

FR_TR = {
    'movie': 'Film',
    'tv series': 'Série TV',
    'tv miniseries': 'Mini-série TV'
}


class Lumen(commands.Cog):
    """Base de données IMdb et progammation de streams"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=736144321857978388, force_registration=True)

        default_guild = {'imdb_country': 'France'}
        default_user = {}
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)


    def get_local_title(self, movie_id: Union[str, int], country: str):
        db = imdb.IMDb()
        data = db.get_movie_akas(movie_id)
        if data:
            if 'raw akas' in data['data']:
                countries = data['data']['raw akas']
                for c in countries:
                    if country.lower() in c.get('countries', '').lower():
                        return c['title']
        return db.get_movie(movie_id)['title'] if db.get_movie(movie_id) else ''

    def get_fast_embed(self, movie: Union[str, int, imdb.Movie.Movie], add_footer: str = '', *,
                        lang_country: str = 'France'):
        db = imdb.IMDb()
        if type(movie) != imdb.Movie.Movie:
            try:
                movie = db.get_movie(movie, info=['plot'])
            except imdb.IMDbError as e:
                logger.error(e, exc_info=True)
                return None
        else:
            db.update(movie, 'plot')

        if add_footer != '':
            add_footer = f' · {add_footer}'

        title = self.get_local_title(movie.movieID, lang_country)
        kind = movie['kind'].capitalize() if movie['kind'] not in FR_TR else FR_TR[movie['kind']]
        plot = movie['plot'][0].split('::')[0] if '::' in movie['plot'][0] else movie['plot'][0]
        em = discord.Embed(title="**{}** ({}, {})".format(title, kind, movie['year']),
                           description=plot,
                           color=IMDB_Color)
        em.set_footer(text=f"IMDb{add_footer}", icon_url=IMDB_Image)
        em.set_thumbnail(url=movie['cover url'])
        return em

    def get_movie_embed(self, movie: Union[str, int, imdb.Movie.Movie], add_footer: str = '', *,
                        lang_country: str = 'France'):
        db = imdb.IMDb()
        if type(movie) != imdb.Movie.Movie:
            try:
                movie = db.get_movie(movie, info=['main', 'plot'])
            except imdb.IMDbError as e:
                logger.error(e, exc_info=True)
                return None
        else:
            db.update(movie, ['main', 'plot'])

        if add_footer != '':
            add_footer = f' · {add_footer}'

        title = self.get_local_title(movie.movieID, lang_country)
        kind = movie['kind'].capitalize() if movie['kind'] not in FR_TR else FR_TR[movie['kind']]
        plot = movie['plot'][0].split('::')[0] if '::' in movie['plot'][0] else movie['plot'][0]
        rating = f"{movie.get('rating', '?')} ({movie.get('votes', 0)})"
        em = discord.Embed(title="**{}** ({}, {})".format(title, kind, movie['year']),
                           description=plot,
                           color=IMDB_Color)
        em.add_field(name="Note", value=box(rating))
        if movie.get('genres', False):
            em.add_field(name="Genre", value=box(', '.join(movie['genres'])))
        if movie.get('runtimes', False):
            runtime = movie['runtimes'] if type(movie['runtimes']) in (str, int) else movie['runtimes'][0]
            em.add_field(name="Durée", value=box(runtime + 'm'))
        em.set_footer(text=f"IMDb{add_footer}", icon_url=IMDB_Image)
        em.set_thumbnail(url=movie['full-size cover url'])
        return em

    def get_serie_embed(self, serie: Union[str, int, imdb.Movie.Movie], add_footer: str = '', *,
                        lang_country: str = 'France'):
        em = self.get_movie_embed(serie, add_footer, lang_country=lang_country)

        db = imdb.IMDb()
        if type(serie) != imdb.Movie.Movie:
            try:
                serie = db.get_movie(serie, info=['main', 'plot'])
            except imdb.IMDbError as e:
                logger.error(e, exc_info=True)
                return None
        else:
            try:
                db.update(serie, 'episodes')
            except Exception as e:
                logger.info(e, exc_info=True)
                return em

        seasons = [serie['episodes'][s] for s in serie['episodes'].keys() if s >= 0]
        len_seasons = str(len(seasons))
        len_episodes = str(sum([len(e) for e in seasons]))
        em.add_field(name="Nb. saisons", value=box(len_seasons))
        em.add_field(name="Nb. épisodes", value=box(len_episodes))
        return em

    async def fetch_movie_menu(self, ctx, search: str) -> Union[None, imdb.Movie.Movie]:
        db = imdb.IMDb()
        local_lang = 'France' if not ctx.guild else await self.config.guild(ctx.guild).imdb_country()

        results = db.search_movie(search)
        if not results:
            return None

        if len(results) > 1:
            results = results[:3]
            p = 1
            total = len(results)
            movies = []

            async with ctx.typing():
                for m in results:
                    movies.append((m, self.get_fast_embed(m, add_footer=f'Page {p}/{total}', lang_country=local_lang)))
                    p += 1

            current = 0
            menu = None

            while True:
                if menu:
                    await menu.edit(embed=movies[current][1])
                else:
                    menu = await ctx.send(embed=movies[current][1])
                    start_adding_reactions(menu, ['⬅️', '✅', '❎', '➡️'])

                try:
                    react, ruser = await self.bot.wait_for("reaction_add",
                                                           check=lambda rm,
                                                                        ru: ru == ctx.author and rm.message.id == menu.id,
                                                           timeout=30)
                except asyncio.TimeoutError:
                    await menu.delete()
                    return None

                if react.emoji == '✅':
                    await menu.clear_reactions()
                    return movies[current][0]
                elif react.emoji == '⬅️':
                    await menu.remove_reaction(ruser, '⬅️')
                    current = current - 1 if current > 0 else len(movies) - 1
                elif react.emoji == '➡️':
                    await menu.remove_reaction(ruser, '⬅️')
                    current = current + 1 if current < (len(movies) - 1) else 0
                elif react.emoji == '❎':
                    await menu.delete()
                    return None
                else:
                    await menu.remove_reaction(ruser, react.emoji)

        return results[0].movieID

    @commands.command(name="imdb")
    async def search_on_imdb(self, ctx, *, search: str):
        """Recherche un film/série sur la base de données IMDb

        Il est possible d'entrer directement l'ID IMDb du contenu recherché"""
        if search.isdigit():
            db = imdb.IMDb()
            async with ctx.typing():
                try:
                    movie = db.get_movie(search)
                except imdb.IMDbError as e:
                    logger.error(e, exc_info=True)
                    return await ctx.send("**Aucun résultat** • Vérifiez l'identifiant IMDb donné")
        else:
            movie = await self.fetch_movie_menu(ctx, search)

        if movie:
            if movie.get('kind', 'movie') in ('tv series', 'tv miniseries'):
                embed = self.get_serie_embed(movie, f"\"{search}\"")
            else:
                embed = self.get_movie_embed(movie, f"\"{search}\"")
            await ctx.send(embed=embed)
