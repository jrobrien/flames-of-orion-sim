"""imgui drawing for the map and panels. Imports imgui_bundle - not imported by
tests. All layout/format/camera logic lives in the pure modules; this file only
translates it into imgui calls.
"""

from __future__ import annotations

import math

from imgui_bundle import ImVec2, ImVec4, imgui

from foosim.engine.hexgrid import Hex
from foosim.ui import format as fmt
from foosim.ui.camera import Camera

_GRID = (0.28, 0.30, 0.34, 1.0)
_BG = (0.10, 0.11, 0.13, 1.0)
_TERRAIN_BLOCK = (0.30, 0.31, 0.36, 1.0)
_TERRAIN_COVER = (0.22, 0.34, 0.28, 1.0)
_TERRAIN_DESTROYED = (0.16, 0.16, 0.18, 1.0)
_SELECT = (1.0, 0.92, 0.4, 1.0)
_HOVER = (0.9, 0.9, 0.95, 1.0)
_REACH = (0.32, 0.62, 0.95, 0.22)
_REACH_HOVER = (0.45, 0.80, 1.0, 0.45)
_PATH = (0.55, 0.85, 1.0, 1.0)
_TARGET = (0.98, 0.45, 0.35, 1.0)
_AIM_OK = (0.45, 0.95, 0.5, 1.0)
_ANNO_MOVE = (0.62, 0.78, 1.0, 0.85)
_ANNO_HIT = (0.98, 0.62, 0.32, 1.0)
_ANNO_MISS = (0.58, 0.58, 0.64, 0.75)
_ANNO_CRIT = (1.0, 0.86, 0.30, 1.0)
_ANNO_FREE = (0.80, 0.55, 0.95, 1.0)
_ANNO_BLAST = (1.0, 0.42, 0.14, 0.9)


def _col(rgba: tuple[float, float, float, float]) -> int:
    r, g, b, a = rgba
    return imgui.IM_COL32(int(r * 255), int(g * 255), int(b * 255), int(a * 255))


def _pts(cam: Camera, h, origin: tuple[float, float]):
    ox, oy = origin
    return [ImVec2(x + ox, y + oy) for x, y in cam.hex_corners_screen(h)]


def _center(cam: Camera, h, origin: tuple[float, float]) -> ImVec2:
    cx, cy = cam.hex_to_screen(h)
    return ImVec2(cx + origin[0], cy + origin[1])


def draw_map(state, cam: Camera, origin: tuple[float, float], size: tuple[float, float],
             selected_id: str | None, hovered_hex, *,
             overlay=None, origin_hex=None) -> None:
    dl = imgui.get_window_draw_list()
    ox, oy = origin
    w, h = size
    dl.add_rect_filled(ImVec2(ox, oy), ImVec2(ox + w, oy + h), _col(_BG))
    dl.push_clip_rect(ImVec2(ox, oy), ImVec2(ox + w, oy + h), True)

    cells = state.mapspec.cells()

    # grid
    grid_col = _col(_GRID)
    for cell in cells:
        pts = _pts(cam, cell, origin)
        for i in range(6):
            dl.add_line(pts[i], pts[(i + 1) % 6], grid_col, 1.0)

    # terrain
    for pos, t in state.terrain.items():
        pts = _pts(cam, pos, origin)
        if t.destroyed:
            fill = _TERRAIN_DESTROYED
        elif "blocking" in t.tags:
            fill = _TERRAIN_BLOCK
        elif "cover" in t.tags:
            fill = _TERRAIN_COVER
        else:
            continue
        dl.add_convex_poly_filled(pts, _col(fill))
        if "indestructible" in t.tags and not t.destroyed:
            for i in range(6):
                dl.add_line(pts[i], pts[(i + 1) % 6], _col((0.5, 0.5, 0.55, 1.0)), 2.0)

    # interaction overlay (under tokens)
    if overlay is not None and overlay.mode != "idle":
        if overlay.reachable:
            for dest in overlay.reachable:
                fill = _REACH_HOVER if dest == hovered_hex else _REACH
                dl.add_convex_poly_filled(_pts(cam, dest, origin), _col(fill))
            path = overlay.reachable.get(hovered_hex)
            if path and len(path) > 1:
                for a, b in zip(path[:-1], path[1:], strict=True):
                    dl.add_line(_center(cam, a, origin), _center(cam, b, origin), _col(_PATH), 2.5)
        for tid in overlay.targets:
            t = state.units.get(tid)
            if t is not None:
                c = _center(cam, t.pos, origin)
                dl.add_circle(c, max(6.0, cam.scale * 0.9), _col(_TARGET), 0, 2.5)
        if origin_hex is not None and hovered_hex is not None and state.unit_at(hovered_hex):
            tid = state.unit_at(hovered_hex).id
            if tid in overlay.targets:
                dl.add_line(_center(cam, origin_hex, origin),
                            _center(cam, hovered_hex, origin), _col(_AIM_OK), 2.0)

    # hovered
    if hovered_hex is not None:
        pts = _pts(cam, hovered_hex, origin)
        for i in range(6):
            dl.add_line(pts[i], pts[(i + 1) % 6], _col(_HOVER), 1.5)

    # tokens
    r = max(4.0, cam.scale * 0.62)
    for u in state.units.values():
        cx, cy = cam.hex_to_screen(u.pos)
        cx += ox
        cy += oy
        base = fmt.side_color(u.side)
        if u.out_of_action:
            base = (base[0] * 0.4, base[1] * 0.4, base[2] * 0.4, 0.5)
        dl.add_rect_filled(ImVec2(cx - r, cy - r), ImVec2(cx + r, cy + r), _col(base), 3.0)
        dl.add_rect(ImVec2(cx - r, cy - r), ImVec2(cx + r, cy + r),
                    _col((0.05, 0.05, 0.06, 1.0)), rounding=3.0, thickness=2.0)
        dl.add_text(ImVec2(cx - r + 3, cy - r + 2), _col((0.05, 0.05, 0.06, 1.0)), u.id)
        if not u.out_of_action:
            # hp bar (top) + heat bar (bottom)
            frac_hp = u.hp / max(1, u.hp_max)
            dl.add_rect_filled(
                ImVec2(cx - r, cy - r - 5),
                ImVec2(cx - r + 2 * r * frac_hp, cy - r - 2),
                _col((0.4, 0.85, 0.45, 1.0)),
            )
            frac_heat = fmt.heat_fraction(u)
            hot = (0.95, 0.55, 0.25, 1.0) if frac_heat < 0.85 else (1.0, 0.3, 0.15, 1.0)
            dl.add_rect_filled(
                ImVec2(cx - r, cy + r + 2),
                ImVec2(cx - r + 2 * r * frac_heat, cy + r + 5),
                _col(hot),
            )
        if u.id == selected_id:
            dl.add_rect(ImVec2(cx - r - 3, cy - r - 3), ImVec2(cx + r + 3, cy + r + 3),
                        _col(_SELECT), rounding=4.0, thickness=2.5)

    dl.pop_clip_rect()


def draw_units_panel(state, selected_id: str | None) -> str | None:
    new_sel = selected_id
    for side in state.sides():
        imgui.separator_text(f"Side {side}")
        for u in sorted((x for x in state.units.values() if x.side == side), key=lambda x: x.id):
            tag = f"{u.id}  {u.name}"
            if u.out_of_action:
                tag += "  [out]"
            clicked, _ = imgui.selectable(f"{tag}##{u.id}", u.id == selected_id)
            if clicked:
                new_sel = u.id
            imgui.same_line()
            imgui.text_colored(ImVec4(*fmt.side_color(u.side)),
                               f"  {u.hp}/{u.hp_max}hp {u.heat}h")
    return new_sel


def draw_stats_panel(state, selected_id: str | None) -> None:
    if selected_id is None or selected_id not in state.units:
        imgui.text_disabled("no unit selected")
        return
    u = state.units[selected_id]
    imgui.text_colored(ImVec4(*fmt.side_color(u.side)), fmt.unit_label(u))
    imgui.text(f"pos {tuple(u.pos)}  facing {u.facing}  {u.profile}")
    imgui.separator()
    for line in fmt.unit_stat_lines(u):
        imgui.text(line)


def draw_tile_panel(state, sel_hex, selected_id: str | None) -> None:
    from foosim.engine import hexgrid
    from foosim.engine.visibility import VisibilityConfig, line_of_sight

    if sel_hex is None:
        imgui.text_disabled("click an empty hex to inspect it")
        return
    col, row = hexgrid.to_offset_oddr(sel_hex)
    imgui.text(f"hex {tuple(sel_hex)}   offset (col {col}, row {row})")
    if not state.mapspec.in_bounds(sel_hex):
        imgui.text_disabled("off board")
        return
    imgui.text(f"ground elevation {state.mapspec.elevation.get(sel_hex, 0)}")
    t = state.terrain.get(sel_hex)
    if t is None:
        imgui.text("terrain: open")
    else:
        state_str = "destroyed" if t.destroyed else f"{t.damage_marks} damage marks"
        imgui.text(f"terrain: {', '.join(sorted(t.tags))}  h{t.height}  ({state_str})")
    occ = state.unit_at(sel_hex)
    imgui.text(f"occupant: {fmt.unit_label(occ) if occ else '-'}")
    if selected_id and selected_id in state.units:
        u = state.units[selected_id]
        imgui.separator()
        dist = hexgrid.distance(u.pos, sel_hex)
        los = line_of_sight(state, u.pos, sel_hex, VisibilityConfig.from_rules({}))
        note = ""
        if not los.los:
            note = f"  blocked by {tuple(los.blocked_by)}" if los.blocked_by else "  no LOS"
        elif los.cover:
            note = "  (cover)"
        imgui.text(f"from {u.id}: distance {dist}   LOS {'yes' if los.los else 'no'}{note}")


def draw_event_log(frames, cursor: int, filt: str, follow: bool) -> None:
    imgui.begin_child("log", ImVec2(0, 0))
    filt_l = filt.lower()
    for fr in frames[: cursor + 1]:
        if fr.index == 0:
            continue
        for e in fr.events:
            line = fmt.event_line(e)
            if filt_l and filt_l not in line.lower():
                continue
            imgui.text_colored(ImVec4(*fmt.event_color(e)), f"{fr.index:>3} {line}")
    if follow:
        imgui.set_scroll_here_y(1.0)
    imgui.end_child()


def _arrow(dl, p0: ImVec2, p1: ImVec2, col: int, thickness: float = 2.0) -> None:
    dl.add_line(p0, p1, col, thickness)
    dx, dy = p1.x - p0.x, p1.y - p0.y
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    head = min(11.0, length * 0.35)
    for ang in (2.4, -2.4):
        c, s = math.cos(ang), math.sin(ang)
        dl.add_line(p1, ImVec2(p1.x - (c * ux - s * uy) * head,
                               p1.y - (s * ux + c * uy) * head), col, thickness)


def draw_frame_annotations(state, cam: Camera, origin: tuple[float, float], events) -> None:
    """Transient marks for what happened on the frame in view: movement trails,
    shot / melee arrows, blast radii."""
    dl = imgui.get_window_draw_list()

    def cen(h):
        cx, cy = cam.hex_to_screen(h)
        return ImVec2(cx + origin[0], cy + origin[1])

    for e in events:
        d = e.data
        if e.kind == "move" and d.get("path") and len(d["path"]) > 1:
            pts = [cen(Hex(q, r)) for q, r in d["path"]]
            for a, b in zip(pts[:-1], pts[1:], strict=True):
                dl.add_line(a, b, _col(_ANNO_MOVE), 2.0)
            dl.add_circle_filled(pts[0], 3.5, _col(_ANNO_MOVE))
            _arrow(dl, pts[-2], pts[-1], _col(_ANNO_MOVE), 2.0)
        elif e.kind in ("attack", "free_attack"):
            atk = state.units.get(d.get("attacker"))
            tgt = state.units.get(d.get("target"))
            if not atk or not tgt:
                continue
            if e.kind == "free_attack":
                col, thick = _ANNO_FREE, 2.0
            else:
                col = {"crit": _ANNO_CRIT, "hit": _ANNO_HIT}.get(d.get("outcome"), _ANNO_MISS)
                thick = 3.5 if d.get("kind") == "melee" else 2.0
            _arrow(dl, cen(atk.pos), cen(tgt.pos), _col(col), thick)
        elif e.kind == "snap_shot":
            frm, tgt = d.get("from_hex"), state.units.get(d.get("target"))
            if frm and tgt:
                _arrow(dl, cen(Hex(*frm)), cen(tgt.pos), _col(_ANNO_HIT), 2.0)
        elif e.kind == "rail_shot":
            u = state.units.get(d.get("unit"))
            path = d.get("path") or []
            if u and path:
                pts = [cen(u.pos)] + [cen(Hex(q, r)) for q, r in path]
                for a, b in zip(pts[:-1], pts[1:], strict=True):
                    dl.add_line(a, b, _col(_ANNO_CRIT), 2.5)
        elif e.kind == "explosion":
            u = state.units.get(d.get("unit"))
            if u:
                r = max(6.0, cam.scale * (d.get("radius", 1) + 0.5))
                dl.add_circle(cen(u.pos), r, _col(_ANNO_BLAST), 0, 2.0)
