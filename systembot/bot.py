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
STATIONS_PATH = DATA_PATH / "stations" / "stations.json"

STATION_TYPES = {
    "CAMP": {"min_players": 1, "notes": "Camp (mind. 1 Spieler)"},
    "DORF": {"min_players": 4, "notes": "Dorf (mind. 4 Spieler)"},
    "SIEDLUNG": {"min_players": 10, "notes": "Siedlung (10 Spieler oder 8 Spieler-Fraktion)"},
    "AUSSENPOSTEN": {"min_players": 5, "notes": "Außenposten (mind. 5 Spieler-Fraktion)"},
    "STRATEGISCH": {"min_players": 5, "notes": "Strategischer Punkt (Capture + 48h Schutz)"},
}

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
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, indent=2, ensure_ascii=False), encoding="utf-8")
        return default

    raw = path.read_bytes()

    # robust decode + parse (handles UTF-8 BOM + Windows ANSI)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue

    return default

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def is_staff(interaction: discord.Interaction) -> bool:
    # MVP: Admin Permission reicht erstmal
    return interaction.user.guild_permissions.administrator

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

    # stations
    stations = load_json(STATIONS_PATH, {})
    if stations is None:
        stations = {}
    save_json(STATIONS_PATH, stations)

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

@bot.tree.command(name="whoami", description="Show your faction.")
async def whoami(interaction: discord.Interaction):
    players = load_json(PLAYERS_PATH, {})
    user_id = str(interaction.user.id)

    if user_id not in players:
        await interaction.response.send_message(
            "Du bist noch keiner Fraktion zugewiesen. Nutze `/join_faction` oder frag die Fraktionsführung/Staff.",
            ephemeral=True
        )
        return

    faction = players[user_id].get("faction", "UNBEKANNT")
    await interaction.response.send_message(
        f"✅ Du bist in der Fraktion: **{faction}**",
        ephemeral=True
    )

@bot.tree.command(name="create_station", description="(Staff) Create a station for a faction.")
@app_commands.describe(
    station_id="Unique ID (e.g. nadbor_camp_01)",
    name="Display name",
    station_type="CAMP / DORF / SIEDLUNG / AUSSENPOSTEN / STRATEGISCH",
    owner_faction="LDF / CMC / IND",
    member_count="Current member count (for validation)"
)
async def create_station(
    interaction: discord.Interaction,
    station_id: str,
    name: str,
    station_type: str,
    owner_faction: str,
    member_count: int
):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff darf Stationen erstellen.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    station_type = station_type.upper().strip()
    owner_faction = owner_faction.upper().strip()

    if station_type not in STATION_TYPES:
        await interaction.response.send_message("❌ Ungültiger Stationstyp.", ephemeral=True)
        return

    min_p = STATION_TYPES[station_type]["min_players"]
    if member_count < min_p:
        await interaction.response.send_message(
            f"❌ Mindestspieler nicht erreicht: {station_type} braucht mind. {min_p}.",
            ephemeral=True
        )
        return

    stations = load_json(STATIONS_PATH, {})

    if station_id in stations:
        await interaction.response.send_message("❌ Station-ID existiert bereits.", ephemeral=True)
        return

    # Schutzzeit: Strategisch bekommt direkt 48h Schutz (nach euren Regeln)
    protection = 48 if station_type == "STRATEGISCH" else 0

    stations[station_id] = {
        "name": name,
        "type": station_type,
        "owner_faction": owner_faction,
        "member_count": member_count,
        "state": {
            "condition": 100,
            "protection_hours": protection
        }
    }

    save_json(STATIONS_PATH, stations)
    await interaction.response.send_message(
        f"✅ Station erstellt: **{name}** ({station_type}) für **{owner_faction}**\nID: `{station_id}`\nSchutz: {protection}h",
        ephemeral=True
    )

@bot.tree.command(name="station_info", description="Show station info by station_id.")
@app_commands.describe(station_id="Station ID (e.g. nadbor_camp_01)")
async def station_info(interaction: discord.Interaction, station_id: str):
    station_id = station_id.lower().strip()
    stations = load_json(STATIONS_PATH, {})

    if station_id not in stations:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = stations[station_id]
    cond = s.get("state", {}).get("condition", 0)
    prot = s.get("state", {}).get("protection_hours", 0)

    msg = (
        f"**Station:** {s.get('name','?')}\n"
        f"**ID:** `{station_id}`\n"
        f"**Typ:** {s.get('type','?')} ({STATION_TYPES.get(s.get('type',''),{}).get('notes','')})\n"
        f"**Besitzer:** {s.get('owner_faction','?')}\n"
        f"**Mitglieder (gemeldet):** {s.get('member_count','?')}\n"
        f"**Zustand:** {cond}/100\n"
        f"**Schutzzeit:** {prot}h\n"
    )

    await interaction.response.send_message(msg, ephemeral=True)

bot.run(TOKEN)
