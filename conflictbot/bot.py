import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # optional

# KEINE privileged intents (damit Railway + Discord Portal sofort klappt)
intents = discord.Intents.none()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"[READY] Slash-Commands synced to Guild: {GUILD_ID}")
        else:
            await bot.tree.sync()
            print("[READY] Global Slash-Commands synced")
    except Exception as e:
        print(f"[ERROR] Command sync failed: {e}")

    print(f"[ONLINE] Logged in as {bot.user} (ID: {bot.user.id})")

@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong ?", ephemeral=True)

def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing.")
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
