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

RESOURCE_ZONES = ["lager", "verarbeitung", "bauhaus", "produktion"]

def load_json(path: Path, default):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, indent=2, ensure_ascii=False), encoding="utf-8")
        return default

    raw = path.read_bytes()
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
    return interaction.user.guild_permissions.administrator

def bootstrap_files():
    factions = load_json(FACTIONS_PATH, DEFAULT_FACTIONS) or DEFAULT_FACTIONS
    save_json(FACTIONS_PATH, factions)

    players = load_json(PLAYERS_PATH, {})
    if players is None:
        players = {}
    save_json(PLAYERS_PATH, players)

    stations = load_json(STATIONS_PATH, {})
    if stations is None:
        stations = {}
    save_json(STATIONS_PATH, stations)

def ensure_station_resources(station: dict) -> dict:
    if "resources" not in station or not isinstance(station["resources"], dict):
        station["resources"] = {}
    for z in RESOURCE_ZONES:
        if z not in station["resources"] or not isinstance(station["resources"][z], dict):
            station["resources"][z] = {}
    return station

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

# --------------------
# BASIC
# --------------------
@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong ✅ (SYSTEMBOT)", ephemeral=True)

# --------------------
# FACTIONS / PLAYERS
# --------------------
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
    await interaction.response.send_message(f"✅ Du bist in der Fraktion: **{faction}**", ephemeral=True)

# --------------------
# STATIONS
# --------------------
@bot.tree.command(name="stations", description="List all stations (ID, name, type, owner).")
async def stations(interaction: discord.Interaction):
    stations_data = load_json(STATIONS_PATH, {})

    if not stations_data:
        await interaction.response.send_message("ℹ️ Es gibt aktuell keine Stationen.", ephemeral=True)
        return

    lines = ["**Alle Stationen:**"]
    for sid, s in sorted(stations_data.items()):
        members_count = len(s.get("members", []))
        lines.append(
            f"- `{sid}` | **{s.get('name','?')}** | {s.get('type','?')} | {s.get('owner_faction','?')} | Mitglieder: {members_count}"
        )

    # Discord hat Message-Limits, daher notfalls kürzen
    msg = "\n".join(lines)
    if len(msg) > 1800:
        msg = msg[:1800] + "\n…(gekürzt)"

    await interaction.response.send_message(msg, ephemeral=True)

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

    stations_data = load_json(STATIONS_PATH, {})
    if station_id in stations_data:
        await interaction.response.send_message("❌ Station-ID existiert bereits.", ephemeral=True)
        return

    protection = 48 if station_type == "STRATEGISCH" else 0

    station = {
        "name": name,
        "type": station_type,
        "owner_faction": owner_faction,
        "members": [],
        "member_count": member_count,
        "state": {"condition": 100, "protection_hours": protection},
    }
    station = ensure_station_resources(station)

    stations_data[station_id] = station
    save_json(STATIONS_PATH, stations_data)

    await interaction.response.send_message(
        f"✅ Station erstellt: **{name}** ({station_type}) für **{owner_faction}**\nID: `{station_id}`\nSchutz: {protection}h",
        ephemeral=True
    )

@bot.tree.command(name="station_info", description="Show station info by station_id.")
@app_commands.describe(station_id="Station ID (e.g. nadbor_camp_01)")
async def station_info(interaction: discord.Interaction, station_id: str):
    station_id = station_id.lower().strip()
    stations_data = load_json(STATIONS_PATH, {})

    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = ensure_station_resources(stations_data[station_id])
    cond = s.get("state", {}).get("condition", 0)
    prot = s.get("state", {}).get("protection_hours", 0)
    members_count = len(s.get("members", []))

    msg = (
        f"**Station:** {s.get('name','?')}\n"
        f"**ID:** `{station_id}`\n"
        f"**Typ:** {s.get('type','?')} ({STATION_TYPES.get(s.get('type',''),{}).get('notes','')})\n"
        f"**Besitzer:** {s.get('owner_faction','?')}\n"
        f"**Mitglieder:** {members_count}\n"
        f"**Zustand:** {cond}/100\n"
        f"**Schutzzeit:** {prot}h\n"
    )
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="station_members", description="List members of a station.")
@app_commands.describe(station_id="Station ID (e.g. nadbor_camp_01)")
async def station_members(interaction: discord.Interaction, station_id: str):
    station_id = station_id.lower().strip()
    stations_data = load_json(STATIONS_PATH, {})

    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = stations_data[station_id]
    members = s.get("members", [])

    if not members:
        await interaction.response.send_message("ℹ️ Station hat noch keine Mitglieder.", ephemeral=True)
        return

    lines = []
    for uid in members:
        member = interaction.guild.get_member(int(uid)) if interaction.guild else None
        if member:
            lines.append(f"- {member.mention} ({member.name})")
        else:
            lines.append(f"- <@{uid}>")

    msg = f"**Mitglieder von {s.get('name','?')}** (`{station_id}`)\n" + "\n".join(lines)
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="station_add_member", description="(Staff) Add a member to a station.")
@app_commands.describe(user="User to add", station_id="Station ID")
async def station_add_member(interaction: discord.Interaction, user: discord.Member, station_id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff darf Station-Mitglieder verwalten.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    stations_data = load_json(STATIONS_PATH, {})

    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = stations_data[station_id]
    members = s.get("members", [])

    uid = str(user.id)
    if uid in members:
        await interaction.response.send_message("ℹ️ Dieser Spieler ist bereits Mitglied der Station.", ephemeral=True)
        return

    members.append(uid)
    s["members"] = members
    s["member_count"] = len(members)

    stations_data[station_id] = ensure_station_resources(s)
    save_json(STATIONS_PATH, stations_data)

    await interaction.response.send_message(
        f"✅ {user.mention} wurde zu **{s.get('name','?')}** hinzugefügt.\nMitglieder: {len(members)}",
        ephemeral=True
    )

@bot.tree.command(name="station_remove_member", description="(Staff) Remove a member from a station.")
@app_commands.describe(user="User to remove", station_id="Station ID")
async def station_remove_member(interaction: discord.Interaction, user: discord.Member, station_id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff darf Station-Mitglieder verwalten.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    stations_data = load_json(STATIONS_PATH, {})

    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = stations_data[station_id]
    members = s.get("members", [])

    uid = str(user.id)
    if uid not in members:
        await interaction.response.send_message("ℹ️ Dieser Spieler ist kein Mitglied der Station.", ephemeral=True)
        return

    members.remove(uid)
    s["members"] = members
    s["member_count"] = len(members)

    stations_data[station_id] = ensure_station_resources(s)
    save_json(STATIONS_PATH, stations_data)

    await interaction.response.send_message(
        f"✅ {user.mention} wurde aus **{s.get('name','?')}** entfernt.\nMitglieder: {len(members)}",
        ephemeral=True
    )

@bot.tree.command(name="station_set_type", description="(Staff) Change station type.")
@app_commands.describe(station_id="Station ID", station_type="CAMP/DORF/SIEDLUNG/AUSSENPOSTEN/STRATEGISCH")
async def station_set_type(interaction: discord.Interaction, station_id: str, station_type: str):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    station_type = station_type.upper().strip()

    if station_type not in STATION_TYPES:
        await interaction.response.send_message("❌ Ungültiger Stationstyp.", ephemeral=True)
        return

    stations_data = load_json(STATIONS_PATH, {})
    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    stations_data[station_id]["type"] = station_type

    if station_type == "STRATEGISCH":
        st = stations_data[station_id].get("state", {})
        if st.get("protection_hours", 0) == 0:
            st["protection_hours"] = 48
            stations_data[station_id]["state"] = st

    save_json(STATIONS_PATH, stations_data)
    await interaction.response.send_message(f"✅ Typ gesetzt: `{station_id}` → **{station_type}**", ephemeral=True)

@bot.tree.command(name="station_set_condition", description="(Staff) Set station condition (0-100).")
@app_commands.describe(station_id="Station ID", condition="0-100")
async def station_set_condition(interaction: discord.Interaction, station_id: str, condition: int):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    condition = max(0, min(100, int(condition)))

    stations_data = load_json(STATIONS_PATH, {})
    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    st = stations_data[station_id].get("state", {})
    st["condition"] = condition
    stations_data[station_id]["state"] = st

    save_json(STATIONS_PATH, stations_data)
    await interaction.response.send_message(f"✅ Zustand gesetzt: `{station_id}` → **{condition}/100**", ephemeral=True)

@bot.tree.command(name="station_set_protection", description="(Staff) Set station protection hours.")
@app_commands.describe(station_id="Station ID", hours="Protection hours (e.g. 48)")
async def station_set_protection(interaction: discord.Interaction, station_id: str, hours: int):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    hours = max(0, int(hours))

    stations_data = load_json(STATIONS_PATH, {})
    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    st = stations_data[station_id].get("state", {})
    st["protection_hours"] = hours
    stations_data[station_id]["state"] = st

    save_json(STATIONS_PATH, stations_data)
    await interaction.response.send_message(f"✅ Schutzzeit gesetzt: `{station_id}` → **{hours}h**", ephemeral=True)

# --------------------
# RESOURCES (MVP)
# --------------------
@bot.tree.command(name="station_init_resources", description="(Staff) Initialize resources structure for a station.")
@app_commands.describe(station_id="Station ID")
async def station_init_resources(interaction: discord.Interaction, station_id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    stations_data = load_json(STATIONS_PATH, {})
    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    stations_data[station_id] = ensure_station_resources(stations_data[station_id])
    save_json(STATIONS_PATH, stations_data)
    await interaction.response.send_message("✅ Ressourcen-Struktur initialisiert.", ephemeral=True)

@bot.tree.command(name="resource_add", description="(Staff) Add resources to a station zone.")
@app_commands.describe(station_id="Station ID", zone="lager/verarbeitung/bauhaus/produktion", item="Item key", amount="Amount")
async def resource_add(interaction: discord.Interaction, station_id: str, zone: str, item: str, amount: int):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    zone = zone.lower().strip()
    item = item.lower().strip()
    amount = max(0, int(amount))

    if zone not in RESOURCE_ZONES:
        await interaction.response.send_message("❌ Ungültige Zone. Nutze lager/verarbeitung/bauhaus/produktion.", ephemeral=True)
        return

    stations_data = load_json(STATIONS_PATH, {})
    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = ensure_station_resources(stations_data[station_id])
    current = int(s["resources"][zone].get(item, 0))
    s["resources"][zone][item] = current + amount

    stations_data[station_id] = s
    save_json(STATIONS_PATH, stations_data)

    await interaction.response.send_message(f"✅ +{amount} **{item}** in **{zone}** (neu: {current + amount})", ephemeral=True)

@bot.tree.command(name="resource_take", description="(Staff) Take resources from a station zone.")
@app_commands.describe(station_id="Station ID", zone="lager/verarbeitung/bauhaus/produktion", item="Item key", amount="Amount")
async def resource_take(interaction: discord.Interaction, station_id: str, zone: str, item: str, amount: int):
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    zone = zone.lower().strip()
    item = item.lower().strip()
    amount = max(0, int(amount))

    if zone not in RESOURCE_ZONES:
        await interaction.response.send_message("❌ Ungültige Zone. Nutze lager/verarbeitung/bauhaus/produktion.", ephemeral=True)
        return

    stations_data = load_json(STATIONS_PATH, {})
    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = ensure_station_resources(stations_data[station_id])
    current = int(s["resources"][zone].get(item, 0))
    new_val = max(0, current - amount)
    s["resources"][zone][item] = new_val

    stations_data[station_id] = s
    save_json(STATIONS_PATH, stations_data)

    await interaction.response.send_message(f"✅ -{amount} **{item}** aus **{zone}** (neu: {new_val})", ephemeral=True)

@bot.tree.command(name="resource_show", description="Show resources of a station.")
@app_commands.describe(station_id="Station ID")
async def resource_show(interaction: discord.Interaction, station_id: str):
    station_id = station_id.lower().strip()
    stations_data = load_json(STATIONS_PATH, {})

    if station_id not in stations_data:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    s = ensure_station_resources(stations_data[station_id])
    res = s.get("resources", {})

    def fmt_zone(z: str) -> str:
        items = res.get(z, {})
        if not items:
            return f"**{z}**: (leer)\n"
        lines = [f"**{z}**:"]
        for k, v in sorted(items.items()):
            lines.append(f"- {k}: {v}")
        return "\n".join(lines) + "\n"

    msg = f"**Ressourcen – {s.get('name','?')}** (`{station_id}`)\n\n"
    for z in RESOURCE_ZONES:
        msg += fmt_zone(z) + "\n"

    await interaction.response.send_message(msg, ephemeral=True)

bot.run(TOKEN)
