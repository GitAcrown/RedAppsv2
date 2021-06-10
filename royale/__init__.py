from redbot.core import data_manager
from .royale import Royale

__red_end_user_data_statement__ = 'This cog does not store personal data.'

async def setup(bot):
    royale = Royale(bot)
    data_manager.bundled_data_path(royale)
    await royale._load_bundled_data()
    bot.add_cog(royale)
