"""CLI 入口 + Rich 终端 UI"""

import argparse
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from review_radar.agent import ReviewRadarAgent
from review_radar.report import save_report

console = Console()

PHASE_ICONS = {
    "Phase 0: 识别 App": "🔍",
    "Phase 1: 抓取评论": "📥",
    "Phase 2: 分批分析": "🧠",
    "Phase 3: 评估质量": "✅",
    "Phase 4: 生成报告": "📝",
}


def make_event_handler():
    """创建事件回调函数"""
    state = {
        "start_time": time.time(),
        "tools_called": 0,
        "current_phase": "",
        "progress": None,
        "task_id": None,
    }

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    )
    state["progress"] = progress

    def on_event(event_type: str, data: dict):
        if event_type == "agent_start":
            console.print()
            console.print(Panel.fit(
                f"[bold white]AppPulse[/bold white]\n"
                f"[dim]感知每一条用户心声[/dim]\n\n"
                f"目标: [bold cyan]{data.get('app_name')}[/bold cyan]",
                border_style="blue",
                padding=(1, 3),
            ))
            console.print()

        elif event_type == "phase":
            phase = data.get("phase", "")
            state["current_phase"] = phase
            icon = PHASE_ICONS.get(phase, "▶")
            # 停止上一个 progress task
            if state["task_id"] is not None:
                progress.update(state["task_id"], description=f"[green]{state['current_phase']} ✓[/green]")
                progress.stop_task(state["task_id"])
            state["task_id"] = progress.add_task(f"{icon} {phase}", total=None)
            if not progress.live.is_started:
                progress.start()

        elif event_type == "tool_call":
            state["tools_called"] += 1
            summary = data.get("input_summary", "")
            if state["task_id"] is not None:
                icon = PHASE_ICONS.get(state["current_phase"], "▶")
                progress.update(state["task_id"], description=f"{icon} {state['current_phase']} — {summary}")

        elif event_type == "tool_result":
            pass  # progress spinner 已经在显示了

        elif event_type == "agent_done":
            # 停止最后一个 task
            if state["task_id"] is not None:
                progress.update(state["task_id"], description=f"[green]{state['current_phase']} ✓[/green]")
                progress.stop_task(state["task_id"])
            if progress.live.is_started:
                progress.stop()

            elapsed = time.time() - state["start_time"]
            tool_calls = data.get("tool_calls", state["tools_called"])

            console.print()
            console.print(Panel.fit(
                f"[bold green]分析完成[/bold green]\n\n"
                f"耗时 [bold]{elapsed:.0f}[/bold] 秒  |  "
                f"Tool 调用 [bold]{tool_calls}[/bold] 次",
                border_style="green",
                padding=(1, 3),
            ))

    return on_event, state


def show_report_preview(report: str):
    """在终端展示报告预览"""
    # 取前 40 行
    lines = report.strip().split("\n")[:40]
    preview = "\n".join(lines)
    if len(report.strip().split("\n")) > 40:
        preview += "\n\n..."

    console.print()
    console.print(Panel(
        Markdown(preview),
        title="[bold]报告预览[/bold]",
        border_style="blue",
        padding=(1, 2),
    ))


def main():
    import review_radar.config  # noqa: F401 — 确保 load_dotenv 被调用

    parser = argparse.ArgumentParser(
        description="AppPulse — 感知每一条用户心声",
    )
    parser.add_argument("app_name", help="App 名字，如'微信'、'飞书'、'Notion'")
    parser.add_argument("--count", type=int, default=100, help="每平台每国家的评论数量（默认 100）")
    parser.add_argument("--countries", default="us", help="国家/地区代码，逗号分隔（默认 us）。如 us,jp,cn")
    parser.add_argument("--platforms", default="app_store,google_play", help="平台，逗号分隔（默认 app_store,google_play）")
    parser.add_argument("--output", default="reports", help="报告输出目录（默认 reports）")

    args = parser.parse_args()

    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]

    on_event, state = make_event_handler()
    agent = ReviewRadarAgent(on_event=on_event)

    try:
        report = agent.run(
            app_name=args.app_name,
            platforms=platforms,
            countries=countries,
            count_per_platform=args.count,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        return
    except Exception as e:
        console.print(f"\n[bold red]错误:[/bold red] {e}")
        raise

    if report:
        filepath = save_report(report, args.app_name, args.output)
        console.print(f"\n报告已保存: [bold cyan]{filepath}[/bold cyan]")
        show_report_preview(report)
    else:
        console.print("[yellow]未生成报告[/yellow]")


if __name__ == "__main__":
    main()
