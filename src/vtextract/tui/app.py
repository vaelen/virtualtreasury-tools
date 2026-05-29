# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from pathlib import Path
from typing import Literal

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle
from vtextract.tui.dialogs.build import ProgressModal
from vtextract.tui.dialogs.exit import ExitDialog
from vtextract.tui.dialogs.extract import ExtractDialog
from vtextract.tui.dialogs.file import FileDialog, FileResult
from vtextract.tui.dialogs.help import HelpDialog
from vtextract.tui.dialogs.index_prompt import IndexPromptDialog
from vtextract.tui.dialogs.info import (
    ItemInfoDialog,
    PageInfoDialog,
    VolumeInfoDialog,
)
from vtextract.tui.dialogs.search import SearchDialog, SearchSpec
from vtextract.tui.export import export_bundle
from vtextract.tui.extract_client import ExtractClient
from vtextract.tui.index_client import IndexClient, IndexError
from vtextract.tui.progress_events import ErrorEvent
from vtextract.tui.panes.bundle_pane import BundlePane
from vtextract.tui.panes.document_pane import DocumentPane
from vtextract.tui.screens.no_index import NoIndexScreen
from vtextract.tui.screens.pages import PagesScreen
from vtextract.tui.screens.results import ResultsScreen
from vtextract.tui.screens.transcription import TranscriptionScreen
from vtextract.tui.screens.volumes import VolumesScreen


class VtBrowseApp(App):
    TITLE = "vtbrowse"
    CSS = """
    Screen { layout: vertical; }
    Horizontal { height: 1fr; }
    """

    BINDINGS = [
        Binding("ctrl+x", "request_quit", "exit"),
        Binding("ctrl+f", "open_search", "search"),
        Binding("ctrl+r", "open_results", "results"),
        Binding("ctrl+v", "open_volumes", "volumes"),
        Binding("ctrl+i", "open_info", "info"),
        Binding("ctrl+s", "save_bundle", "save"),
        Binding("ctrl+o", "open_bundle", "open"),
        Binding("ctrl+shift+s", "export_bundle", "export"),
        Binding("ctrl+b", "build_index", "build"),
        Binding("ctrl+e", "extract", "extract"),
        Binding("f1", "open_help", "help"),
        Binding("question_mark", "open_help", "help"),
        Binding("tab", "focus_next", "switch pane"),
    ]

    def __init__(self, *, archive: Path) -> None:
        super().__init__()
        self.archive = archive
        self.index = IndexClient(archive)
        self.bundle = Bundle()
        self.last_results: list[dict] = []
        self.last_query: str | None = None
        self.current_root_id: str | None = None
        self._stale_chip_visible: bool = False
        self._bundle_dirty: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield BundlePane(self.bundle)
            yield DocumentPane()
        yield Footer()

    def on_mount(self) -> None:
        state = self._detect_index_state()
        if state in ("missing", "stale"):
            self.push_screen(
                IndexPromptDialog(
                    state=state, archive=self.archive,
                    index_path=self._index_path()),
                lambda ok, s=state: self._on_index_prompt_dismissed(ok, s),
            )
            return
        self._finalize_startup(state)

    def _on_index_prompt_dismissed(
        self, ok: bool | None, state: Literal["missing", "stale"],
    ) -> None:
        if ok:
            self.action_build_index()
        elif state == "missing":
            self._show_no_index_screen()
            self._start_stale_poll()
            return
        self._finalize_startup(state)

    def _finalize_startup(
        self, state: Literal["missing", "stale", "ok"],
    ) -> None:
        self.open_volumes()
        if state == "stale":
            self._stale_chip_visible = True
            self._refresh_header_chip()
        self._start_stale_poll()

    # ---------- index state ----------

    def _index_path(self) -> Path:
        # Mirror ``vtextract.index.builder.INDEX_RELPATH``. We can't import it
        # here per the boundary rule, so we duplicate the literal — acceptable
        # because it's a stable on-disk layout fact.
        return self.archive / "index" / "vtindex.sqlite3"

    def _detect_index_state(self) -> Literal["missing", "stale", "ok"]:
        try:
            stats = self.index.stats()
        except IndexError:
            return "missing"
        return "stale" if stats.get("stale") else "ok"

    def _show_no_index_screen(self) -> None:
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        pane.mount(NoIndexScreen(index_path=self._index_path()))
        self.call_after_refresh(self.query_one(DocumentPane).children[0].focus)

    def _start_stale_poll(self) -> None:
        self.set_interval(30.0, self._poll_stale)

    def _poll_stale(self) -> None:
        try:
            stats = self.index.stats()
        except IndexError:
            return
        is_stale = bool(stats.get("stale"))
        if is_stale != self._stale_chip_visible:
            self._stale_chip_visible = is_stale
            self._refresh_header_chip()

    def _refresh_header_chip(self) -> None:
        # Stash chip text in ``App.sub_title`` — Textual's Header widget reads
        # ``App.sub_title`` at mount and on refresh.
        self.sub_title = (
            "[stale: press Ctrl+B to rebuild]"
            if self._stale_chip_visible else ""
        )

    def open_volumes(self) -> None:
        self.current_root_id = None
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = VolumesScreen(self.index)
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def open_pages(self, root_id: str) -> None:
        self.current_root_id = root_id
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = PagesScreen(index=self.index, bundle=self.bundle, root_id=root_id)
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def open_transcription(self, root_id: str, page_key: str,
                           *, query: str | None = None) -> None:
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = TranscriptionScreen(
            index=self.index, reader=ArchiveReader(self.archive),
            bundle=self.bundle, root_id=root_id, page_key=page_key,
            query=query,
        )
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def bundle_changed(self) -> None:
        self._bundle_dirty = True
        self.query_one(BundlePane).refresh_content()

    def action_request_quit(self) -> None:
        if not self._bundle_dirty:
            self.exit()
            return
        pages = len(self.bundle.effective_pages())
        items = len(self.bundle.selected_items)
        self.push_screen(
            ExitDialog(page_count=pages, item_count=items),
            self._on_exit_choice,
        )

    def _on_exit_choice(self, choice: str | None) -> None:
        if choice == "cancel" or choice is None:
            return
        if choice == "save_and_exit":
            self.push_screen(
                FileDialog(mode="save", start_dir=Path.home()),
                self._on_save_then_exit,
            )
            return
        # choice == "exit"
        self.exit()

    def _on_save_then_exit(self, result: FileResult | None) -> None:
        if result is None:
            return
        result.path.write_text(self.bundle.to_json())
        self._bundle_dirty = False
        self.exit()

    def action_open_help(self) -> None:
        self.push_screen(HelpDialog())

    # ---------- search flow ----------

    def action_open_search(self) -> None:
        self.push_screen(SearchDialog(default_volume=self.current_root_id),
                         self._on_search_submitted)

    def _on_search_submitted(self, spec: SearchSpec | None) -> None:
        if spec is None:
            return
        rows = self.index.search(
            query=spec.query, fields=spec.fields,
            date_from=spec.date_from, date_to=spec.date_to,
            date_type=spec.date_type, volume=spec.volume,
        )
        self.last_results = rows
        self.last_query = spec.query
        self.action_open_results()

    def action_open_results(self) -> None:
        if not self.last_results:
            return
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        screen = ResultsScreen(
            bundle=self.bundle,
            results=self.last_results,
            query=self.last_query or "",
        )
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def action_open_volumes(self) -> None:
        self.open_volumes()

    # ---------- info dispatch ----------

    def action_open_info(self) -> None:
        pane = self.query_one(DocumentPane)
        if not pane.children:
            return
        screen_widget = pane.children[0]
        ctx = getattr(screen_widget, "selected_context", lambda: None)()
        if ctx is None:
            return
        if ctx[0] == "volume":
            dialog = VolumeInfoDialog(index=self.index, bundle=self.bundle,
                                      root_id=ctx[1])
        elif ctx[0] == "item":
            dialog = ItemInfoDialog(index=self.index, bundle=self.bundle,
                                    isadg_id=ctx[1])
        elif ctx[0] == "page":
            dialog = PageInfoDialog(index=self.index,
                                    reader=ArchiveReader(self.archive),
                                    bundle=self.bundle,
                                    root_id=ctx[1], page_key=ctx[2])
        else:
            return
        self.push_screen(dialog)

    # ---------- save / open / export ----------

    def action_save_bundle(self) -> None:
        self.push_screen(
            FileDialog(mode="save", start_dir=Path.home()),
            self._on_save_chosen,
        )

    def _on_save_chosen(self, result: FileResult | None) -> None:
        if result is None:
            return
        result.path.write_text(self.bundle.to_json())
        self._bundle_dirty = False
        self.notify(f"Saved to {result.path}")

    def action_open_bundle(self) -> None:
        self.push_screen(
            FileDialog(mode="open", start_dir=Path.home()),
            self._on_open_chosen,
        )

    def _on_open_chosen(self, result: FileResult | None) -> None:
        if result is None or not result.path.exists():
            return
        self.bundle = Bundle.from_json(result.path.read_text())
        self.bundle_changed()
        # ``bundle_changed`` re-marks dirty for the load-side mutation; an
        # Open is effectively a clean slate — the on-disk file IS the truth.
        self._bundle_dirty = False
        self.notify(f"Opened {result.path}")

    def action_export_bundle(self) -> None:
        self.push_screen(
            FileDialog(mode="export", start_dir=Path.home()),
            self._on_export_chosen,
        )

    def _on_export_chosen(self, result: FileResult | None) -> None:
        if result is None:
            return
        if result.include_images:
            reader = ArchiveReader(self.archive)
            missing_isadg_ids: set[int] = set()
            for ref in self.bundle.effective_pages():
                if reader.image_exists(ref.root_id, ref.page_key):
                    continue
                for iid, page_refs in self.bundle.selected_items.items():
                    if ref in page_refs:
                        missing_isadg_ids.add(iid)
            if missing_isadg_ids:
                extract = ExtractClient(archive=self.archive)
                ids = sorted(missing_isadg_ids)
                self.push_screen(
                    ProgressModal(
                        title=f"vtextract get --images ({len(ids)} items)",
                        stream_factory=lambda: extract.get_images_stream(ids),
                    ),
                    lambda ok: self._after_backfill(ok, result),
                )
                return
        self._do_export(result)

    def _after_backfill(self, ok: bool | None, result: FileResult) -> None:
        if ok:
            self._do_export(result)
        else:
            self.notify("Image backfill failed; export aborted.",
                        severity="error")

    def _do_export(self, result: FileResult) -> None:
        out = export_bundle(
            bundle=self.bundle, archive=self.archive,
            destination=result.path, include_images=result.include_images,
            fmt=result.fmt,
        )
        self.notify(f"Exported to {out}")

    # ---------- index build ----------

    def action_build_index(self) -> None:
        self.push_screen(ProgressModal(
            title="vtindex build",
            stream_factory=lambda: self.index.build_stream(),
        ))

    # ---------- extract (⌃E) ----------

    def action_extract(self) -> None:
        self.push_screen(ExtractDialog(), self._after_extract_form)

    def _after_extract_form(self, argv: list[str] | None) -> None:
        if argv is None:
            return

        extract = ExtractClient(archive=self.archive)
        index = self.index

        async def chained():
            step1_ok = True
            # Step 1: vtextract search
            async for ev in extract.search_stream(argv=argv):
                yield ev
                if isinstance(ev, ErrorEvent):
                    step1_ok = False
                    return
            # Step 2: vtindex build (only if Step 1 finished cleanly)
            if step1_ok:
                async for ev in index.build_stream():
                    yield ev

        self.push_screen(ProgressModal(
            title="vtextract search → vtindex build",
            stream_factory=chained,
        ))
