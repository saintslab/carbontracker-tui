from __future__ import annotations


ACCENT = "#5f9f6a"
ACCENT_DARK = "#2f6f44"


BASE_CSS = """
Screen {
    background: $surface;
    color: $text;
}

#body {
    height: 1fr;
    padding: 1 1 0 1;
}

#footer-line {
    height: 1;
    width: 100%;
    background: $boost;
}

#footer-left {
    width: 1fr;
    padding: 0 1;
    color: $text;
    text-style: bold;
    content-align: left middle;
}

#footer-right {
    width: 36;
    padding: 0 1;
    color: $text-muted;
    content-align: right middle;
}

.hidden {
    display: none;
}
"""


TABLE_CSS = """
DataTable {
    height: 1fr;
}

DataTable > .datatable--header {
    background: $surface;
    color: $text-muted;
    text-style: bold;
}

DataTable:focus > .datatable--header {
    background: #5f9f6a 60%;
}

DataTable > .datatable--odd-row {
    background: #5f9f6a 8%;
}

DataTable > .datatable--even-row {
    background: $surface;
}

DataTable > .datatable--cursor,
DataTable > .datatable--fixed-cursor,
DataTable > .datatable--header-cursor {
    background: #5f9f6a 25%;
    color: $text;
}

DataTable:focus > .datatable--cursor,
DataTable:focus > .datatable--fixed-cursor,
DataTable:focus > .datatable--header-cursor {
    background: #5f9f6a 70%;
    color: $text;
}

DataTable > .datatable--header-hover,
DataTable > .datatable--hover {
    background: #5f9f6a 25%;
}
"""

