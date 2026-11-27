-- See https://wiki.hypr.land/configuring/core/autostart/

local programs = require("config.programs")

-- Autostart necessary processes (like notifications daemons, status bars, etc.)
-- Or execute your favorite apps at launch like this:
hl.on("hyprland.start", function()
    -- hl.exec_cmd("hyprctl setcursor breeze_cursors 32")
    hl.exec_cmd(programs.hyprpaper)
    hl.exec_cmd(programs.waybar)
    hl.exec_cmd(programs.steam .. " -silent -steamos3")
    -- hl.exec_cmd("nm-applet")
    -- hl.exec_cmd("waybar & hyprpaper & firefox")
end)
