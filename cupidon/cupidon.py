import logging

import aiohttp
import discord
from bs4 import BeautifulSoup
from redbot.core import commands
from redbot.core.commands import Cog
from redbot.core.utils.chat_formatting import box

log = logging.getLogger("red.RedAppsv2.Cupidon")


class Cupidon(Cog):
    """Calcul du pourcentage de compatibilité amoureuse entre deux membres"""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def red_delete_data_for_user(self, **kwargs):
        """Nothing to delete"""
        return

    @commands.command(aliases=["love"])
    async def cupidon(
        self, ctx: commands.Context, lover: discord.Member, loved: discord.Member
    ):
        """Calcule le pourcentage de compatibilité amoureuse"""

        x = lover.display_name
        y = loved.display_name

        url = "https://www.lovecalculator.com/love.php?name1={}&name2={}".format(
            x.replace(" ", "+"), y.replace(" ", "+")
        )
        async with aiohttp.ClientSession(headers={"Connection": "keep-alive"}) as session:
            async with session.get(url, ssl=False) as response:
                assert response.status == 200
                resp = await response.text()

        log.debug(f"{resp=}")
        soup_object = BeautifulSoup(resp, "html.parser")

        description = soup_object.find("div", class_="result__score").get_text()

        if description is None:
            description = f"Dr. {self.bot.user.name} est occupé..."
        else:
            description = description.strip()

        result_image = soup_object.find("img", class_="result__image").get("src")

        result_text = soup_object.find("div", class_="result-text")
        if result_text is None:
            result_text = f"**{x}** et **{y}** ne sont pas compatibles 😔"
        else:
            result_text = result_text.get_text()
        result_text = " ".join(result_text.split())

        try:
            z = description[:2]
            z = int(z)
            if z > 50:
                emoji = "❤"
            else:
                emoji = "💔"
            title = f"Dr. {self.bot.user.name} dit que la compatibilité entre **{x}** et **{y}** est de : {emoji} {description} {emoji}"
        except (TypeError, ValueError):
            title = f"Dr. {self.bot.user.name} a rencontré des problèmes en réalisant son calcul."

        text = result_text.replace('Dr. Love', f'Dr. {self.bot.user.name}')
        em = discord.Embed(
            title=title, description=box(text), color=discord.Color.red(), url=url
        )
        em.set_image(url=f"https://www.lovecalculator.com/{result_image}")
        await ctx.send(embed=em)
