"""
Discord bot — dispatches natural-language intents to HermesMaster + task_runner.

Requires: DISCORD_BOT_TOKEN, optional DISCORD_ALLOWED_CHANNEL_ID / DISCORD_ALLOWED_USER_IDS
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

try:
    import discord
    from discord.ext import commands
except ImportError:
    print("Install discord.py: pip install discord.py")
    raise

from master_brain import HermesMaster

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_RUNNER = Path(__file__).resolve().parent / "task_runner.py"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
hermes = HermesMaster()


def _allowed(message: discord.Message) -> bool:
    channel_id = os.environ.get("DISCORD_ALLOWED_CHANNEL_ID", "").strip()
    if channel_id and str(message.channel.id) != channel_id:
        return False
    users = os.environ.get("DISCORD_ALLOWED_USER_IDS", "").strip()
    if users:
        allowed = {u.strip() for u in users.split(",") if u.strip()}
        if str(message.author.id) not in allowed:
            return False
    return True


def _run_task_runner() -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(TASK_RUNNER)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


@bot.event
async def on_ready() -> None:
    print(f"[discord_bot] Logged in as {bot.user}")


@bot.command(name="vanmap")
async def vanmap_cmd(ctx: commands.Context, *, intent: str) -> None:
    if not _allowed(ctx.message):
        return
    await ctx.send(f"Hermes 收到指令：`{intent}`")
    hermes.plan_and_dispatch(intent)
    code, out = await asyncio.to_thread(_run_task_runner)
    if code == 0:
        await ctx.send("任务完成 — 查看 `order_box/task.json` 状态 DONE")
    else:
        await ctx.send(f"任务失败 (exit {code})\n```\n{out[-1500:]}\n```")


@bot.command(name="refresh_events")
async def refresh_events(ctx: commands.Context) -> None:
    if not _allowed(ctx.message):
        return
    hermes.plan_and_dispatch("更新大温活动数据")
    code, out = await asyncio.to_thread(_run_task_runner)
    await ctx.send("✅ 活动已更新" if code == 0 else f"❌ 失败:\n{out[-800:]}")


def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("[discord_bot] Set DISCORD_BOT_TOKEN in environment")
        raise SystemExit(1)
    bot.run(token)


if __name__ == "__main__":
    main()
