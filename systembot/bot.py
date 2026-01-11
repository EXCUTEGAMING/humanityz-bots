# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime, time
from zoneinfo import ZoneInfo

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ---- ENV ----
TOKEN = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise RuntimeError("TOKEN/DISCORD_TOKEN missing. Set Railway Variable TOKEN.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL missing. Add Railway PostgreSQL and ensure this service has DATABASE_URL.")

TZ = ZoneInfo("Europe/Berlin")

# ---- OPEN HOURS (Standard) ----
OPEN_HOURS_TEXT = "Öffnungszeiten: Mo–Do 14:00–23:00 | Fr–So 12:00–01:00 (Europe/Berlin)"

def is_open_now(dt: datetime) -> bool:
    weekday = dt.weekday()  # Mon=0 ... Sun=6
    t = dt.time()

    # Mo–Do: 14:00–23:00
    if weekday in (0, 1, 2, 3):
        return time(14, 0) <= t < time(23, 0)

    # Fr–So: 12:00–01:00 (über Mitternacht)
    if weekday in (4, 5, 6):
        return (t >= time(12, 0)) or (t < time(1, 0))

    return False

async def require_open(interaction: discord.Interaction) -> bool:
    now = datetime.now(TZ)
    if is_open_now(now):
        return True
    await interaction.response.send_message(
        f"🔒 Server ist aktuell geschlossen.\n{OPEN_HOURS_TEXT}",
        ephemeral=True
    )
    return False

def is_staff(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator

# ---- DISCORD BOT ----
intents = discord.Intents.none()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---- CONSTANTS ----
STATION_TYPES = {
    "CAMP": {"min_players": 1, "notes": "Camp (mind. 1 Spieler)"},
    "DORF": {"min_players": 4, "notes": "Dorf (mind. 4 Spieler)"},
    "SIEDLUNG": {"min_players": 10, "notes": "Siedlung (10 Spieler oder 8 Spieler-Fraktion)"},
    "AUSSENPOSTEN": {"min_players": 5, "notes": "Außenposten (mind. 5 Spieler-Fraktion)"},
    "STRATEGISCH": {"min_players": 5, "notes": "Strategischer Punkt (Capture + 48h Schutz)"},
}
RESOURCE_ZONES = ["lager", "verarbeitung", "bauhaus", "produktion"]

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

# ---- DB ----
pool: asyncpg.Pool | None = None

async def db_init():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async with pool.acquire() as con:
        # tables
        await con.execute("""
        CREATE TABLE IF NOT EXISTS factions (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            side TEXT NOT NULL,
            playable BOOLEAN NOT NULL,
            description TEXT NOT NULL
        );
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            faction_key TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            station_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            owner_faction TEXT NOT NULL,
            condition INT NOT NULL DEFAULT 100,
            protection_hours INT NOT NULL DEFAULT 0,
            resources JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        await con.execute("""
        CREATE TABLE IF NOT EXISTS station_members (
            station_id TEXT NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL,
            PRIMARY KEY (station_id, user_id)
        );
        """)

        # seed factions (upsert)
        for k, v in DEFAULT_FACTIONS.items():
            await con.execute("""
            INSERT INTO factions(key, name, side, playable, description)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (key) DO UPDATE SET
              name=EXCLUDED.name,
              side=EXCLUDED.side,
              playable=EXCLUDED.playable,
              description=EXCLUDED.description;
            """, k, v["name"], v["side"], v["playable"], v["description"])

async def fetch_factions():
    assert pool
    async with pool.acquire() as con:
        rows = await con.fetch("SELECT key,name,side,playable,description FROM factions ORDER BY key;")
        return rows

async def get_player(user_id: str):
    assert pool
    async with pool.acquire() as con:
        return await con.fetchrow("SELECT user_id,name,faction_key FROM players WHERE user_id=$1;", user_id)

async def set_player_faction(user_id: str, name: str, faction_key: str):
    assert pool
    async with pool.acquire() as con:
        await con.execute("""
        INSERT INTO players(user_id, name, faction_key, updated_at)
        VALUES ($1,$2,$3,NOW())
        ON CONFLICT (user_id) DO UPDATE SET
          name=EXCLUDED.name,
          faction_key=EXCLUDED.faction_key,
          updated_at=NOW();
        """, user_id, name, faction_key)

async def station_exists(station_id: str) -> bool:
    assert pool
    async with pool.acquire() as con:
        row = await con.fetchrow("SELECT station_id FROM stations WHERE station_id=$1;", station_id)
        return row is not None

def default_resources():
    return {z: {} for z in RESOURCE_ZONES}

async def create_station_db(station_id: str, name: str, stype: str, owner: str, protection: int):
    assert pool
    async with pool.acquire() as con:
        await con.execute("""
        INSERT INTO stations(station_id, name, type, owner_faction, condition, protection_hours, resources)
        VALUES ($1,$2,$3,$4,100,$5,$6::jsonb)
        """, station_id, name, stype, owner, protection, json.dumps(default_resources()))

async def list_stations_db():
    assert pool
    async with pool.acquire() as con:
        return await con.fetch("""
        SELECT s.station_id, s.name, s.type, s.owner_faction,
               (SELECT COUNT(*) FROM station_members m WHERE m.station_id=s.station_id) AS members_count
        FROM stations s
        ORDER BY s.station_id;
        """)

async def get_station_db(station_id: str):
    assert pool
    async with pool.acquire() as con:
        row = await con.fetchrow("""
        SELECT station_id,name,type,owner_faction,condition,protection_hours,resources
        FROM stations WHERE station_id=$1;
        """, station_id)
        return row

async def list_station_members_db(station_id: str):
    assert pool
    async with pool.acquire() as con:
        rows = await con.fetch("SELECT user_id FROM station_members WHERE station_id=$1 ORDER BY user_id;", station_id)
        return [r["user_id"] for r in rows]

async def add_station_member_db(station_id: str, user_id: str):
    assert pool
    async with pool.acquire() as con:
        await con.execute("""
        INSERT INTO station_members(station_id, user_id)
        VALUES ($1,$2)
        ON CONFLICT DO NOTHING;
        """, station_id, user_id)

async def remove_station_member_db(station_id: str, user_id: str):
    assert pool
    async with pool.acquire() as con:
        await con.execute("DELETE FROM station_members WHERE station_id=$1 AND user_id=$2;", station_id, user_id)

async def update_station_type_db(station_id: str, stype: str):
    assert pool
    async with pool.acquire() as con:
        await con.execute("UPDATE stations SET type=$2 WHERE station_id=$1;", station_id, stype)

async def update_station_condition_db(station_id: str, condition: int):
    assert pool
    async with pool.acquire() as con:
        await con.execute("UPDATE stations SET condition=$2 WHERE station_id=$1;", station_id, condition)

async def update_station_protection_db(station_id: str, hours: int):
    assert pool
    async with pool.acquire() as con:
        await con.execute("UPDATE stations SET protection_hours=$2 WHERE station_id=$1;", station_id, hours)

async def get_resources_db(station_id: str) -> dict:
    assert pool
    async with pool.acquire() as con:
        row = await con.fetchrow("SELECT resources FROM stations WHERE station_id=$1;", station_id)
        return dict(row["resources"]) if row else default_resources()

async def set_resources_db(station_id: str, resources: dict):
    assert pool
    async with pool.acquire() as con:
        await con.execute("UPDATE stations SET resources=$2::jsonb WHERE station_id=$1;", station_id, json.dumps(resources))

# ---- EVENTS ----
@bot.event
async def on_ready():
    await db_init()

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

# ---- COMMANDS ----
@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong ✅ (SYSTEMBOT)", ephemeral=True)

@bot.tree.command(name="factions", description="List all available factions.")
async def factions(interaction: discord.Interaction):
    if not await require_open(interaction):
        return

    rows = await fetch_factions()
    msg = "**Verfügbare Fraktionen:**\n"
    for r in rows:
        status = "spielbar" if r["playable"] else "nicht spielbar"
        msg += f"- **{r['key']}** – {r['name']} ({status})\n"
        if r["description"]:
            msg += f"  _{r['description']}_\n"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="join_faction", description="Join a playable faction.")
@app_commands.describe(faction="LDF / CMC / IND")
async def join_faction(interaction: discord.Interaction, faction: str):
    if not await require_open(interaction):
        return

    faction = faction.upper().strip()
    rows = await fetch_factions()
    factions_map = {r["key"]: r for r in rows}

    if faction not in factions_map:
        await interaction.response.send_message("❌ Diese Fraktion existiert nicht.", ephemeral=True)
        return
    if not factions_map[faction]["playable"]:
        await interaction.response.send_message("❌ Diese Fraktion ist nicht spielbar.", ephemeral=True)
        return

    await set_player_faction(str(interaction.user.id), interaction.user.name, faction)
    await interaction.response.send_message(f"✅ Du bist jetzt Teil der Fraktion **{faction}**.", ephemeral=True)

@bot.tree.command(name="whoami", description="Show your faction.")
async def whoami(interaction: discord.Interaction):
    if not await require_open(interaction):
        return

    row = await get_player(str(interaction.user.id))
    if not row:
        await interaction.response.send_message(
            "Du bist noch keiner Fraktion zugewiesen. Nutze `/join_faction` oder frag die Fraktionsführung/Staff.",
            ephemeral=True
        )
        return
    await interaction.response.send_message(f"✅ Du bist in der Fraktion: **{row['faction_key']}**", ephemeral=True)

@bot.tree.command(name="stations", description="List all stations (ID, name, type, owner).")
async def stations(interaction: discord.Interaction):
    if not await require_open(interaction):
        return

    rows = await list_stations_db()
    if not rows:
        await interaction.response.send_message("ℹ️ Es gibt aktuell keine Stationen.", ephemeral=True)
        return

    lines = ["**Alle Stationen:**"]
    for r in rows:
        lines.append(f"- `{r['station_id']}` | **{r['name']}** | {r['type']} | {r['owner_faction']} | Mitglieder: {r['members_count']}")
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
    if not await require_open(interaction):
        return
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
        await interaction.response.send_message(f"❌ Mindestspieler nicht erreicht: {station_type} braucht mind. {min_p}.", ephemeral=True)
        return

    if await station_exists(station_id):
        await interaction.response.send_message("❌ Station-ID existiert bereits.", ephemeral=True)
        return

    protection = 48 if station_type == "STRATEGISCH" else 0
    await create_station_db(station_id, name, station_type, owner_faction, protection)

    await interaction.response.send_message(
        f"✅ Station erstellt: **{name}** ({station_type}) für **{owner_faction}**\nID: `{station_id}`\nSchutz: {protection}h",
        ephemeral=True
    )

@bot.tree.command(name="station_info", description="Show station info by station_id.")
@app_commands.describe(station_id="Station ID (e.g. nadbor_camp_01)")
async def station_info(interaction: discord.Interaction, station_id: str):
    if not await require_open(interaction):
        return

    station_id = station_id.lower().strip()
    row = await get_station_db(station_id)
    if not row:
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    members = await list_station_members_db(station_id)
    msg = (
        f"**Station:** {row['name']}\n"
        f"**ID:** `{row['station_id']}`\n"
        f"**Typ:** {row['type']} ({STATION_TYPES.get(row['type'],{}).get('notes','')})\n"
        f"**Besitzer:** {row['owner_faction']}\n"
        f"**Mitglieder:** {len(members)}\n"
        f"**Zustand:** {row['condition']}/100\n"
        f"**Schutzzeit:** {row['protection_hours']}h\n"
    )
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="station_members", description="List members of a station.")
@app_commands.describe(station_id="Station ID")
async def station_members(interaction: discord.Interaction, station_id: str):
    if not await require_open(interaction):
        return

    station_id = station_id.lower().strip()
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    members = await list_station_members_db(station_id)
    if not members:
        await interaction.response.send_message("ℹ️ Station hat noch keine Mitglieder.", ephemeral=True)
        return

    lines = []
    for uid in members:
        m = interaction.guild.get_member(int(uid)) if interaction.guild else None
        lines.append(f"- {m.mention} ({m.name})" if m else f"- <@{uid}>")

    await interaction.response.send_message("\n".join([f"**Mitglieder** (`{station_id}`):"] + lines), ephemeral=True)

@bot.tree.command(name="station_add_member", description="(Staff) Add a member to a station.")
@app_commands.describe(user="User to add", station_id="Station ID")
async def station_add_member(interaction: discord.Interaction, user: discord.Member, station_id: str):
    if not await require_open(interaction):
        return
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    await add_station_member_db(station_id, str(user.id))
    await interaction.response.send_message(f"✅ {user.mention} hinzugefügt.", ephemeral=True)

@bot.tree.command(name="station_remove_member", description="(Staff) Remove a member from a station.")
@app_commands.describe(user="User to remove", station_id="Station ID")
async def station_remove_member(interaction: discord.Interaction, user: discord.Member, station_id: str):
    if not await require_open(interaction):
        return
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    await remove_station_member_db(station_id, str(user.id))
    await interaction.response.send_message(f"✅ {user.mention} entfernt.", ephemeral=True)

@bot.tree.command(name="station_set_type", description="(Staff) Change station type.")
@app_commands.describe(station_id="Station ID", station_type="CAMP/DORF/SIEDLUNG/AUSSENPOSTEN/STRATEGISCH")
async def station_set_type(interaction: discord.Interaction, station_id: str, station_type: str):
    if not await require_open(interaction):
        return
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    station_type = station_type.upper().strip()
    if station_type not in STATION_TYPES:
        await interaction.response.send_message("❌ Ungültiger Stationstyp.", ephemeral=True)
        return
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    await update_station_type_db(station_id, station_type)

    # auto: strategisch -> 48h, nur wenn aktuell 0
    row = await get_station_db(station_id)
    if row and station_type == "STRATEGISCH" and int(row["protection_hours"]) == 0:
        await update_station_protection_db(station_id, 48)

    await interaction.response.send_message(f"✅ Typ gesetzt: `{station_id}` → **{station_type}**", ephemeral=True)

@bot.tree.command(name="station_set_condition", description="(Staff) Set station condition (0-100).")
@app_commands.describe(station_id="Station ID", condition="0-100")
async def station_set_condition(interaction: discord.Interaction, station_id: str, condition: int):
    if not await require_open(interaction):
        return
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    condition = max(0, min(100, int(condition)))
    await update_station_condition_db(station_id, condition)
    await interaction.response.send_message(f"✅ Zustand gesetzt: `{station_id}` → **{condition}/100**", ephemeral=True)

@bot.tree.command(name="station_set_protection", description="(Staff) Set station protection hours.")
@app_commands.describe(station_id="Station ID", hours="Protection hours (e.g. 48)")
async def station_set_protection(interaction: discord.Interaction, station_id: str, hours: int):
    if not await require_open(interaction):
        return
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    hours = max(0, int(hours))
    await update_station_protection_db(station_id, hours)
    await interaction.response.send_message(f"✅ Schutzzeit gesetzt: `{station_id}` → **{hours}h**", ephemeral=True)

@bot.tree.command(name="resource_show", description="Show resources of a station.")
@app_commands.describe(station_id="Station ID")
async def resource_show(interaction: discord.Interaction, station_id: str):
    if not await require_open(interaction):
        return

    station_id = station_id.lower().strip()
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    res = await get_resources_db(station_id)

    def fmt_zone(z: str) -> str:
        items = res.get(z, {})
        if not items:
            return f"**{z}**: (leer)\n"
        lines = [f"**{z}**:"]
        for k, v in sorted(items.items()):
            lines.append(f"- {k}: {v}")
        return "\n".join(lines) + "\n"

    msg = f"**Ressourcen** (`{station_id}`)\n\n"
    for z in RESOURCE_ZONES:
        msg += fmt_zone(z) + "\n"

    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="resource_add", description="(Staff) Add resources to a station zone.")
@app_commands.describe(station_id="Station ID", zone="lager/verarbeitung/bauhaus/produktion", item="Item key", amount="Amount")
async def resource_add(interaction: discord.Interaction, station_id: str, zone: str, item: str, amount: int):
    if not await require_open(interaction):
        return
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    zone = zone.lower().strip()
    item = item.lower().strip()
    amount = max(0, int(amount))

    if zone not in RESOURCE_ZONES:
        await interaction.response.send_message("❌ Ungültige Zone.", ephemeral=True)
        return
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    res = await get_resources_db(station_id)
    if zone not in res:
        res[zone] = {}
    current = int(res[zone].get(item, 0))
    res[zone][item] = current + amount
    await set_resources_db(station_id, res)

    await interaction.response.send_message(f"✅ +{amount} **{item}** in **{zone}** (neu: {current + amount})", ephemeral=True)

@bot.tree.command(name="resource_take", description="(Staff) Take resources from a station zone.")
@app_commands.describe(station_id="Station ID", zone="lager/verarbeitung/bauhaus/produktion", item="Item key", amount="Amount")
async def resource_take(interaction: discord.Interaction, station_id: str, zone: str, item: str, amount: int):
    if not await require_open(interaction):
        return
    if not is_staff(interaction):
        await interaction.response.send_message("❌ Nur Staff.", ephemeral=True)
        return

    station_id = station_id.lower().strip()
    zone = zone.lower().strip()
    item = item.lower().strip()
    amount = max(0, int(amount))

    if zone not in RESOURCE_ZONES:
        await interaction.response.send_message("❌ Ungültige Zone.", ephemeral=True)
        return
    if not await station_exists(station_id):
        await interaction.response.send_message("❌ Station nicht gefunden.", ephemeral=True)
        return

    res = await get_resources_db(station_id)
    if zone not in res:
        res[zone] = {}
    current = int(res[zone].get(item, 0))
    res[zone][item] = max(0, current - amount)
    await set_resources_db(station_id, res)

    await interaction.response.send_message(f"✅ -{amount} **{item}** aus **{zone}** (neu: {res[zone][item]})", ephemeral=True)

bot.run(TOKEN)
