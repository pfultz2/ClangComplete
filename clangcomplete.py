# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# 
# Copyright (c) 2013, Paul Fultz II

import sublime, sublime_plugin

from threading import Timer, Lock
from .complete.complete import find_uses, get_completions, get_diagnostics, get_usage, get_definition, get_type, reparse, free_tu, free_all
import os, re, sys, bisect

def get_settings():
    return sublime.load_settings("ClangComplete.sublime-settings")

def get_setting(view, key, default=None):
    s = view.settings()
    if s.has("clangcomplete_%s" % key):
        return s.get("clangcomplete_%s" % key)
    return get_settings().get(key, default)

def get_project_path(view):
    return view.window().folders()[0]


def get_unsaved_buffer(view):
    buffer = None
    if view.is_dirty():
        buffer = view.substr(sublime.Region(0, view.size()))
    return buffer

#
#
# Retrieve options from cmake 
#
#
def parse_flags(f, pflags=[]):
    flags = []
    flag_set = set(pflags)
    def check_include(word):
        if word.startswith('-I') or word.startswith("-D"):
            return word not in flag_set
        else:
            return word != '-g'

    for line in open(f).readlines():
        if line.startswith('CXX_FLAGS') or line.startswith('CXX_DEFINES'):
            words = line[line.index('=')+1:].split()
            flags.extend([word for word in words if check_include(word)])
    return flags

def accumulate_options(path):
    flags = []
    for root, dirs, filenames in os.walk(path):
        for f in filenames:
            if f.endswith('flags.make'): flags.extend(parse_flags(os.path.join(root, f), flags))
    return flags

project_options = {}

def clear_options():
    global project_options
    project_options = {}

def get_options(project_path, additional_options, build_dir, default_options):
    if project_path in project_options: return project_options[project_path]

    build_dir = os.path.join(project_path, build_dir)
    if os.path.exists(build_dir):
        project_options[project_path] = ['-x', 'c++'] + accumulate_options(build_dir) + additional_options
    else:
        project_options[project_path] = ['-x', 'c++'] + default_options + additional_options

    # print(project_path, project_options[project_path])
    return project_options[project_path]

def get_args(view):
    project_path = get_project_path(view)
    additional_options = get_setting(view, "additional_options", [])
    build_dir = get_setting(view, "build_dir", "build")
    default_options = get_setting(view, "default_options", ["-std=c++11"])
    return get_options(project_path, additional_options, build_dir, default_options)

#
#
# Retrieve include files
#
#
def find_any_of(s, items):
    for item in items:
        i = s.find(item)
        if (i != -1): return i
    return -1

def bisect_right_prefix(a, x, lo=0, hi=None):
    if lo < 0:
        raise ValueError('lo must be non-negative')
    if hi is None:
        hi = len(a)
    while lo < hi:
        mid = (lo+hi)//2
        if x < a[mid] and not a[mid].startswith(x): hi = mid
        else: lo = mid+1
    return lo

def find_prefix(items, prefix):
    return items[bisect.bisect_left(items, prefix): bisect_right_prefix(items, prefix)]

project_includes = {}
includes_lock = Lock()

def clear_includes_impl():
    global project_includes
    if includes_lock.acquire(timeout=10000):
        project_includes = {}
        includes_lock.release()
    else:
        print("Can't clear includes")

def clear_includes():
    sublime.set_timeout(lambda:clear_includes_impl() , 1)

def search_include(path):
    start = len(path)
    if path[-1] is not '/': start = start + 1
    result = []
    for root, dirs, filenames in os.walk(path):
        for f in filenames:
            full_name = os.path.join(root, f)
            result.append(full_name[start:])
    return result

def find_includes(view, project_path):
    result = set()
    is_path = False
    for option in get_args(view):
        if option.startswith('-I'): result.update(search_include(option[2:]))
        if is_path: result.update(search_include(option))
        if option == '-isystem': is_path = True
        else: is_path = False 
    for path in get_setting(view, "default_include_paths", ["/usr/include", "/usr/local/include"]):
        result.update(search_include(path))
    return sorted(result)

def get_includes(view):
    global project_includes
    if includes_lock.acquire(blocking=False):
        try:
            project_path = get_project_path(view)
            if project_path not in project_includes:
                project_includes[project_path] = find_includes(view, project_path)
            result = project_includes[project_path]
        finally:
            includes_lock.release()
        return result
    else:
        print("Includes locked: return nothing")
        return []

def parse_slash(path, index):
    last = path.find('/', index)
    if last == -1: return path[index:]
    return path[index:last + 1]

def complete_includes(view, prefix):
    slash_index = prefix.rfind('/') + 1
    paths = find_prefix(get_includes(view), prefix)
    return set([parse_slash(path, slash_index) for path in paths])



#
#
# Error panel
#
#
class ClangTogglePanel(sublime_plugin.WindowCommand):
    def run(self, **args):
        show = args["show"] if "show" in args else None

        if show or (show == None and not clang_error_panel.is_visible(self.window)):
            clang_error_panel.open(self.window)
        else:
            clang_error_panel.close()


class ClangErrorPanelFlush(sublime_plugin.TextCommand):
    def run(self, edit, data):
        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, data)


class ClangErrorPanel(object):
    def __init__(self):
        self.view = None
        self.data = ""

    def set_data(self, data):
        self.data = data
        if self.is_visible(): self.flush()

    def get_view(self):
        return self.view

    def is_visible(self, window=None):
        ret = self.view != None and self.view.window() != None
        if ret and window:
            ret = self.view.window().id() == window.id()
        return ret

    def set_view(self, view):
        self.view = view

    def flush(self):
        self.view.set_read_only(False)
        self.view.set_scratch(True)
        self.view.run_command("clang_error_panel_flush", {"data": self.data})
        self.view.set_read_only(True)

    def open(self, window=None):
        if window == None:
            window = sublime.active_window()
        if not self.is_visible(window):
            self.view = window.get_output_panel("clangcomplete")
            self.view.settings().set("result_file_regex", "^(..[^:\n]*):([0-9]+):?([0-9]+)?:? (.*)$")
            self.view.set_syntax_file('Packages/ClangComplete/ErrorPanel.tmLanguage')
        self.flush()

        window.run_command("show_panel", {"panel": "output.clangcomplete"})

    def close(self):
        sublime.active_window().run_command("hide_panel", {"panel": "output.clangcomplete"})


clang_error_panel = ClangErrorPanel()

#
#
# Get language from sublime 
#
#

language_regex = re.compile("(?<=source\.)[\w+#]+")

def get_language(view):
    caret = view.sel()[0].a
    language = language_regex.search(view.scope_name(caret))
    if language == None:
        return None
    return language.group(0)


def is_supported_language(view):
    language = get_language(view)
    if language == None or (language != "c++" and
                            language != "c" and
                            language != "objc" and
                            language != "objc++"):
        return False
    return True



member_regex = re.compile(r"(([a-zA-Z_]+[0-9_]*)|([\)\]])+)((\.)|(->))$")

def convert_completion(x):
    if '\n' in x:
        c = x.split('\n', 1)
        return (c[0], c[1])
    else:
        return (x, x)

def convert_completions(completions):
    return [convert_completion(x) for x in completions]

# def is_member_completion(view, caret):
#     line = view.substr(Region(view.line(caret).a, caret))
#     if member_regex.search(line) != None:
#         return True
#     elif get_language(view).startswith("objc"):
#         return re.search(r"\[[\.\->\s\w\]]+\s+$", line) != None
#     return False

class ClangCompleteClearCache(sublime_plugin.TextCommand):
    def run(self, edit):
        sublime.status_message("Clearing cache...")
        clear_includes()
        clear_options()
        free_all()

class ClangCompleteFindUses(sublime_plugin.TextCommand):
    def run(self, edit):
        print("Find Uses")
        filename = self.view.file_name()
        # The view hasnt finsished loading yet
        if (filename is None): return

        row, col = self.view.rowcol(self.view.sel()[0].begin())
        uses = find_uses(filename, get_args(self.view), row+1, col+1, None)
        self.view.window().show_quick_panel(uses, self.on_done, sublime.MONOSPACE_FONT, 0, lambda index:self.quick_open(uses, index))

    def quick_open(self, uses, index):
        self.view.window().open_file(uses[index], sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def on_done(self):
        pass

class ClangCompleteShowUsage(sublime_plugin.TextCommand):
    def run(self, edit):
        print("Show Usages")
        filename = self.view.file_name()
        # The view hasnt finsished loading yet
        if (filename is None): return

        usage = get_usage(filename, get_args(self.view))
        data = '\n'.join([key + ": " + str(value) for key, value in usage.items()])

        panel = self.view.window().get_output_panel("clangusage")

        panel.set_read_only(False)
        panel.set_scratch(True)
        panel.erase(edit, sublime.Region(0, panel.size()))
        panel.insert(edit, 0, data)
        panel.set_read_only(True)

        self.view.window().run_command("show_panel", {"panel": "output.clangusage"})

class ClangCompleteGotoDef(sublime_plugin.TextCommand):
    def run(self, edit):
        filename = self.view.file_name()
        # The view hasnt finsished loading yet
        if (filename is None): return

        reparse(filename, get_args(self.view), get_unsaved_buffer(self.view))

        pos = self.view.sel()[0].begin()
        row, col = self.view.rowcol(pos)
        target = get_definition(filename, get_args(self.view), row+1, col+1)

        if (len(target) is 0): sublime.status_message("Cant find definition")
        else: self.view.window().open_file(target, sublime.ENCODED_POSITION)

class ClangCompleteShowType(sublime_plugin.TextCommand):
    def run(self, edit):
        filename = self.view.file_name()
        # The view hasnt finsished loading yet
        if (filename is None): return

        reparse(filename, get_args(self.view), get_unsaved_buffer(self.view))

        pos = self.view.sel()[0].begin()
        row, col = self.view.rowcol(pos)
        type = get_type(filename, get_args(self.view), row+1, col+1)

        sublime.status_message(type)

class ClangCompleteCompletion(sublime_plugin.EventListener):
    def complete_at(self, view, prefix, location, timeout):
        print("complete_at", prefix)
        filename = view.file_name()
        # The view hasnt finsished loading yet
        if (filename is None): return []
        if not is_supported_language(view):
            return []

        completions = []

        line = view.substr(view.line(location))
        row, col = view.rowcol(location - len(prefix))

        if line.startswith("#include") or line.startswith("# include"):
            start = find_any_of(line, ['<', '"'])
            if start != -1: completions = convert_completions(complete_includes(view, line[start+1:col] + prefix))
        else:
            completions = convert_completions(get_completions(filename, get_args(view), row+1, col+1, "", timeout, get_unsaved_buffer(view)))
            # completions = get_completions(filename, get_args(view), row+1, col+1, prefix, timeout, get_unsaved_buffer(view))

        return completions;

    def diagnostics(self, view):
        filename = view.file_name()  
        # The view hasnt finsished loading yet
        if (filename is None): return []      
        return [diag for diag in get_diagnostics(filename, get_args(view)) if 'unknown warning option' not in diag]

    def show_diagnostics(self, view):
        output = '\n'.join(self.diagnostics(view))
        clang_error_panel.set_data(output)
        window = view.window()
        if not window is None and len(output) > 1:
            window.run_command("clang_toggle_panel", {"show": True})


    def on_post_text_command(self, view, name, args):
        if not is_supported_language(view): return
        
        if 'delete' in name: return
        
        # TODO: Adjust position to begining of word boundary
        pos = view.sel()[0].begin()
        self.complete_at(view, "", pos, 0)
        

    def on_query_completions(self, view, prefix, locations):
        if not is_supported_language(view):
            return []
            
        completions = self.complete_at(view, prefix, locations[0], get_setting(view, "timeout", 200))
        print("on_query_completions:", prefix, len(completions))
        if (get_setting(view, "inhibit_sublime_completions", True)):
            return (completions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        else:
            return (completions)

    def on_activated_async(self, view):
        print("on_activated_async")
        if not is_supported_language(view): return
        
        print("on_activated_async: get_includes")
        get_includes(view)
        print("on_activated_async: complete_at")
        self.complete_at(view, "", view.sel()[0].begin(), 0)


    def on_post_save_async(self, view):
        if not is_supported_language(view): return
        
        self.show_diagnostics(view)
        
        pos = view.sel()[0].begin()
        self.complete_at(view, "", pos, 0)

    def on_close(self, view):
        if is_supported_language(view):
            free_tu(view.file_name())
