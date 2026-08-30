"""imgui drawing for the map and panels. Imports imgui_bundle - not imported by
tests. All layout/format/camera logic lives in the pure modules; this file only
translates it into imgui calls.
"""

from __future__ import annotations

from imgui_bundle import ImVec2, ImVec4, imgui

from foosim.ui import format as fmt
from foosim.ui.camera import Camera

_GRID = (0.28, 0.30, 0.34, 1.0)
_BG = (0.10, 0.11, 0.13, 1.0)
_TERRAIN_BLOCK = (0.30, 0.31, 0.36, 1.0)
_TERRAIN_COVER = (0.22, 0.34, 0.28, 1.0)
_TERRAIN_DESTROYED = (0.16, 0.16, 0.18, 1.0)
_SELECT = (1.0, 0.92, 0.4, 1.0)
_HOVER = (0.9, 0.9, 0.95, 1.0)


def _col(rgba: tuple[float, float, float, float]) -> int:
    r, g, b, a = rgba
    return imgui.IM_COL32(int(r * 255), int(g * 255), int(b * 255), int(a * 255))


def _pts(cam: Camera, h, origin: tuple[float, float]):
    ox, oy = origin
    return [ImVec2(x + ox, y + oy) for x, y in cam.hex_corners_screen(h)]


def draw_map(state, cam: Camera, origin: tuple[float, float], size: tuple[float, float],
             selected_id: str | None, hovered_hex) -> None:
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
