import os
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} ist online")

@bot.tree.command(name="ping", description="Testet ob der Bot läuft")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong! SystemBot läuft.", ephemeral=True)

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt!")

bot.run(TOKEN)
