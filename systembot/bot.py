# -*- coding: utf-8 -*-
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

if not TOKEN:
    raise RuntimeError("TOKEN/DISCORD_TOKEN is missing. Set Railway Variable TOKEN.")

# Slash-only: keine privileged intents nötig
intents = discord.Intents.none()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ Pfade relativ zur Datei (Railway-sicher)
BASE_PATH = Path(__file__).parent
DATA_PATH = BASE_PATH / "data"
FACTIONS_PATH = DATA_PATH / "factions" / "factions.json"
PLAYERS_PATH = DATA_PATH / "players" / "players.json"


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
            await bot.tree.sync(guild=guild)
            print(f"[READY] Commands synced to Guild: {GUILD_ID}")
        else:
            await bot.tree.sync()
            print("[READY] Commands synced globally")
    except Exception as e:
        print(f"[SYNC ERROR] {repr(e)}")

    print(f"[ONLINE] Logged in as {bot.user} (ID: {bot.user.id})")


# ✅ Wenn ein Command crasht, siehst du es in Logs + User bekommt Antwort
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"[CMD-ERROR] cmd={interaction.command} user={interaction.user} error={repr(error)}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Fehler im Command (siehe Logs).", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Fehler im Command (siehe Logs).", ephemeral=True)
    except Exception as e:
        print(f"[CMD-ERROR] could not respond: {repr(e)}")


@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    print(f"[CMD] /ping by {interaction.user}")
    await interaction.response.send_message("pong ✅ (SYSTEMBOT)", ephemeral=True)


@bot.tree.command(name="factions", description="List all available factions.")
async def factions(interaction: discord.Interaction):
    print(f"[CMD] /factions by {interaction.user}")

    factions_data = load_json(FACTIONS_PATH, {})
    if not factions_data:
        await interaction.response.send_message("⚠️ Keine Fraktionen definiert.", ephemeral=True)
        return

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
    print(f"[CMD] /join_faction by {interaction.user} -> {faction}")

    factions_data = load_json(FACTIONS_PATH, {})
    if faction not in factions_data:
        await interaction.response.send_message("❌ Diese Fraktion gibt es nicht.", ephemeral=True)
        return

    if not factions_data[faction].get("playable"):
        await interaction.response.send_message("❌ Diese Fraktion ist nicht spielbar (Team/Story).", ephemeral=True)
        return

    players_data = load_json(PLAYERS_PATH, {})
    players_data[str(interaction.user.id)] = {
        "name": interaction.user.name,
        "faction": faction
    }
    save_json(PLAYERS_PATH, players_data)

    await interaction.response.send_message(f"✅ Du bist jetzt Teil der Fraktion **{faction}**.", ephemeral=True)


bot.run(TOKEN)
