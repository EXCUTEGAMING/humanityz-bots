# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Optional

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN") or os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

if not TOKEN:
    raise RuntimeError("TOKEN/DISCORD_TOKEN missing. Set Railway Variable TOKEN.")

TZ = ZoneInfo("Europe/Berlin")

OPEN_HOURS_TEXT = "Öffnungszeiten: Mo–Do 14:00–23:00 | Fr–So 12:00–01:00 (Europe/Berlin)"

def is_open_now(dt: datetime) -> bool:
    wd = dt.weekday()
    t = dt.time()
    if wd in (0, 1, 2, 3):
        return time(14, 0) <= t < time(23, 0)
    if wd in (4, 5, 6):
        return (t >= time(12, 0)) or (t < time(1, 0))
    return False

async def require_open(interaction: discord.Interaction) -> bool:
    if is_open_now(datetime.now(TZ)):
        return True
    await interaction.response.send_message(f"🔒 Server ist aktuell geschlossen.\n{OPEN_HOURS_TEXT}", ephemeral=True)
    return False

def is_staff(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator

intents = discord.Intents.none()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---- DB URL RESOLUTION ----
def resolve_database_url() -> Optional[str]:
    # 1) direct
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # 2) sometimes platforms expose PG* vars instead
    pghost = os.getenv("PGHOST") or os.getenv("POSTGRES_HOST")
    pgport = os.getenv("PGPORT") or os.getenv("POSTGRES_PORT")
    pguser = os.getenv("PGUSER") or os.getenv("POSTGRES_USER")
    pgpass = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
    pgdb = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB")

    if all([pghost, pgport, pguser, pgpass, pgdb]):
        return f"postgresql://{pguser}:{pgpass}@{pghost}:{pgport}/{pgdb}"

    return None

DATABASE_URL = resolve_database_url()

def log_env_presence():
    keys = [
        "DATABASE_URL",
        "PGHOST","PGPORT","PGUSER","PGPASSWORD","PGDATABASE",
        "POSTGRES_HOST","POSTGRES_PORT","POSTGRES_USER","POSTGRES_PASSWORD","POSTGRES_DB"
    ]
    status = {k: ("SET" if os.getenv(k) else "MISSING") for k in keys}
    print(f"[DB-ENV] {status}")

# ---- CONSTANTS (short for now, just boot) ----
DEFAULT_FACTIONS = {
    "LDF": {"name":"Livonian Defence Forces","side":"state","playable":True,"description":"Staat/Verteidiger."},
    "CMC": {"name":"Chernarus Mining Corporation","side":"invader","playable":True,"description":"Invasoren/Corporate."},
    "IND": {"name":"Unabhängige","side":"independent","playable":True,"description":"Weder Staat noch CMC."},
    "UN":  {"name":"United Nations","side":"neutral_team","playable":False,"description":"Team-Fraktion."},
}

pool: Optional[asyncpg.Pool] = None

async def db_init():
    global pool
    log_env_presence()

    if not DATABASE_URL:
        # Don't crash; keep bot alive so you can see /ping and logs
        print("[DB] DATABASE_URL missing. Set DATABASE_URL in the SERVICE Variables (not Project).")
        return

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async with pool.acquire() as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS factions (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            side TEXT NOT NULL,
            playable BOOLEAN NOT NULL,
            description TEXT NOT NULL
        );
        """)
        for k, v in DEFAULT_FACTIONS.items():
            await con.execute("""
            INSERT INTO factions(key,name,side,playable,description)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (key) DO UPDATE SET
              name=EXCLUDED.name, side=EXCLUDED.side, playable=EXCLUDED.playable, description=EXCLUDED.description;
            """, k, v["name"], v["side"], v["playable"], v["description"])

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

    print(f"[ONLINE] {bot.user} (ID: {bot.user.id})")

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

@bot.tree.command(name="db_status", description="Show whether DB is connected.")
async def db_status(interaction: discord.Interaction):
    ok = pool is not None
    await interaction.response.send_message(
        f"DB connected: **{ok}**\nDATABASE_URL present: **{bool(DATABASE_URL)}**",
        ephemeral=True
    )

bot.run(TOKEN)
