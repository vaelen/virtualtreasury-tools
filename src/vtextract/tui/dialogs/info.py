# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.index_client import IndexClient


def _fmt_range(begin: str | None, end: str | None) -> str:
    """Render a date range: ``-`` when absent, the single value when begin==end."""
    if not begin and not end:
        return "-"
    if begin == end:
        return begin or "-"
    return f"{begin or '?'} – {end or '?'}"


class _InfoBase(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "close")]

    def compose(self):
        with Vertical(id="info-dialog"):
            yield Static(self._title(), id="info-title")
            yield Static("Loading…", id="info-body")
            yield Button("Close", id="close")

    async def on_mount(self) -> None:
        body = await self._body()
        self.query_one("#info-body", Static).update(body)

    def _title(self) -> str: ...
    async def _body(self) -> str: ...

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss(None)


class PageInfoDialog(_InfoBase):
    def __init__(self, *, index: IndexClient, reader: ArchiveReader,
                 bundle: Bundle, root_id: str, page_key: str) -> None:
        super().__init__()
        self.index = index
        self.reader = reader
        self.bundle = bundle
        self.root_id = root_id
        self.page_key = page_key

    def _title(self) -> str:
        return "Page info"

    async def _body(self) -> str:
        vol = self.reader.read_volume_meta(self.root_id) or {}
        ref = PageRef(self.root_id, self.page_key)
        state = self.bundle.page_state.get(ref, "default")
        contributing = [iid for iid, refs in self.bundle.selected_items.items()
                        if ref in refs]
        page_dir = self.reader.archive / "pages" / self.root_id
        image = (page_dir / self.page_key
                 if self.reader.image_exists(self.root_id, self.page_key)
                 else None)
        files = [
            ("image", image),
            ("text", page_dir / f"{self.page_key}.txt"),
            ("meta", page_dir / f"{self.page_key}.json"),
        ]
        # Show paths relative to the archive root so the dialog stays portable
        # (and snapshot tests stay deterministic across tmp dirs).
        archive_root = self.reader.archive
        lines = [
            f"Volume       {self.root_id} — {vol.get('title') or ''}",
            f"Page         {self.page_key}",
            f"In bundle    {'yes' if self.bundle.is_in_bundle(ref) else 'no'}",
            f"User state   {state}",
            "",
            "Contributing items",
        ]
        for iid in contributing:
            item = await self.index.item(iid)
            title = item.title if item else ""
            lines.append(f"  {iid}  {title or ''}")
        lines += ["", f"Files on disk (under {archive_root.name}/)"]
        for label, path in files:
            if path is None:
                lines.append(f"  {label:5s}  (missing)")
            else:
                rel = path.relative_to(archive_root)
                lines.append(f"  {label:5s}  {rel}")
        return "\n".join(lines)


class VolumeInfoDialog(_InfoBase):
    def __init__(self, *, index: IndexClient, bundle: Bundle, root_id: str) -> None:
        super().__init__()
        self.index = index
        self.bundle = bundle
        self.root_id = root_id

    def _title(self) -> str:
        return "Volume info"

    async def _body(self) -> str:
        vols = {v.root_id: v for v in await self.index.volumes()}
        v = vols.get(self.root_id)
        pages = await self.index.pages(self.root_id)
        in_bundle = sum(1 for p in self.bundle.effective_pages()
                        if p.root_id == self.root_id)
        return "\n".join([
            f"Root ID      {self.root_id}",
            f"Title        {(v.title if v else None) or '-'}",
            f"Reference    {(v.reference_code if v else None) or '-'}",
            f"Label        {(v.label if v else None) or '-'}",
            f"Items        {v.item_count if v else 0}",
            f"Pages        {len(pages)}",
            f"In bundle    {in_bundle} pages from this volume",
        ])


class ItemInfoDialog(_InfoBase):
    def __init__(self, *, index: IndexClient, bundle: Bundle, isadg_id: int) -> None:
        super().__init__()
        self.index = index
        self.bundle = bundle
        self.isadg_id = isadg_id

    def _title(self) -> str:
        return "Item info"

    async def _body(self) -> str:
        item = await self.index.item(self.isadg_id)
        if item is None:
            return f"item {self.isadg_id} not found"
        pages_block = "\n".join(
            f"  {p.role:7s}  {p.root_id}/{p.page_key}"
            for p in item.pages
        )
        in_bundle = self.isadg_id in self.bundle.selected_items
        est = _fmt_range(item.estimated_begin, item.estimated_end)
        source = item.estimated_source
        if est != "-" and source:
            est = f"{est} (from {source})"
        return "\n".join([
            f"ISADG ID     {item.isadg_id}",
            f"Title        {item.title or '-'}",
            f"Reference    {item.reference_code or '-'}",
            f"Repository   {item.repository or '-'}",
            f"Content date {_fmt_range(item.content_begin, item.content_end)}",
            f"Created date {_fmt_range(item.created_begin, item.created_end)}",
            f"Estimated    {est}",
            "",
            f"Pages ({len(item.pages)})",
            pages_block,
            "",
            f"In bundle    {'yes (item selected)' if in_bundle else 'no'}",
        ])
