"""theory_y.cli — the `theory-y` command-line client."""

from __future__ import annotations

import sys

import click

from . import config
from .client import Client, TheoryYError


def _client(ctx: click.Context) -> Client:
    return Client(base_url=ctx.obj.get("url"), api_key=ctx.obj.get("key"))


@click.group()
@click.option("--url", default=None, help="API base URL (overrides config/env).")
@click.option("--key", default=None, help="API key or license token (overrides config/env).")
@click.pass_context
def main(ctx: click.Context, url: str | None, key: str | None) -> None:
    """TheoryY Research — generate institutional equity memos via the API."""
    ctx.obj = {"url": url, "key": key}


@main.command()
@click.option("--url", prompt=True, help="API base URL.")
@click.option("--key", default=None, help="API key or license token.")
def auth(url: str, key: str | None) -> None:
    """Save the API URL + credential to ~/.theory-y/config.json."""
    path = config.save(url, key)
    click.echo(f"Saved credentials to {path}")


@main.command()
@click.pass_context
def tickers(ctx: click.Context) -> None:
    """List the supported ticker universe."""
    data = _run(_client(ctx).tickers)
    for t in data["sector_tickers"]:
        peers = ", ".join(data["competitor_map"].get(t, []))
        click.echo(f"{t:6} {peers}")


@main.command()
@click.argument("tickers", nargs=-1)
@click.option("--out", "-o", default=None, help="Write CSV to this path instead of stdout.")
@click.pass_context
def sector(ctx: click.Context, tickers: tuple[str, ...], out: str | None) -> None:
    """Generate the valuation comparables CSV for TICKERS."""
    csv_text = _run(lambda: _client(ctx).sector(list(tickers)))
    if out:
        with open(out, "w") as f:
            f.write(csv_text)
        click.echo(f"Wrote {out}")
    else:
        click.echo(csv_text)


@main.command()
@click.argument("ticker")
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "pdf", "docx"]), default="pdf")
@click.option("--out", "-o", default=None, help="Output file path.")
@click.option("--wait/--no-wait", default=True, help="Wait for completion and download.")
@click.pass_context
def memo(ctx: click.Context, ticker: str, fmt: str, out: str | None, wait: bool) -> None:
    """Generate an investment memo for TICKER."""
    client = _client(ctx)
    if not wait:
        job = _run(lambda: client.create_memo(ticker, fmt))
        click.echo(f"Submitted job {job['job_id']} (status: {job['status']})")
        return
    click.echo(f"Generating {fmt} memo for {ticker.upper()} ...")
    path = _run(lambda: client.generate(ticker, fmt, out))
    click.echo(f"Saved {path}")


@main.command()
@click.argument("job_id")
@click.pass_context
def status(ctx: click.Context, job_id: str) -> None:
    """Check the status of a memo job."""
    s = _run(lambda: _client(ctx).memo_status(job_id))
    click.echo(f"{s['status']}  {s['progress']}%  formats={s['formats']}  {s.get('error') or ''}")


@main.command()
@click.option("--limit", default=20, help="Max jobs to show.")
@click.pass_context
def history(ctx: click.Context, limit: int) -> None:
    """List recent memo jobs."""
    jobs = _run(lambda: _client(ctx).list_memos(limit))
    if not jobs:
        click.echo("No memos yet.")
        return
    for j in jobs:
        click.echo(f"{j['job_id']}  {j['status']:10}  {j['progress']:3}%  {','.join(j['formats'])}")


@main.command()
@click.argument("job_id")
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "pdf", "docx"]), default="pdf")
@click.option("--out", "-o", default=None, help="Output file path.")
@click.pass_context
def download(ctx: click.Context, job_id: str, fmt: str, out: str | None) -> None:
    """Download a completed memo."""
    path = _run(lambda: _client(ctx).download(job_id, fmt, out or f"memo.{fmt}"))
    click.echo(f"Saved {path}")


# ── account (SaaS mode) ──────────────────────────────────────────────────────
@main.command()
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True)
@click.pass_context
def login(ctx: click.Context, email: str, password: str) -> None:
    """Log in (SaaS) and save the session token as your credential."""
    client = _client(ctx)
    token = _run(lambda: client.login(email, password))
    config.save(client.base_url, token)
    click.echo("Logged in. Token saved.")


@main.command(name="create-key")
@click.option("--name", default="default")
@click.pass_context
def create_key(ctx: click.Context, name: str) -> None:
    """Create an API key (SaaS). Shown once — save it."""
    info = _run(lambda: _client(ctx).create_api_key(name))
    click.echo(f"API key ({info['name']}): {info['api_key']}")


@main.command()
@click.pass_context
def usage(ctx: click.Context) -> None:
    """Show plan and usage this billing period (SaaS)."""
    u = _run(lambda: _client(ctx).usage())
    quota = "unlimited" if u["quota"] is None else u["quota"]
    click.echo(f"Plan: {u['plan']}  |  {u['used']}/{quota} memos in {u['billing_period']}")


def _run(fn):
    try:
        return fn()
    except TheoryYError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
