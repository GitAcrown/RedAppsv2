from .cupidon import Cupidon


def setup(bot):
    bot.add_cog(Cupidon(bot))