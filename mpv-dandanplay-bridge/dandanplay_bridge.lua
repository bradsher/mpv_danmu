-- MPV front-end for dandanplay_bridge.py.
-- The Python side owns credentials, HTTP, caching and ASS generation.

local mp = require("mp")
local msg = require("mp.msg")
local utils = require("mp.utils")
local options = require("mp.options")

local opt = {
    python_command = "python",
    auto_load = true,
    load_delay_seconds = 1,
}
options.read_options(opt, "dandanplay_bridge")

local script_path = mp.get_script_file()
local script_directory = utils.split_path(script_path)
local bridge_path = utils.join_path(script_directory, "dandanplay_bridge.py")
local config_path = utils.join_path(script_directory, "dandanplay_bridge.json")
local current_sub_id = nil
local selection_bindings = {}

local function osd(text, duration)
    mp.osd_message("[弹弹play] " .. text, duration or 4)
end

local function trim_extension(value)
    return (value:gsub("%.[^%.]+$", ""))
end

local function local_video_path()
    local path = mp.get_property("path")
    if not path or path:match("^%a[%w+.-]*://") then
        return nil
    end
    return path
end

local function invoke(arguments, callback)
    local command = { opt.python_command, bridge_path, "--config", config_path }
    for _, value in ipairs(arguments) do table.insert(command, tostring(value)) end
    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        capture_stdout = true,
        capture_stderr = true,
        args = command,
    }, function(success, result, error)
        if not success or not result then
            osd("启动辅助程序失败：" .. tostring(error or "未知错误"), 6)
            return
        end
        local data = utils.parse_json(result.stdout or "")
        if not data then
            msg.error("bridge returned: " .. tostring(result.stdout) .. " / " .. tostring(result.stderr))
            osd("辅助程序没有返回有效结果；请在终端运行 MPV 查看日志", 7)
            return
        end
        callback(data)
    end)
end

local function remove_selection_bindings()
    for _, name in ipairs(selection_bindings) do mp.remove_key_binding(name) end
    selection_bindings = {}
end

local function load_ass(data)
    if not data.ok then
        osd(data.message or "加载失败", 6)
        return
    end
    local path = data.ass_path
    if not path or path == "" then
        osd("未生成 ASS 弹幕文件", 6)
        return
    end
    if current_sub_id then
        mp.commandv("sub-remove", tostring(current_sub_id))
    end
    mp.commandv("sub-add", path, "select")
    current_sub_id = mp.get_property_number("sid")
    local title = data.anime_title or ""
    local episode = data.episode_title or ""
    osd(string.format("已加载 %s%s（%d 条）", title, episode ~= "" and " · " .. episode or "", tonumber(data.count) or 0), 5)
end

local function fetch_episode(episode_id, force)
    osd("正在获取弹幕…", 30)
    local args = { "fetch", "--episode-id", episode_id }
    if force then table.insert(args, "--force") end
    invoke(args, load_ass)
end

local function show_candidates(data)
    if not data.ok then
        osd(data.message or "搜索失败", 6)
        return
    end
    local candidates = data.candidates or {}
    if #candidates == 0 then
        osd("没有找到候选集。可在 MPV 控制台执行：script-message dandanplay-search 剧名", 7)
        return
    end
    remove_selection_bindings()
    local lines = { "候选集（按数字键 1–" .. tostring(#candidates) .. " 选择，Esc 取消）：" }
    for index, candidate in ipairs(candidates) do
        table.insert(lines, string.format("%d. %s · %s", index, candidate.anime_title or "", candidate.episode_title or ""))
        local name = "dandanplay_pick_" .. index
        table.insert(selection_bindings, name)
        mp.add_forced_key_binding(tostring(index), name, function()
            local chosen = candidates[index]
            remove_selection_bindings()
            fetch_episode(chosen.episode_id, false)
        end)
    end
    mp.add_forced_key_binding("ESC", "dandanplay_cancel_pick", function()
        remove_selection_bindings()
        osd("已取消选择", 2)
    end)
    table.insert(selection_bindings, "dandanplay_cancel_pick")
    osd(table.concat(lines, "\n"), 15)
end

local function search(query)
    query = query or trim_extension(mp.get_property("filename") or "")
    if query == "" then
        osd("没有可用于搜索的文件名", 4)
        return
    end
    osd("正在搜索候选剧集…", 30)
    invoke({ "search", "--query", query }, show_candidates)
end

local function fetch_current(force)
    local path = local_video_path()
    if not path then
        osd("这个插件目前只处理本地视频文件", 4)
        return
    end
    osd("正在识别视频并获取弹幕…", 30)
    local args = { "fetch", "--file", path }
    if force then table.insert(args, "--force") end
    invoke(args, load_ass)
end

mp.register_event("file-loaded", function()
    current_sub_id = nil
    if opt.auto_load then
        mp.add_timeout(tonumber(opt.load_delay_seconds) or 1, function() fetch_current(false) end)
    end
end)

mp.add_key_binding("Ctrl+d", "dandanplay_search_filename", function() search(nil) end)
mp.add_key_binding("Ctrl+Shift+d", "dandanplay_reload", function() fetch_current(true) end)
mp.register_script_message("dandanplay-search", function(query) search(query) end)
mp.register_script_message("dandanplay-reload", function() fetch_current(true) end)
