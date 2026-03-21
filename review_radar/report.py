"""报告保存 + 终端预览"""

import os
from datetime import datetime


def save_report(report: str, app_name: str, output_dir: str = "reports") -> str:
    """保存报告到 Markdown 文件，返回文件路径"""
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{app_name}-评论洞察-{date_str}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return filepath
