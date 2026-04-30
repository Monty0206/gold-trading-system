"""
TRADE MONITOR — Home PC dashboard (run separately from executor)
Shows live open positions, today's trade history, and account status.
Uses Rich for a clean terminal display. Refreshes every 5 seconds.
"""

import os
import time
from datetime import datetime, timezone, date

import MetaTrader5 as mt5
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.columns import Columns
from rich import box
from supabase import create_client

load_dotenv()

console = Console()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)


def connect_mt5() -> bool:
    if not mt5.initialize():
        return False
    login = int(os.getenv("MT5_LOGIN", "0"))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "Deriv-Server")
    return mt5.login(login, password=password, server=server)


def build_account_panel() -> Panel:
    info = mt5.account_info()
    if not info:
        return Panel("[red]MT5 not connected[/red]", title="Account")
    balance = info.balance
    equity = info.equity
    margin_free = info.margin_free
    profit = equity - balance
    profit_str = f"[green]+${profit:.2f}[/green]" if profit >= 0 else f"[red]-${abs(profit):.2f}[/red]"

    text = (
        f"[bold]{info.name}[/bold]  |  Server: {info.server}\n"
        f"Balance:  [cyan]${balance:.2f}[/cyan]   "
        f"Equity: [cyan]${equity:.2f}[/cyan]   "
        f"Float P&L: {profit_str}\n"
        f"Free Margin: ${margin_free:.2f}"
    )
    return Panel(text, title="[bold yellow]Account Status[/bold yellow]", box=box.ROUNDED)


def build_positions_table() -> Table:
    table = Table(
        title="Open Positions",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
    )
    table.add_column("Ticket", style="cyan")
    table.add_column("Symbol")
    table.add_column("Type")
    table.add_column("Lots")
    table.add_column("Entry")
    table.add_column("Current")
    table.add_column("SL")
    table.add_column("TP")
    table.add_column("P&L", justify="right")
    table.add_column("Opened")

    positions = mt5.positions_get(symbol="XAUUSD") or []
    if not positions:
        table.add_row("[dim]No open positions[/dim]", *[""] * 9)
        return table

    for pos in positions:
        pnl = pos.profit
        pnl_str = f"[green]+${pnl:.2f}[/green]" if pnl >= 0 else f"[red]-${abs(pnl):.2f}[/red]"
        direction = "[green]BUY[/green]" if pos.type == mt5.ORDER_TYPE_BUY else "[red]SELL[/red]"
        opened = datetime.fromtimestamp(pos.time, tz=timezone.utc).strftime("%H:%M")
        table.add_row(
            str(pos.ticket),
            pos.symbol,
            direction,
            str(pos.volume),
            f"{pos.price_open:.2f}",
            f"{pos.price_current:.2f}",
            f"{pos.sl:.2f}",
            f"{pos.tp:.2f}",
            pnl_str,
            opened,
        )
    return table


def build_history_table() -> Table:
    table = Table(
        title="Today's Signals (Supabase)",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
    )
    table.add_column("Time (UTC)", style="dim")
    table.add_column("Session")
    table.add_column("Decision")
    table.add_column("Entry")
    table.add_column("Executed")
    table.add_column("Ticket")
    table.add_column("Outcome")

    try:
        today_str = date.today().isoformat()
        rows = (
            supabase.table("trade_signals")
            .select("*, trade_outcomes(*)")
            .gte("created_at", f"{today_str}T00:00:00")
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        for r in rows.data:
            created = r.get("created_at", "")[:16].replace("T", " ")
            decision = r.get("decision", "")
            dec_colour = (
                "green" if "EXECUTE" in decision
                else "yellow" if decision == "WAIT"
                else "red"
            )
            outcome_row = r.get("trade_outcomes") or []
            outcome = outcome_row[0].get("outcome", "RUNNING") if outcome_row else ("RUNNING" if r.get("executed") else "—")
            out_colour = "green" if outcome == "WIN" else "red" if outcome == "LOSS" else "dim"

            table.add_row(
                created,
                r.get("session", ""),
                f"[{dec_colour}]{decision}[/{dec_colour}]",
                str(r.get("entry_price") or "—"),
                "[green]YES[/green]" if r.get("executed") else "[dim]NO[/dim]",
                str(r.get("mt5_ticket") or "—"),
                f"[{out_colour}]{outcome}[/{out_colour}]",
            )
    except Exception as e:
        table.add_row(f"[red]Supabase error: {e}[/red]", *[""] * 6)

    return table


def render_dashboard():
    account_panel = build_account_panel()
    positions_table = build_positions_table()
    history_table = build_history_table()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return Panel(
        f"{account_panel}\n\n{positions_table}\n\n{history_table}",
        title=f"[bold yellow]GOLD SESSION SNIPER — Monitor[/bold yellow]  [dim]{now_str}[/dim]",
        box=box.HEAVY,
    )


def main():
    if not connect_mt5():
        console.print("[red]Failed to connect to MT5. Check credentials.[/red]")
        return

    console.print("[green]Connected to MT5. Starting monitor (Ctrl+C to exit)...[/green]")

    with Live(console=console, refresh_per_second=0.2) as live:
        while True:
            try:
                live.update(render_dashboard())
                time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[yellow]Monitor error: {e}[/yellow]")
                time.sleep(5)

    mt5.shutdown()
    console.print("[dim]Monitor stopped.[/dim]")


if __name__ == "__main__":
    main()
