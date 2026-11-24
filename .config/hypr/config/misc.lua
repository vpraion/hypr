hl.config({
    render = {
      direct_scanout = 1,
    },
    misc = {
        force_default_wallpaper = -1,    -- Set to 0 or 1 to disable the anime mascot wallpapers
        disable_hyprland_logo   = false, -- If true disables the random hyprland logo / anime girl background. :(
        -- Enable VRR for all fullscreen windows (vrr in monitor config alone doesn't activate it,
        -- and XWayland games report contentType = none so vrr = 3 won't trigger).
        vrr                      = 2,
        disable_splash_rendering = true,
    },

    layers = {
        allow_new_top_layers_over_existing_fullscreen = true, -- Set to false to make newly mapped top layers render below existing covering fullscreen window
    },
})
