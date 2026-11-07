"""Disk-backed Excel summaries for large prompt batches (no image buffering)."""
import re
from collections import Counter
from pathlib import Path

import xlsxwriter

from app.core.exceptions import BusinessError


def validate_folder_name(name):
    if (not isinstance(name, str) or not name or name != name.strip() or len(name) > 120
            or len(name.encode("utf-8")) > 240 or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.endswith((".", " "))
            or re.match(r"^(\.|\.\.|CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I)):
        raise BusinessError("文件夹名称不合法，不能包含路径、特殊字符或超过长度限制", code=40041)
    return name


class BatchExportReports:
    def __init__(self, directory, prompt_columns=1):
        self.counts = Counter()
        self.books = []
        self.prompt_columns = prompt_columns
        for filename in ("完整汇总.xlsx", "失败汇总.xlsx"):
            path = Path(directory) / filename
            book = xlsxwriter.Workbook(str(path), {"constant_memory": True, "tmpdir": directory,
                                                  "strings_to_formulas": False, "strings_to_urls": False})
            book.use_zip64()
            sheet = book.add_worksheet("提示词汇总")
            header = book.add_format({"bold": True, "bg_color": "#E8EEF4", "text_wrap": True})
            text = book.add_format({"text_wrap": True, "valign": "top"})
            sheet.freeze_panes(1, 0)
            sheet.set_column(0, 0, 9)
            sheet.set_column(1, 1, 26)
            sheet.set_column(2, 2, 32)
            sheet.set_column(3, 3, 12)
            sheet.set_column(4, 5, 45)
            sheet.set_column(6, 5 + prompt_columns, 90, text)
            sheet.write_row(0, 0, ["序号", "文件夹", "任务编号", "状态", "错误", "图片文件", "提示词"]
                            + [f"提示词（续 {i}）" for i in range(2, prompt_columns + 1)], header)
            self.books.append([book, sheet, path, 1])

    def append(self, index, item, folder, filename, status, error):
        self.counts[status] += 1
        # Excel limits cells to 32,767 characters. Preserve long prompts in
        # ordered continuation columns instead of silently truncating them.
        chunks = [item.prompt[i:i + 30000] for i in range(0, len(item.prompt), 30000)] or [""]
        row = [index, folder, item.task_no, status, error, filename, *chunks]
        for entry in self.books if status == "失败" else self.books[:1]:
            entry[1].write_row(entry[3], 0, row)
            entry[3] += 1

    def close(self):
        for book, sheet, _path, row in self.books:
            sheet.autofilter(0, 0, max(1, row - 1), 5 + self.prompt_columns)
            book.close()

    def write_to(self, archive):
        for _book, _sheet, path, _row in self.books:
            archive.write(path, path.name)
        succeeded, failed, pending = (self.counts[key] for key in ("成功", "失败", "未完成"))
        summary = f"全部成功 {succeeded} 张" if not failed and not pending else f"成功 {succeeded} 张，失败 {failed} 张"
        if pending:
            summary += f"，未完成 {pending} 张（本次下载快照）"
        archive.writestr("结果统计.txt", summary + "\n")
