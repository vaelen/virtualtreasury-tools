# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import asyncio
import time
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
from vtextract.tui.dialogs.splash import SplashScreen
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
    # Minimum time the startup splash stays up, so a fast index open does not
    # flash it. Tests override this to 0 (see tests/tui/conftest.py).
    SPLASH_MIN_SECONDS = 0.5
    # Defer the slow startup work to after the splash's first paint (see
    # on_mount / _run_startup). Tests set this False so startup runs inline and
    # the screen stack is settled before the test drives the app; the real
    # deferred path has its own coverage (test_splash_shown_on_real_startup_path).
    SPLASH_DEFER_STARTUP = True
    CSS = """
    Screen { layout: vertical; }
    /* The main Bundle | Document split fills the height between header and
       footer. Scoped to #main so the rule does NOT leak into modal dialogs,
       whose own Horizontals (button rows, the date row) must stay compact. */
    #main { height: 1fr; }

    /* Every modal dialog is a centred box over the main screen, not a
       full-screen takeover. */
    ModalScreen { align: center middle; }
    /* Horizontal's own default height is 1fr; inside a dialog that fills the
       box and forces it to max-height. Dialog rows (buttons, the date pair)
       must be compact so the box sizes to its content. */
    ModalScreen Horizontal { height: auto; }
    #search-dialog, #extract-dialog, #file-dialog, #exit-dialog,
    #progress-modal, #help-dialog, #info-dialog, #index-prompt,
    #splash-dialog {
        width: 70%;
        max-width: 92;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    /* The splash centers its title + status within the box; the brand title
       is bold so it reads as a heading above the subtitle and status. */
    #splash-dialog { content-align: center middle; text-align: center; }
    #splash-title { text-style: bold; }

    /* The two date inputs share their row instead of the first filling it
       and pushing the second off-screen. */
    #search-dialog #from, #search-dialog #to,
    #extract-dialog #from, #extract-dialog #to { width: 1fr; }

    /* Dialogs holding a scrollable tree / table need a bounded body to
       scroll within. */
    #file-dialog { height: 85%; }
    #file-dialog #tree { height: 1fr; }
    #help-dialog { height: 85%; }
    #help-dialog DataTable { height: 1fr; }
    """

    # Plain single-key bindings (no control modifiers). These fire only when no
    # focused widget consumes the key first, so typing into a dialog Input is
    # unaffected — Inputs swallow printable keys before they reach the app.
    BINDINGS = [
        Binding("q", "request_quit", "quit"),
        Binding("f", "open_search", "find"),
        Binding("r", "open_results", "results"),
        Binding("v", "open_volumes", "volumes"),
        Binding("i", "open_info", "info"),
        Binding("s", "save_bundle", "save"),
        Binding("o", "open_bundle", "open"),
        Binding("x", "export_bundle", "export"),
        Binding("b", "build_index", "build"),
        Binding("e", "extract", "extract"),
        Binding("f1", "open_help", "help"),
        Binding("question_mark", "open_help", "help"),
        Binding("tab", "focus_next", "switch pane"),
    ]

    def __init__(self, *, archive: Path, initial_theme: str | None = None) -> None:
        super().__init__()
        self.archive = archive
        self._initial_theme = initial_theme
        self.index = IndexClient(archive)
        self.bundle = Bundle()
        self.last_results: list = []
        self.last_query: str | None = None
        self.current_root_id: str | None = None
        self.current_volume_title: str | None = None
        self._stale_chip_visible: bool = False
        self._bundle_dirty: bool = False
        self._splash: SplashScreen | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            yield BundlePane(self.bundle)
            yield DocumentPane()
        yield Footer()

    async def on_mount(self) -> None:
        # Restore the saved theme. Guarded: an unregistered name (a typo, or a
        # theme dropped in a Textual upgrade) would raise InvalidThemeError, so
        # ignore it and let Textual's default stand.
        if self._initial_theme in self.available_themes:
            self.theme = self._initial_theme
        # Push the splash, then DEFER the slow startup work. Textual dispatches
        # the initial Mount (this on_mount) inside a batch_update() that
        # suspends all repaints until the batch ends. Any slow work done here
        # would run — and dismiss the splash — before a single frame paints, so
        # the splash would never reach the screen. call_after_refresh runs the
        # work only after the batch ends and the splash has painted.
        self._splash = SplashScreen()
        self.push_screen(self._splash)
        if self.SPLASH_DEFER_STARTUP:
            self.call_after_refresh(self._run_startup)
        else:
            # Inline path (tests): run startup now so the stack is settled
            # before the caller interacts. The splash never paints here anyway
            # — the initial mount runs inside Textual's repaint-suspending
            # batch_update — but the end state is identical.
            await self._run_startup()

    async def _run_startup(self) -> None:
        # Runs after the splash's first paint (see on_mount). Does the slow
        # index open + volume load behind the visible splash, then dismisses it.
        start = time.monotonic()
        try:
            state = await self._detect_index_state()
            if state in ("missing", "stale"):
                await self._dismiss_splash(start)
                self.push_screen(
                    IndexPromptDialog(
                        state=state, archive=self.archive,
                        index_path=self._index_path()),
                    lambda ok, s=state: self._on_index_prompt_dismissed(ok, s),
                )
                return
            if self._splash is not None:
                self._splash.set_status("Loading volumes…")
            self._finalize_startup(state)
            await self._dismiss_splash(start)
            self.call_after_refresh(self._focus_document_pane)
        except Exception:
            # Never leave the modal splash stranded over a half-initialized
            # app: dismiss it immediately (skipping the min-display wait) and
            # let the error propagate. The guard makes a later dismiss a no-op.
            if self._splash is not None:
                self._splash.dismiss()
                self._splash = None
            raise

    async def _dismiss_splash(self, start: float) -> None:
        # Keep the splash up for at least SPLASH_MIN_SECONDS so a fast load
        # does not flash it, then pop it. Guarded so a second call is a no-op.
        remaining = self.SPLASH_MIN_SECONDS - (time.monotonic() - start)
        if remaining > 0:
            await asyncio.sleep(remaining)
        if self._splash is not None:
            self._splash.dismiss()
            self._splash = None

    def _focus_document_pane(self) -> None:
        # After the modal splash pops, focus returns to nothing (the splash was
        # pushed before any screen was focused), so re-assert focus on the
        # revealed document-pane child (the VolumesScreen). open_volumes already
        # scheduled a focus call, but that one was shadowed while the splash
        # modal owned focus, so this re-assert is what actually takes effect.
        children = self.query_one(DocumentPane).children
        if children:
            children[0].focus()

    def on_unmount(self) -> None:
        self.index.close()

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

    async def _detect_index_state(self) -> Literal["missing", "stale", "ok"]:
        try:
            stats = await self.index.stats()
        except IndexError:
            return "missing"
        return "stale" if stats.stale else "ok"

    def _show_no_index_screen(self) -> None:
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        self.set_pane_title("No index")
        self.set_pane_count("")
        pane.mount(NoIndexScreen(index_path=self._index_path()))
        self.call_after_refresh(self.query_one(DocumentPane).children[0].focus)

    def _start_stale_poll(self) -> None:
        self.set_interval(30.0, self._poll_stale)

    async def _poll_stale(self) -> None:
        try:
            stats = await self.index.stats()
        except IndexError:
            return
        is_stale = bool(stats.stale)
        if is_stale != self._stale_chip_visible:
            self._stale_chip_visible = is_stale
            self._refresh_header_chip()

    def _refresh_header_chip(self) -> None:
        # Stash chip text in ``App.sub_title`` — Textual's Header widget reads
        # ``App.sub_title`` at mount and on refresh.
        self.sub_title = (
            "[stale: press b to rebuild]"
            if self._stale_chip_visible else ""
        )

    # ---------- document-pane title / count footer ----------

    def set_pane_title(self, text: str) -> None:
        self.query_one(DocumentPane).border_title = text

    def set_pane_count(self, text: str) -> None:
        # Rendered right-aligned in the pane's bottom border (border_subtitle).
        self.query_one(DocumentPane).border_subtitle = text

    def _mount_screen(self, screen, *, title: str) -> None:
        pane = self.query_one(DocumentPane)
        pane.remove_children()
        self.set_pane_title(title)
        self.set_pane_count("")  # list screens republish after layout
        pane.mount(screen)
        self.call_after_refresh(screen.focus)

    def open_volumes(self) -> None:
        self.current_root_id = None
        self.current_volume_title = None
        self._mount_screen(VolumesScreen(self.index), title="Volumes")

    def open_pages(self, root_id: str, *, title: str | None = None) -> None:
        # Back-navigation (esc from a transcription) re-opens pages without a
        # title; reuse the one we remembered for this volume rather than
        # falling back to the bare root id.
        if title is None and self.current_root_id == root_id:
            title = self.current_volume_title
        self.current_root_id = root_id
        self.current_volume_title = title
        self._mount_screen(
            PagesScreen(index=self.index, bundle=self.bundle, root_id=root_id),
            title=title or root_id,
        )

    def open_transcription(self, root_id: str, page_key: str,
                           *, query: str | None = None,
                           origin: str = "pages",
                           view: Literal["text", "image"] = "text") -> None:
        vol = (self.current_volume_title
               if self.current_root_id == root_id else None)
        base_title = f"{vol} — {page_key}" if vol else page_key
        screen = TranscriptionScreen(
            index=self.index, reader=ArchiveReader(self.archive),
            bundle=self.bundle, root_id=root_id, page_key=page_key,
            query=query, origin=origin, view=view, base_title=base_title,
        )
        title = base_title + (" [image]" if view == "image" else "")
        # Transcription is a single document, not a list — no count footer.
        self._mount_screen(screen, title=title)

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
                FileDialog(mode="save", start_dir=Path.cwd()),
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

    async def _on_search_submitted(self, spec: SearchSpec | None) -> None:
        if spec is None:
            return
        rows = await self.index.search(
            query=spec.query, fields=spec.fields,
            date_from=spec.date_from, date_to=spec.date_to,
            date_type=spec.date_type, volume=spec.volume,
            limit=0,  # the TUI renders the full result set, not a 50-row page
        )
        self.last_results = rows
        self.last_query = spec.query
        self.action_open_results()

    def action_open_results(self) -> None:
        if not self.last_results:
            return
        screen = ResultsScreen(
            bundle=self.bundle,
            results=self.last_results,
            query=self.last_query or "",
        )
        # ResultsScreen.on_mount re-publishes this title with the sort-mode suffix
        self._mount_screen(screen, title="Search Results")

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
            FileDialog(mode="save", start_dir=Path.cwd()),
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
            FileDialog(mode="open", start_dir=Path.cwd()),
            self._on_open_chosen,
        )

    def _on_open_chosen(self, result: FileResult | None) -> None:
        if result is None or not result.path.exists():
            return
        self.bundle.replace_contents(Bundle.from_json(result.path.read_text()))
        self.bundle_changed()
        # ``bundle_changed`` re-marks dirty for the load-side mutation; an
        # Open is effectively a clean slate — the on-disk file IS the truth.
        self._bundle_dirty = False
        self.notify(f"Opened {result.path}")

    def action_export_bundle(self) -> None:
        self.push_screen(
            FileDialog(mode="export", start_dir=Path.cwd()),
            self._on_export_chosen,
        )

    def _on_export_chosen(self, result: FileResult | None) -> None:
        if result is None:
            return
        if result.include_images:
            reader = ArchiveReader(self.archive)
            missing_isadg_ids: set[int] = set()
            missing_page_keys: set[str] = set()
            for ref in self.bundle.effective_pages():
                if reader.image_exists(ref.root_id, ref.page_key):
                    continue
                missing_page_keys.add(ref.page_key)
                for iid, page_refs in self.bundle.selected_items.items():
                    if ref in page_refs:
                        missing_isadg_ids.add(iid)
            if missing_isadg_ids:
                extract = ExtractClient(archive=self.archive)
                ids = sorted(missing_isadg_ids)
                # Pass the selected page keys so the backfill downloads only
                # those pages, not every image in the resource's manifest
                # (which may span an entire volume).
                page_keys = sorted(missing_page_keys)
                self.push_screen(
                    ProgressModal(
                        title=f"vtextract get --images ({len(ids)} items)",
                        stream_factory=lambda cancel_event=None: (
                            extract.get_images_stream(
                                ids, page_keys=page_keys,
                                cancel_event=cancel_event,
                            )
                        ),
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
            stream_factory=lambda cancel_event=None: (
                self.index.build_stream(cancel_event=cancel_event)
            ),
        ))

    # ---------- extract (e) ----------

    def action_extract(self) -> None:
        self.push_screen(ExtractDialog(), self._after_extract_form)

    def _after_extract_form(self, argv: list[str] | None) -> None:
        if argv is None:
            return

        extract = ExtractClient(archive=self.archive)
        index = self.index

        async def chained(cancel_event=None):
            step1_ok = True
            # Step 1: vtextract search
            search_gen = extract.search_stream(
                argv=argv, cancel_event=cancel_event,
            )
            try:
                async for ev in search_gen:
                    yield ev
                    if isinstance(ev, ErrorEvent):
                        step1_ok = False
                        return
                    if cancel_event is not None and cancel_event.is_set():
                        return
            finally:
                await search_gen.aclose()
            # Step 2: vtindex build (only if Step 1 finished cleanly)
            if step1_ok and not (cancel_event and cancel_event.is_set()):
                build_gen = index.build_stream(cancel_event=cancel_event)
                try:
                    async for ev in build_gen:
                        yield ev
                        if cancel_event is not None and cancel_event.is_set():
                            return
                finally:
                    await build_gen.aclose()

        self.push_screen(ProgressModal(
            title="vtextract search → vtindex build",
            stream_factory=chained,
        ))
