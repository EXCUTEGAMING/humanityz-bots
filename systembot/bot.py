import os
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

intents = discord.Intents.none()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_PATH = Path("data")

def load_json(path: Path, default):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

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

@bot.tree.command(name="factions", description="List all available factions.")
async def factions(interaction: discord.Interaction):
    factions_path = DATA_PATH / "factions" / "factions.json"
    factions_data = load_json(factions_path, {})

    msg = "**Verfügbare Fraktionen:**\n"
    for key, f in factions_data.items():
        status = "spielbar" if f.get("playable") else "nicht spielbar"
        desc = f.get("description", "")
        msg += f"- **{key}** – {f.get('name','?')} ({status})\n"
        if desc:
            msg += f"  _{desc}_\n"

    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="join_faction", description="Join a faction (LDF/CMC/IND).")
@app_commands.describe(faction="Faction key: LDF / CMC / IND")
async def join_faction(interaction: discord.Interaction, faction: str):
    faction = faction.upper().strip()

    factions_data = load_json(DATA_PATH / "factions" / "factions.json", {})
    if faction not in factions_data:
        await interaction.response.send_message("Diese Fraktion gibt es nicht.", ephemeral=True)
        return

    if not factions_data[faction].get("playable"):
        await interaction.response.send_message("Diese Fraktion ist nicht spielbar (Team/Story).", ephemeral=True)
        return

    players_path = DATA_PATH / "players" / "players.json"
    players_data = load_json(players_path, {})

    players_data[str(interaction.user.id)] = {
        "name": interaction.user.name,
        "faction": faction
    }
    save_json(players_path, players_data)

    await interaction.response.send_message(f"Du bist jetzt Teil der Fraktion **{faction}**.", ephemeral=True)

def main():
    if not TOKEN:
        raise RuntimeError("TOKEN/DISCORD_TOKEN is missing. Set Railway Variable TOKEN.")
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
