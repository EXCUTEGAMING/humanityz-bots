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
    raise RuntimeError("TOKEN/DISCORD_TOKEN missing. Set Railway Variable TOKEN.")

# Slash-only
intents = discord.Intents.none()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Paths (Railway-safe)
BASE_PATH = Path(__file__).parent
DATA_PATH = BASE_PATH / "data"
FACTIONS_PATH = DATA_PATH / "factions" / "factions.json"
PLAYERS_PATH = DATA_PATH / "players" / "players.json"

DEFAULT_FACTIONS = {
  "LDF": {
    "name": "Livonian Defence Forces",
    "side": "state",
    "playable": True,
    "description": "Staat/Verteidiger. Ordnung, Versorgung, Struktur."
  },
  "CMC": {
    "name": "Chernarus Mining Corporation",
    "side": "invader",
    "playable": True,
    "description": "Invasoren/Corporate. Expansion, Kontrolle, Ressourcen."
  },
  "IND": {
    "name": "Unabhängige",
    "side": "independent",
    "playable": True,
    "description": "Weder Staat noch CMC. Eigene Agenda, flexibel."
  },
  "UN": {
    "name": "United Nations",
    "side": "neutral_team",
    "playable": False,
    "description": "Team-Fraktion. Neutral, fördert Spawn & IC-Aktionen."
  }
}

def load_json(path: Path, default):
    # ensure file exists
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, indent=2, ensure_ascii=False), encoding="utf-8")
        return default

    raw = path.read_bytes()

    # robust decode (fixes Windows ANSI files)
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except UnicodeDecodeError:
            continue

    # never crash
    return default

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def bootstrap_files():
    # factions
    factions = load_json(FACTIONS_PATH, DEFAULT_FACTIONS)
    if not factions:
        factions = DEFAULT_FACTIONS
    save_json(FACTIONS_PATH, factions)

    # players
    players = load_json(PLAYERS_PATH, {})
    if players is None:
        players = {}
    save_json(PLAYERS_PATH, players)

@bot.event
async def on_ready():
    bootstrap_files()

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

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"[CMD-ERROR] cmd={interaction.command} user={interaction.user} error={repr(error)}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Fehler im Command (siehe Logs).", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Fehler im Command (siehe Logs).", ephemeral=True)
    except Exception:
        pass

@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong ✅ (SYSTEMBOT)", ephemeral=True)

@bot.tree.command(name="factions", description="List all available factions.")
async def factions(interaction: discord.Interaction):
    factions_data = load_json(FACTIONS_PATH, DEFAULT_FACTIONS)

    msg = "**Verfügbare Fraktionen:**\n"
    for key, f in factions_data.items():
        status = "spielbar" if f.get("playable") else "nicht spielbar"
        desc = f.get("description", "")
        msg += f"- **{key}** – {f.get('name','?')} ({status})\n"
        if desc:
            msg += f"  _{desc}_\n"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="join_faction", description="Join a playable faction.")
@app_commands.describe(faction="LDF / CMC / IND")
async def join_faction(interaction: discord.Interaction, faction: str):
    faction = faction.upper().strip()

    factions_data = load_json(FACTIONS_PATH, DEFAULT_FACTIONS)
    if faction not in factions_data:
        await interaction.response.send_message("❌ Diese Fraktion existiert nicht.", ephemeral=True)
        return

    if not factions_data[faction].get("playable"):
        await interaction.response.send_message("❌ Diese Fraktion ist nicht spielbar.", ephemeral=True)
        return

    players = load_json(PLAYERS_PATH, {})
    players[str(interaction.user.id)] = {"name": interaction.user.name, "faction": faction}
    save_json(PLAYERS_PATH, players)

    await interaction.response.send_message(f"✅ Du bist jetzt Teil der Fraktion **{faction}**.", ephemeral=True)

bot.run(TOKEN)
