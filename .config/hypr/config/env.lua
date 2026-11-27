-- See https://wiki.hypr.land/configuring/core/environment-variables/

hl.env("XCURSOR_THEME", "breeze_cursors")
hl.env("XCURSOR_SIZE", "32")

-- Native Wayland & HDR for Proton games (isolated to the Hyprland session;
-- automatically cleared on logout so it never leaks into Gamescope TV mode)
hl.env("PROTON_ENABLE_WAYLAND", "1")
hl.env("PROTON_ENABLE_HDR", "1")
