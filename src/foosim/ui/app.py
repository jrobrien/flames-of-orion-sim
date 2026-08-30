"""foosim desktop UI - Watch (AI vs AI) and Replay modes.

Run:  uv run --extra ui foosim-ui --seed 3
      uv run --extra ui foosim-ui --replay tests/data/replays/skirmish_2v2_seed1.json

Layout is a hello_imgui docking space (panels reflow with the window). M5 is
view-only: play/pause/step/scrub, select units, read stats and the event log.
Interactive play lands in M6.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from foosim.ai.policy import RandomPolicy
from foosim.engine.rules import Ruleset
from foosim.engine.rules import load as load_rules
from foosim.sim import replay as replaymod
from foosim.sim.autobattle import drive
from foosim.sim.setups import skirmish_2v2
from foosim.ui.camera import Camera
from foosim.ui.timeline import Timeline

_CRIT_KINDS = {"critical", "catastrophic"}
_BOOM_KINDS = {"explosion", "overheat"}
_KILL_KINDS = {"out_of_action"}


@dataclass
class UiState:
    rules: Ruleset
    timeline: Timeline
    mode: str  # "watch" | "replay"
    subtitle: str
    camera: Camera = field(default_factory=Camera)
    playing: bool = False
    speed: float = 5.0  # frames per second
    accum: float = 0.0
    selected_id: str | None = None
    log_filter: str = ""
    follow_log: bool = True
    autofit: bool = True
    fit_w: float = 0.0
    fit_h: float = 0.0

    def advance_playback(self, dt: float) -> None:
        if not self.playing:
            return
        self.accum += dt * self.speed
        while self.accum >= 1.0:
            self.accum -= 1.0
            if not self.timeline.step(1):
                self.playing = False
                self.accum = 0.0
                break


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------


def build_watch(rules: Ruleset, seed: int) -> UiState:
    gs = skirmish_2v2(rules, seed=seed)
    pols = {0: RandomPolicy(rules, seed * 2 + 1), 1: RandomPolicy(rules, seed * 2 + 2)}
    src = drive(gs, lambda st, sd: pols[sd].decide(st), rules)
    return UiState(rules, Timeline(gs, src), "watch", f"watch · seed {seed}")


def build_replay(rules: Ruleset, path: str) -> UiState:
    rep = replaymod.load(path)
    tl = Timeline(rep.state(), replaymod.iter_frames(rep, rules))
    tl.load_all()
    return UiState(rules, tl, "replay", f"replay · {path}")


# --------------------------------------------------------------------------
# panels  (imgui imported lazily so `import foosim.ui.app` stays cheap)
# --------------------------------------------------------------------------


def _toolbar(ui: UiState) -> None:
    from imgui_bundle import imgui

    ui.advance_playback(imgui.get_io().delta_time)
    tl = ui.timeline
    fr = tl.current

    if imgui.button("|<"):
        tl.seek(0)
        ui.playing = False
    imgui.same_line()
    if imgui.button("< step"):
        tl.step(-1)
        ui.playing = False
    imgui.same_line()
    if imgui.button("  pause  " if ui.playing else "  play  "):
        ui.playing = not ui.playing
        if ui.playing and tl.at_end():
            tl.seek(0)
    imgui.same_line()
    if imgui.button("step >"):
        tl.step(1)
        ui.playing = False
    imgui.same_line()
    if imgui.button("load all"):
        tl.load_all()
    imgui.same_line()
    if imgui.button("fit"):
        ui.autofit = True

    total = max(tl.last_index, 1)
    imgui.set_next_item_width(-1)
    changed, val = imgui.slider_int("##frame", tl.cursor, 0, total)
    if changed:
        tl.seek(val)
        ui.playing = False

    imgui.set_next_item_width(160)
    _, ui.speed = imgui.slider_float("fps", ui.speed, 0.5, 60.0)
    imgui.same_line()
    if imgui.button("next crit"):
        tl.jump(1, lambda e: e.kind in _CRIT_KINDS)
    imgui.same_line()
    if imgui.button("next boom"):
        tl.jump(1, lambda e: e.kind in _BOOM_KINDS)
    imgui.same_line()
    if imgui.button("next kill"):
        tl.jump(1, lambda e: e.kind in _KILL_KINDS)
    imgui.same_line()
    tail = "" if tl.complete else "  (+more)"
    imgui.text(
        f"  {ui.subtitle}   frame {tl.cursor}/{tl.last_index}{tail}   "
        f"round {fr.state.round}  {fr.state.phase}"
    )


def _units(ui: UiState) -> None:
    from foosim.ui import render

    ui.selected_id = render.draw_units_panel(ui.timeline.current.state, ui.selected_id)


def _stats(ui: UiState) -> None:
    from foosim.ui import render

    render.draw_stats_panel(ui.timeline.current.state, ui.selected_id)


def _log(ui: UiState) -> None:
    from imgui_bundle import imgui

    from foosim.ui import render

    imgui.set_next_item_width(200)
    _, ui.log_filter = imgui.input_text("filter", ui.log_filter)
    imgui.same_line()
    _, ui.follow_log = imgui.checkbox("follow", ui.follow_log)
    render.draw_event_log(
        ui.timeline._frames, ui.timeline.cursor, ui.log_filter, ui.follow_log and ui.playing
    )


def _map(ui: UiState) -> None:
    from imgui_bundle import ImVec2, imgui

    from foosim.ui import render

    io = imgui.get_io()
    fr = ui.timeline.current
    avail = imgui.get_content_region_avail()
    origin = imgui.get_cursor_screen_pos()
    w, h = max(avail.x, 10.0), max(avail.y, 10.0)

    grew = w > ui.fit_w * 1.2 or h > ui.fit_h * 1.2 or w < ui.fit_w * 0.8 or h < ui.fit_h * 0.8
    if ui.autofit and (ui.fit_w == 0.0 or grew):
        ui.camera.fit(fr.state.mapspec.cells(), w, h)
        ui.fit_w, ui.fit_h = w, h

    imgui.invisible_button("mapcanvas", ImVec2(w, h))
    hovered = None
    if imgui.is_item_hovered():
        mp = imgui.get_mouse_pos()
        lx, ly = mp.x - origin.x, mp.y - origin.y
        hovered = ui.camera.screen_to_hex(lx, ly)
        if io.mouse_wheel:
            ui.camera.zoom_at(lx, ly, 1.1 if io.mouse_wheel > 0 else 1.0 / 1.1)
            ui.autofit = False
        for btn in (1, 2):  # right / middle drag to pan
            if imgui.is_mouse_dragging(btn):
                d = imgui.get_mouse_drag_delta(btn)
                ui.camera.pan(d.x, d.y)
                imgui.reset_mouse_drag_delta(btn)
                ui.autofit = False
        if imgui.is_mouse_clicked(0) and hovered is not None:
            u = fr.state.unit_at(hovered)
            if u is not None:
                ui.selected_id = u.id

    render.draw_map(fr.state, ui.camera, (origin.x, origin.y), (w, h), ui.selected_id, hovered)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def _runner_params(ui: UiState):
    from imgui_bundle import hello_imgui, imgui

    rp = hello_imgui.RunnerParams()
    rp.app_window_params.window_title = "foosim"
    rp.app_window_params.window_geometry.size = (1360, 860)
    rp.app_window_params.restore_previous_geometry = True
    rp.fps_idling.enable_idling = False  # keep animating while playing
    rp.ini_filename_use_app_window_title = False
    rp.ini_filename = "foosim_ui.ini"
    rp.ini_folder_type = hello_imgui.IniFolderType.app_user_config_folder

    iw = rp.imgui_window_params
    iw.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    iw.enable_viewports = False
    iw.show_status_bar = True
    iw.show_status_fps = True

    def _split(initial: str, new: str, direction, ratio: float):
        s = hello_imgui.DockingSplit()
        s.initial_dock = initial
        s.new_dock = new
        s.direction = direction
        s.ratio = ratio
        return s

    def _win(label: str, dock: str, fn):
        w = hello_imgui.DockableWindow()
        w.label = label
        w.dock_space_name = dock
        w.gui_function = fn
        return w

    dp = hello_imgui.DockingParams()
    dp.docking_splits = [
        _split("MainDockSpace", "TopSpace", imgui.Dir.up, 0.13),
        _split("MainDockSpace", "LeftSpace", imgui.Dir.left, 0.16),
        _split("MainDockSpace", "RightSpace", imgui.Dir.right, 0.27),
        _split("RightSpace", "RightBottomSpace", imgui.Dir.down, 0.62),
    ]
    dp.dockable_windows = [
        _win("Transport", "TopSpace", lambda: _toolbar(ui)),
        _win("Units", "LeftSpace", lambda: _units(ui)),
        _win("Map", "MainDockSpace", lambda: _map(ui)),
        _win("Stats", "RightSpace", lambda: _stats(ui)),
        _win("Event Log", "RightBottomSpace", lambda: _log(ui)),
    ]
    rp.docking_params = dp
    return rp


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="foosim UI (watch / replay)")
    ap.add_argument("--replay", metavar="PATH", help="replay a saved .json instead of a live game")
    ap.add_argument("--seed", type=int, default=1, help="watch mode: setup + policy seed")
    args = ap.parse_args(argv)

    rules = load_rules()
    ui = build_replay(rules, args.replay) if args.replay else build_watch(rules, args.seed)

    try:
        from imgui_bundle import hello_imgui
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "the UI needs the 'ui' extra:  uv sync --extra ui   (then: uv run foosim-ui)"
        ) from None

    hello_imgui.run(_runner_params(ui))


if __name__ == "__main__":  # pragma: no cover
    main()
