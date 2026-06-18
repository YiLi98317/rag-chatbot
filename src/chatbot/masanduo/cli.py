#!/usr/bin/env python3
"""马三多挂件 CLI：交互式聊天循环。

运行：python -m chatbot.masanduo.cli
"""

from __future__ import annotations

import uuid

import typer
from rich import print as rprint

from chatbot.config import get_settings
from chatbot.masanduo.engine import respond

app = typer.Typer(add_completion=False)


@app.command()
def run(
    surname: str = typer.Option("", "--surname", help="老板姓氏，用于称呼如「王老板」"),
    session_id: str = typer.Option("", "--session", help="会话 id，默认随机生成"),
) -> None:
    """启动马三多交互聊天。输入问题回车；输入 quit/exit 退出。"""
    settings = get_settings()
    sid = session_id or f"cli-{uuid.uuid4().hex[:8]}"

    rprint("[bold]马三多上线啦[/bold] —— 手机妈妈平台 AI 商务")
    rprint(f"[dim]session={sid} model={getattr(settings, 'model_name', '')} provider={getattr(settings, 'llm_provider', '')}[/dim]")
    rprint("输入问题按 [bold]回车[/bold]，输入 [bold]quit[/bold] 退出。")

    while True:
        try:
            msg = input("老板> ").strip()
        except (EOFError, KeyboardInterrupt):
            rprint("\n[dim]马三多下班了～[/dim]")
            break
        if not msg or msg.lower() in {"q", "quit", "exit"}:
            rprint("[dim]马三多下班了～[/dim]")
            break
        try:
            reply = respond(msg, session_id=sid, surname=surname, settings=settings)
            rprint(f"[bold green]马三多>[/bold green] {reply}")
        except Exception as e:  # noqa: BLE001
            import traceback

            rprint(f"[red]出错了:[/red] {e}")
            rprint("[dim]" + traceback.format_exc() + "[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
