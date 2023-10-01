from datetime import datetime
import logging
import time
from typing import ClassVar
from rich.style import Style
from rich.text import Text

import textual
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Footer, Static, RadioSet, RadioButton
from textual.events import Click

from flameshow.models import Frame
from flameshow.render.header import FlameshowHeader
from flameshow.utils import fgid
from flameshow import __version__

from .span import Span
from .flamegraph import FlameGraph

logger = logging.getLogger(__name__)


class FlameGraphScroll(VerticalScroll, inherit_bindings=False):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("b", "scroll_up", "Scroll Up", show=True, key_display="B"),
        Binding(
            "f,space", "scroll_down", "Scroll Down", show=True, key_display="F"
        ),
        Binding("home", "scroll_home", "Scroll Home", show=False),
        Binding("end", "scroll_end", "Scroll End", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]


class FlameGraphApp(App):
    BINDINGS = [
        Binding("k,up", "move_up", "Up", key_display="↑"),
        Binding("l,right", "move_right", "Right", key_display="→"),
        Binding("h,left", "move_left", "Left", key_display="←"),
        Binding("enter", "zoom_in", "Zoom In"),
        Binding("escape", "zoom_out", "Zoom Out", show=False),
        Binding("d", "toggle_dark", "Toggle dark mode", show=False),
        Binding(
            "s",
            "switch_sample_type",
            "Switch Sample Type",
            priority=True,
        ),
        Binding("ctrl+c,q", "quit", "Quit", show=True, key_display="Q"),
    ]

    DEFAULT_CSS = """
    #span-detail-container {
    }

    #span-detail {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        border: round $secondary;
        border-subtitle-align: left;
        content-align-vertical: middle;
    }

    #sample-type-radio {
        width: 20%;
        height: 1fr;
    }

    """

    focused_stack_id = reactive(0)
    sample_index = reactive(None, init=False)
    view_frame = reactive(None, init=False)

    def __init__(
        self,
        profile,
        _debug_exit_after_rednder=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.root_stack = profile.root_stack

        self._debug_exit_after_rednder = _debug_exit_after_rednder

        self.parents_that_only_one_child = []

        self.filename = self.profile.filename

        if profile.default_sample_type_index < 0:
            self.sample_index = (
                len(profile.sample_types) + profile.default_sample_type_index
            )
        else:
            self.sample_index = profile.default_sample_type_index

    def on_mount(self):
        logger.info("mounted")
        self.title = "flameshow"
        self.sub_title = f"v{__version__}"

        self.view_frame = self.root_stack

        fg = self.query_one("FlameGraph")
        fg.focus()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""

        center_text = self._center_header_text(self.sample_index)
        yield FlameshowHeader(center_text)

        options = [
            RadioButton(f"{s.sample_type}, {s.sample_unit}")
            for s in self.profile.sample_types
        ]
        options[self.sample_index].value = True
        radioset = RadioSet(*options, id="sample-type-radio")
        detail_row = Horizontal(
            Static(
                id="span-detail",
            ),
            radioset,
            id="span-detail-container",
        )

        # set min height, 2 lines of detail + 2 lines border
        detail_row.styles.height = max(4, len(options) + 2)

        yield detail_row

        fg = FlameGraph(
            self.profile,
            self.focused_stack_id,
            self.sample_index,
            self.root_stack._id,
        )
        fg.styles.height = self.profile.highest_lines + 1

        yield FlameGraphScroll(
            fg,
            id="flamegraph-out-container",
        )

        yield Static(id="loading-status")
        yield self._profile_info(self.profile.created_at)
        yield Footer()

    def _center_header_text(self, sample_index):
        chosen_sample_type = self.profile.sample_types[sample_index]
        center_header = (
            f"{self.filename}: ({chosen_sample_type.sample_type},"
            f" {chosen_sample_type.sample_unit})"
        )
        return center_header

    def set_status_loading(self):
        widget = self.query_one("#loading-status")
        widget.update(Text("● loading...", Style(color="green")))
        self.loading_start_time = time.time()

    def set_status_loading_done(self):
        widget = self.query_one("#loading-status")
        widget.update("")
        self.loading_end_time = time.time()
        logger.info(
            "rerender done, took %.3f seconds.",
            self.loading_end_time - self.loading_start_time,
        )

    def _profile_info(self, created_at: datetime):
        if not created_at:
            return Static("")

        datetime_str = created_at.astimezone().strftime(
            "Dumped at %Y %b %d(%A) %H:%M:%S %Z"
        )
        return Static(datetime_str)

    async def watch_sample_index(self, sample_index):
        logger.info("sample index changed to %d", sample_index)

        center_text = self._center_header_text(self.sample_index)
        try:
            header = self.query_one("FlameshowHeader")
        except NoMatches:
            logger.warning(
                "FlameshowHeader not found, might be not composed yet."
            )
            return
        header.center_text = center_text

        stack = self.profile.id_store[self.focused_stack_id]
        # await self._rerender(stack, sample_index)

    async def watch_focused_stack_id(
        self,
        focused_stack_id,
    ):
        logger.info(f"{focused_stack_id=} changed")
        flamegraph_widget = self.query_one("FlameGraph")
        flamegraph_widget.focused_stack_id = focused_stack_id
        # await self._rerender(new_focused_stack, self.sample_index)

    def __debug_dom(self, node, indent: int):
        for c in node.children:
            logger.debug("%s %s", indent * " ", c)
            self.__debug_dom(c, indent + 2)

    @on(Span.SpanSelected)
    def handle_span_select(self, message):
        logger.info("app message: %s", message)
        newid = message.stack_id

        self.focused_stack_id = newid

    @on(Click)
    def handle_switch_to_mouse(self):
        logger.debug("mouse click")

    @on(RadioSet.Changed)
    async def handle_radioset_changed(self, e):
        logger.info("event: %s", e)
        self.sample_index = e.index

    @on(FlameGraph.ViewFrameChanged)
    async def handle_view_frame_changed(self, e):
        logger.debug("app handle_view_frame_changed...")
        new_frame = e.frame_id
        self.view_frame = self.profile.id_store[new_frame]

        flamegraph = self.query_one("FlameGraph")
        flamegraph.view_frame_id = new_frame

    async def watch_view_frame(self, old, new_frame):
        logger.debug(
            "view info stack changed: old: %s, new: %s",
            old,
            new_frame,
        )
        # set the viewstack info
        self.set_stack_detail(new_frame)

    def set_stack_detail(self, stack):
        span_detail = self.query_one("#span-detail")
        span_detail.border_subtitle = stack.render_title()
        span_detail.update(
            stack.render_detail(self.sample_index, self.sample_unit)
        )

    def action_move_up(self):
        logger.debug("move up")
        parent = self.view_info_stack.parent

        if not parent:
            logger.debug("no more children")
            return

        new_view_info_stack = parent
        self._set_new_viewinfostack(new_view_info_stack)

    def action_move_right(self):
        logger.debug("move right")

        right = self._find_right_sibling(self.view_info_stack)

        logger.debug("found right sibling: %s, %s", right, right.values)
        if not right:
            logger.debug("Got no right sibling")
            return

        self._set_new_viewinfostack(right)

    def action_move_left(self):
        logger.debug("move left")

        left = self._find_left_sibling(self.view_info_stack)

        if not left:
            logger.debug("Got no left sibling")
            return

        self._set_new_viewinfostack(left)

    def _find_left_sibling(self, me):
        """
        Find left.
        Even not currently displayed, still can be viewed on detail.
        No need to check if the fgid is currently rendered.
        """
        my_parent = me.parent
        while my_parent:
            siblings = my_parent.children
            if len(siblings) >= 2:
                choose_index = siblings.index(me)
                # move left, until:
                # got a sibling while value is not 0 (0 won't render)
                # and index >= 0
                while choose_index >= 0:
                    choose_index = choose_index - 1
                    if (
                        choose_index >= 0
                        and siblings[choose_index].values[self.sample_index]
                        > 0
                    ):
                        return siblings[choose_index]

            me = my_parent
            my_parent = my_parent.parent

    def _find_right_sibling(self, me):
        my_parent = me.parent
        while my_parent:
            siblings = my_parent.children
            if len(siblings) >= 2:
                choose_index = siblings.index(me)
                while choose_index < len(siblings):
                    choose_index = choose_index + 1
                    if (
                        choose_index < len(siblings)
                        and siblings[choose_index].values[self.sample_index]
                        > 0
                    ):
                        return siblings[choose_index]

            me = my_parent
            my_parent = my_parent.parent

    def action_zoom_in(self):
        logger.info("Zoom in!")
        self.focused_stack_id = self.view_info_stack._id

    def action_zoom_out(self):
        logger.info("Zoom out!")
        self.focused_stack_id = self.root_stack._id

    def action_switch_sample_type(self):
        logger.info("Focus on radio type")
        sample_radio = self.query_one("#sample-type-radio")
        if sample_radio.has_focus:
            sample_radio.blur()
        else:
            sample_radio.focus()

    @property
    def sample_unit(self):
        return self.profile.sample_types[self.sample_index].sample_unit

    def is_span_exist(self, span_id):
        _id = f"#{fgid(span_id)}"
        try:
            self.query_one(_id)
            return True
        except NoMatches:
            return False
