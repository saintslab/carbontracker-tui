from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from textual.widgets import DataTable


Alignment = Literal["left", "center", "right"]
T = TypeVar("T")


@dataclass(frozen=True)
class TableColumn:
    label: str
    width: int | None = None
    alignment: Alignment = "left"


@dataclass(frozen=True)
class TableRow:
    cells: tuple[object, ...]
    key: str | None = None


@dataclass(frozen=True)
class TablePage(Generic[T]):
    items: tuple[T, ...]
    start_index: int
    end_index: int
    total_rows: int
    follow_tail: bool
    unseen_new_rows: int


class PagedRows(Generic[T]):
    def __init__(
        self,
        items: Sequence[T] | None = None,
        *,
        page_size: int = 100,
        follow_tail: bool = True,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.page_size = page_size
        self.follow_tail = follow_tail
        self.offset = 0
        self.unseen_new_rows = 0
        self.items: tuple[T, ...] = tuple()
        self.set_items(items or ())

    @property
    def total_rows(self) -> int:
        return len(self.items)

    @property
    def max_offset(self) -> int:
        return max(self.total_rows - self.page_size, 0)

    def set_items(self, items: Sequence[T]) -> None:
        previous_total = self.total_rows
        self.items = tuple(items)
        added = max(self.total_rows - previous_total, 0)
        if self.follow_tail:
            self.offset = self.max_offset
            self.unseen_new_rows = 0
        else:
            self.offset = min(self.offset, self.max_offset)
            self.unseen_new_rows += added

    def append_count(self, count: int) -> None:
        if count <= 0:
            return
        if self.follow_tail:
            self.offset = self.max_offset
            self.unseen_new_rows = 0
        else:
            self.unseen_new_rows += count

    def visible_items(self) -> TablePage[T]:
        end = min(self.offset + self.page_size, self.total_rows)
        start_index = self.offset + 1 if self.total_rows else 0
        return TablePage(
            items=self.items[self.offset : end],
            start_index=start_index,
            end_index=end,
            total_rows=self.total_rows,
            follow_tail=self.follow_tail,
            unseen_new_rows=self.unseen_new_rows,
        )

    def page_up(self) -> None:
        self.follow_tail = False
        self.offset = max(self.offset - self.page_size, 0)

    def page_down(self) -> None:
        self.offset = min(self.offset + self.page_size, self.max_offset)
        if self.offset == self.max_offset:
            self.follow_tail = True
            self.unseen_new_rows = 0

    def jump_start(self) -> None:
        self.follow_tail = False
        self.offset = 0

    def jump_end(self) -> None:
        self.follow_tail = True
        self.offset = self.max_offset
        self.unseen_new_rows = 0


def page_status(page: TablePage[object]) -> str:
    if page.total_rows == 0:
        return "0 rows"
    status = f"showing {page.start_index}-{page.end_index} of {page.total_rows}"
    if page.unseen_new_rows:
        status += f", {page.unseen_new_rows} new"
    return status


def render_table_page(
    table: DataTable,
    columns: Sequence[TableColumn],
    rows: Sequence[TableRow],
    *,
    empty_message: str = "waiting for data",
) -> None:
    table.clear(columns=True)
    table.cursor_type = "row"
    table.zebra_stripes = True
    for column in columns:
        if column.width is None:
            table.add_column(column.label)
        else:
            table.add_column(column.label, width=column.width)

    if not rows:
        table.add_row(empty_message, *("" for _ in columns[1:]))
        return

    for row in rows:
        if row.key is None:
            table.add_row(*row.cells)
        else:
            table.add_row(*row.cells, key=row.key)

