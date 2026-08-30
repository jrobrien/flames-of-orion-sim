"""foosim desktop UI - Watch / Play / Hotseat / Replay.

  uv run --extra ui foosim-ui --seed 3            # watch AI vs AI
  uv run --extra ui foosim-ui --play --seed 3     # you are side 0, AI side 1
  uv run --extra ui foosim-ui --hotseat --seed 3  # both sides human
  uv run --extra ui foosim-ui --replay tests/data/replays/skirmish_2v2_seed1.json

Layout is a hello_imgui docking space. Scrub back to review; "rewind to here"
truncates history so you can try a different line.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from foosim.ai.policy import RandomPolicy
from foosim.engine.actions import (
    ActivateUnit,
    DisengageAction,
    EndActivation,
    IllegalAction,
    MeleeAttackAction,
    MoveAction,
    Pass,
    PurgeHeatAction,
    RangedAttackAction,
)
from foosim.engine.rules import Ruleset
from foosim.engine.rules import load as load_rules
from foosim.sim import replay as replaymod
from foosim.sim.setups import skirmish_2v2
from foosim.ui.camera import Camera
from foosim.ui.interaction import compute_overlay, submode
from foosim.ui.session import Session
from foosim.ui.timeline import Timeline

_CRIT_KINDS = {"critical", "catastrophic"}
_BOOM_KINDS = {"explosion", "overheat"}
_KILL_KINDS = {"out_of_action"}


@dataclass
class UiState:
    rules: Ruleset
    driver: object  # Session | Timeline
    mode: str  # "watch" | "play" | "hotseat" | "replay"
    subtitle: str
    camera: Camera = field(default_factory=Camera)
    playing: bool = False
    speed: float = 5.0
    accum: float = 0.0
    selected_id: str | None = None
    selected_hex: object = None
    hover_hex: object = None
    action_mode: str = "idle"
    pending_weapon: int | None = None
    bolster: bool = False
    log_filter: str = ""
    follow_log: bool = True
    autofit: bool = True
    fit_w: float = 0.0
    fit_h: float = 0.0

    @property
    def is_session(self) -> bool:
        return isinstance(self.driver, Session)

    def reset_targeting(self) -> None:
        self.action_mode = "idle"
        self.pending_weapon = None

    def advance_playback(self, dt: float) -> None:
        if not self.playing:
            return
        self.accum += dt * self.speed
        while self.accum >= 1.0:
            self.accum -= 1.0
            if not self.driver.advance_one():
                self.playing = False
                self.accum = 0.0
                break


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------


def _policies(rules: Ruleset, seed: int) -> dict[int, object]:
    return {0: RandomPolicy(rules, seed * 2 + 1), 1: RandomPolicy(rules, seed * 2 + 2)}


def build_watch(rules: Ruleset, seed: int) -> UiState:
    gs = skirmish_2v2(rules, seed=seed)
    sess = Session(rules, gs, _policies(rules, seed))
    return UiState(rules, sess, "watch", f"watch · seed {seed}")


def build_play(rules: Ruleset, seed: int, *, hotseat: bool) -> UiState:
    gs = skirmish_2v2(rules, seed=seed)
    if hotseat:
        ctrl: dict[int, object] = {0: "human", 1: "human"}
    else:
        ctrl = {0: "human", 1: RandomPolicy(rules, seed * 2 + 2)}
    sess = Session(rules, gs, ctrl)
    label = "hotseat" if hotseat else "play"
    return UiState(rules, sess, label, f"{label} · seed {seed}")


def build_replay(rules: Ruleset, path: str) -> UiState:
    rep = replaymod.load(path)
    tl = Timeline(rep.state(), replaymod.iter_frames(rep, rules))
    tl.load_all()
    return UiState(rules, tl, "replay", f"replay · {path}")


# --------------------------------------------------------------------------
# panels
# --------------------------------------------------------------------------


def _toolbar(ui: UiState) -> None:
    from imgui_bundle import imgui

    ui.advance_playback(imgui.get_io().delta_time)
    d = ui.driver
    fr = d.current

    if imgui.button("|<"):
        d.seek(0)
        ui.playing = False
    imgui.same_line()
    if imgui.button("< step"):
        d.step(-1)
        ui.playing = False
    imgui.same_line()
    if imgui.button("  pause  " if ui.playing else "  play  "):
        ui.playing = not ui.playing
        if ui.playing and d.at_end():
            d.seek(0)
    imgui.same_line()
    if imgui.button("step >") and not d.advance_one():
        ui.playing = False
    imgui.same_line()
    if hasattr(d, "load_all") and imgui.button("load all"):
        d.load_all()
    imgui.same_line()
    if imgui.button("fit"):
        ui.autofit = True
    imgui.same_line()
    if ui.is_session and not d.at_live() and imgui.button(">> live"):
        d.seek(d.last_index)
    imgui.same_line()
    if ui.is_session and imgui.button("rewind to here"):
        d.rewind_to_cursor()
        ui.reset_targeting()

    total = max(d.last_index, 1)
    imgui.set_next_item_width(-1)
    changed, val = imgui.slider_int("##frame", d.cursor, 0, total)
    if changed:
        d.seek(val)
        ui.playing = False

    imgui.set_next_item_width(150)
    _, ui.speed = imgui.slider_float("fps", ui.speed, 0.5, 60.0)
    for label, kinds in (("next crit", _CRIT_KINDS), ("next boom", _BOOM_KINDS),
                         ("next kill", _KILL_KINDS)):
        imgui.same_line()
        if imgui.button(label):
            d.jump(1, lambda e, k=kinds: e.kind in k)
    imgui.same_line()
    tail = "" if d.complete else "  (+more)"
    imgui.text(f"  {ui.subtitle}   frame {d.cursor}/{d.last_index}{tail}   "
               f"round {fr.state.round}  {fr.state.phase}")


def _units(ui: UiState) -> None:
    from foosim.ui import render

    ui.selected_id = render.draw_units_panel(ui.driver.current.state, ui.selected_id)


def _stats(ui: UiState) -> None:
    from imgui_bundle import imgui

    from foosim.ui import render

    st = ui.driver.current.state
    render.draw_stats_panel(st, ui.selected_id)
    imgui.separator_text("tile")
    render.draw_tile_panel(st, ui.selected_hex, ui.selected_id)


def _log(ui: UiState) -> None:
    from imgui_bundle import imgui

    from foosim.ui import render

    imgui.set_next_item_width(200)
    _, ui.log_filter = imgui.input_text("filter", ui.log_filter)
    imgui.same_line()
    _, ui.follow_log = imgui.checkbox("follow", ui.follow_log)
    render.draw_event_log(ui.driver._frames, ui.driver.cursor, ui.log_filter,
                          ui.follow_log and ui.playing)


def _actions(ui: UiState) -> None:
    from imgui_bundle import imgui

    from foosim.engine import resolve

    if not ui.is_session:
        imgui.text_disabled("replay — no controls")
        return
    sess = ui.driver
    if not sess.at_live():
        imgui.text_disabled("viewing history — press '>> live'")
        return
    if sess.complete:
        w = sess.live.winner
        imgui.text("game over — " + ("draw" if w in (-1, None) else f"side {w} wins"))
        return
    if not sess.waiting_for_human():
        imgui.text_disabled(f"waiting for AI (side {sess.pending_side()})")
        return

    st = sess.live
    side = st.active_side

    if st.activating_unit is None:
        imgui.text(f"side {side}: choose a unit to activate")
        for u in sorted((x for x in st.units.values()
                         if x.side == side and not x.activated and not x.out_of_action),
                        key=lambda x: x.id):
            if imgui.button(f"activate {u.id}  ({u.name})"):
                sess.submit(ActivateUnit(u.id))
                ui.selected_id = u.id
        if st.pass_tokens.get(side, 0) > 0 and imgui.button("pass"):
            sess.submit(Pass())
        return

    u = st.units[st.activating_unit]
    ui.selected_id = u.id
    imgui.text(f"{u.id}: action {st.actions_taken + 1}/{ui.rules.game['actions_per_activation']}"
               f"   heat {u.heat}/{u.stat('heat_limit')}")
    _, ui.bolster = imgui.checkbox("bolster", ui.bolster)
    imgui.separator()

    engaged = _is_engaged(st, u)
    for i, w in enumerate(u.weapons):
        if w.used_this_turn or w.disabled:
            continue
        can_ranged = w.kind == "ranged" and not engaged
        if can_ranged and imgui.button(f"ranged: {w.weapon_id}##r{i}"):
            ui.action_mode, ui.pending_weapon = "targeting_ranged", i
        if w.kind == "melee" and imgui.button(f"melee: {w.weapon_id}##m{i}"):
            ui.action_mode, ui.pending_weapon = "targeting_melee", i
    if engaged:
        if imgui.button("disengage"):
            ui.action_mode, ui.pending_weapon = "targeting_disengage", None
    elif imgui.button("move"):
        ui.action_mode, ui.pending_weapon = "targeting_move", None
    if u.heat > 0 and not u.statuses.get("purged_this_turn") and imgui.button("purge heat"):
        sess.submit(PurgeHeatAction(u.id, bolster="reboot" if ui.bolster else None))
        ui.reset_targeting()
    if imgui.button("end activation"):
        sess.submit(EndActivation())
        ui.reset_targeting()

    if ui.action_mode != "idle":
        imgui.separator()
        imgui.text_colored(imgui.ImVec4(0.6, 0.85, 1.0, 1.0),
                           f"targeting: {ui.action_mode[10:]}"
                           + ("  (bolstered)" if ui.bolster else ""))
        if imgui.button("cancel"):
            ui.reset_targeting()
        _preview(ui, sess, u, resolve)


def _preview(ui: UiState, sess, u, resolve) -> None:
    from imgui_bundle import imgui

    h = ui.hover_hex
    if h is None:
        imgui.text_disabled("hover the map")
        return
    if ui.action_mode in ("targeting_move", "targeting_disengage"):
        ov = compute_overlay(sess.live, ui.rules, ui.action_mode, u.id, None, ui.bolster)
        path = ov.reachable.get(h)
        if path:
            heat = (1 if sess.live.actions_taken >= 1 else 0) + (1 if ui.bolster else 0)
            imgui.text(f"move cost {len(path) - 1}   heat +{heat}")
        else:
            imgui.text_disabled("not reachable")
        return
    tgt = sess.live.unit_at(h)
    if tgt is None or tgt.side == u.side:
        imgui.text_disabled("no target here")
        return
    kind = "ranged" if ui.action_mode == "targeting_ranged" else "melee"
    p = resolve.plan_attack(sess.live, u.id, tgt.id, ui.pending_weapon, ui.rules,
                            kind=kind, bolster=submode(ui.action_mode, ui.bolster))
    if not p.legal:
        imgui.text_colored(imgui.ImVec4(1.0, 0.5, 0.4, 1.0), p.reason or "illegal")
        return
    imgui.text(f"vs {tgt.id}:  hit {p.hit_chance * 100:.0f}%   crit {p.crit_chance * 100:.0f}%"
               f"   catastrophic {p.catastrophic_chance * 100:.0f}%")
    imgui.text(f"CS {p.effective_cs}+   save {p.save_tn}+ (AP {p.ap})"
               f"{'   cover' if p.cover else ''}{'   long range' if p.long_range else ''}")
    imgui.text(f"~{p.expected_damage_through:.1f} dmg through   heat +{p.heat_cost}")


def _is_engaged(state, u) -> bool:
    from foosim.engine.legal import is_engaged

    return is_engaged(state, u)


def _map(ui: UiState) -> None:
    from imgui_bundle import ImVec2, imgui

    from foosim.ui import render

    io = imgui.get_io()
    d = ui.driver
    fr = d.current
    st = fr.state
    avail = imgui.get_content_region_avail()
    origin = imgui.get_cursor_screen_pos()
    w, hh = max(avail.x, 10.0), max(avail.y, 10.0)

    grew = (w > ui.fit_w * 1.2 or hh > ui.fit_h * 1.2
            or w < ui.fit_w * 0.8 or hh < ui.fit_h * 0.8)
    if ui.autofit and (ui.fit_w == 0.0 or grew):
        ui.camera.fit(st.mapspec.cells(), w, hh)
        ui.fit_w, ui.fit_h = w, hh

    imgui.invisible_button("mapcanvas", ImVec2(w, hh))
    ui.hover_hex = None
    active_uid = st.activating_unit if ui.is_session else None
    overlay = None
    if active_uid and ui.action_mode != "idle" and d.at_live():
        overlay = compute_overlay(st, ui.rules, ui.action_mode, active_uid,
                                  ui.pending_weapon, ui.bolster)

    if imgui.is_item_hovered():
        mp = imgui.get_mouse_pos()
        lx, ly = mp.x - origin.x, mp.y - origin.y
        ui.hover_hex = ui.camera.screen_to_hex(lx, ly)
        if io.mouse_wheel:
            ui.camera.zoom_at(lx, ly, 1.1 if io.mouse_wheel > 0 else 1.0 / 1.1)
            ui.autofit = False
        for btn in (1, 2):
            if imgui.is_mouse_dragging(btn):
                dd = imgui.get_mouse_drag_delta(btn)
                ui.camera.pan(dd.x, dd.y)
                imgui.reset_mouse_drag_delta(btn)
                ui.autofit = False
        if imgui.is_mouse_clicked(0):
            _handle_click(ui, st, ui.hover_hex, overlay)

    render.draw_map(st, ui.camera, (origin.x, origin.y), (w, hh), ui.selected_id,
                    ui.hover_hex, overlay=overlay,
                    origin_hex=st.units[active_uid].pos if active_uid else None)


def _handle_click(ui: UiState, st, hexpos, overlay) -> None:
    unit = st.unit_at(hexpos)
    if overlay is not None and ui.is_session and ui.driver.waiting_for_human():
        sess = ui.driver
        u = st.units[st.activating_unit]
        try:
            if ui.action_mode == "targeting_move" and hexpos in overlay.reachable:
                sess.submit(MoveAction(u.id, overlay.reachable[hexpos],
                                       bolster="run" if ui.bolster else None))
                ui.reset_targeting()
                return
            if ui.action_mode == "targeting_disengage" and hexpos in overlay.reachable:
                sess.submit(DisengageAction(u.id, overlay.reachable[hexpos],
                                            bolster="dodge" if ui.bolster else None))
                ui.reset_targeting()
                return
            attacking = ui.action_mode in ("targeting_ranged", "targeting_melee")
            if attacking and unit is not None and unit.id in overlay.targets:
                is_ranged = ui.action_mode == "targeting_ranged"
                cls = RangedAttackAction if is_ranged else MeleeAttackAction
                sess.submit(cls(u.id, unit.id, ui.pending_weapon,
                                bolster=submode(ui.action_mode, ui.bolster)))
                ui.reset_targeting()
                return
        except IllegalAction:
            ui.reset_targeting()
    # plain selection
    if unit is not None:
        ui.selected_id = unit.id
        ui.selected_hex = unit.pos
    else:
        ui.selected_hex = hexpos


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def _runner_params(ui: UiState):
    from imgui_bundle import hello_imgui, imgui

    rp = hello_imgui.RunnerParams()
    rp.app_window_params.window_title = "foosim"
    rp.app_window_params.window_geometry.size = (1440, 900)
    rp.app_window_params.restore_previous_geometry = True
    rp.fps_idling.enable_idling = False
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

    def _split(initial, new, direction, ratio):
        s = hello_imgui.DockingSplit()
        s.initial_dock, s.new_dock, s.direction, s.ratio = initial, new, direction, ratio
        return s

    def _win(label, dock, fn):
        wdw = hello_imgui.DockableWindow()
        wdw.label, wdw.dock_space_name, wdw.gui_function = label, dock, fn
        return wdw

    dp = hello_imgui.DockingParams()
    dp.docking_splits = [
        _split("MainDockSpace", "TopSpace", imgui.Dir.up, 0.13),
        _split("MainDockSpace", "LeftSpace", imgui.Dir.left, 0.17),
        _split("LeftSpace", "LeftBottomSpace", imgui.Dir.down, 0.60),
        _split("MainDockSpace", "RightSpace", imgui.Dir.right, 0.28),
        _split("RightSpace", "RightBottomSpace", imgui.Dir.down, 0.62),
    ]
    dp.dockable_windows = [
        _win("Transport", "TopSpace", lambda: _toolbar(ui)),
        _win("Units", "LeftSpace", lambda: _units(ui)),
        _win("Actions", "LeftBottomSpace", lambda: _actions(ui)),
        _win("Map", "MainDockSpace", lambda: _map(ui)),
        _win("Stats", "RightSpace", lambda: _stats(ui)),
        _win("Event Log", "RightBottomSpace", lambda: _log(ui)),
    ]
    rp.docking_params = dp
    return rp


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="foosim UI")
    ap.add_argument("--replay", metavar="PATH", help="replay a saved .json")
    ap.add_argument("--play", action="store_true", help="you control side 0, AI controls side 1")
    ap.add_argument("--hotseat", action="store_true", help="both sides human")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    rules = load_rules()
    if args.replay:
        ui = build_replay(rules, args.replay)
    elif args.hotseat:
        ui = build_play(rules, args.seed, hotseat=True)
    elif args.play:
        ui = build_play(rules, args.seed, hotseat=False)
    else:
        ui = build_watch(rules, args.seed)

    try:
        from imgui_bundle import hello_imgui
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "the UI needs the 'ui' extra:  uv sync --extra ui   (then: uv run foosim-ui)"
        ) from None

    hello_imgui.run(_runner_params(ui))


if __name__ == "__main__":  # pragma: no cover
    main()
