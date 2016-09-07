# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# 
# Copyright (c) 2013, Paul Fultz II

import sublime, sublime_plugin

from threading import Timer, Lock
from .complete.complete import find_uses, get_completions, get_diagnostics, get_definition, get_type, reparse, free_tu, free_all
import os, re, sys, bisect, json, fnmatch, functools

def get_settings():
    return sublime.load_settings("ClangComplete.sublime-settings")

def get_setting(view, key, default=None):
    s = view.settings()
    if s.has("clangcomplete_%s" % key):
        return s.get("clangcomplete_%s" % key)
    return get_settings().get(key, default)

def get_project_path(view):
    try:
        return view.window().folders()[0]
    except:
        pass
    return ""


def get_unsaved_buffer(view):
    buffer = None
    if view.is_dirty():
        buffer = view.substr(sublime.Region(0, view.size()))
    return buffer

def debug_print(*args):
    if get_settings().get("debug", False): print(*args)

#
#
# Retrieve options from cmake 
#
#
def parse_flags(f):
    flags = []
    for line in open(f).readlines():
        if line.startswith('CXX_FLAGS') or line.startswith('CXX_DEFINES') or line.startswith('CXX_INCLUDES'):
            words = line[line.index('=')+1:].split()
            flags.extend([word for word in words if not word.startswith('-g')])
    return flags

def canonicalize_path(path, root):
    if path.startswith('-I'): return '-I'+os.path.normpath(os.path.join(root, path[2:])) # rel or abs path
    else: return path

def parse_compile_commands(root, f):
    flags = []
    compile_commands = json.load(open(os.path.join(root, f)))
    for obj in compile_commands:
        for key, value in obj.items():
            if key == "command":
                for string in value.split()[1:]:
                    if string.startswith(('-o', '-c')): break
                    if not string.startswith('-g'):
                        # ninja adds local paths as -I. and -I..
                        # make adds full paths as i flags
                        flags.append(canonicalize_path(string, root))
    return flags

def merge_flags(flags, pflags):
    result = []
    def append_result(f):
        if f.startswith(('-I', '-D', '-isystem', '-include', '-isysroot', '-W', '-std', '-pthread', '-f', '-pedantic', '-arch', '-m')):
            if f not in pflags and f not in result: result.append(f)
        elif not f.startswith(('-O')): result.append(f)
    flags_to_merge = ['-isystem', '-include', '-isysroot', '-arch']
    prev_flag = ""
    for f in flags:
        if len(prev_flag) > 0:
            append_result(prev_flag + ' ' + f)
            prev_flag = ""
        elif f in flags_to_merge: prev_flag = f
        else: append_result(f)
    return result

def filter_flag(f, exclude_options):
    for pat in exclude_options:
        if fnmatch.fnmatch(f, pat): return False
    return True

ordered_std_flags = ['-std=c++0x', '-std=gnu++0x', '-std=c++11', '-std=gnu++11', '-std=c++1y', '-std=gnu++1y', '-std=c++14', '-std=gnu++14', '-std=c++1z', '-std=gnu++1z', '-std=c++17', '-std=gnu++17']
def find_index(l, elem):
    for i,x in enumerate(l): 
        if x == elem: return i
    return -1

def std_flag_rank(x):
    return find_index(ordered_std_flags, x)


def max_std(x, y):
    if (std_flag_rank(x) > std_flag_rank(y)): return x
    else: return y

def split_flags(flags, exclude_options):
    result = []
    std_flags = []
    for f in flags:
        if f.startswith('-std'): std_flags.append(f)
        elif filter_flag(f, exclude_options): result.extend(f.split())
    if len(std_flags) > 0: result.append(functools.reduce(max_std, std_flags))
    return result

def accumulate_options(path, exclude_options):
    flags = []
    for root, dirs, filenames in os.walk(path):
        for f in filenames:
            if f.endswith('compile_commands.json'):
               flags.extend(merge_flags(parse_compile_commands(root, f), flags))
               return split_flags(flags, exclude_options)
            if f.endswith('flags.make'): 
                flags.extend(merge_flags(parse_flags(os.path.join(root, f)), flags))
    return split_flags(flags, exclude_options)

project_options = {}

def clear_options():
    global project_options
    project_options = {}

def get_build_dir(view):
    result = get_setting(view, "build_dir", ["build"])
    if isinstance(result, str): return [result]
    else: return result 

def get_options(project_path, additional_options, exclude_options, build_dirs, default_options):
    if project_path in project_options: return project_options[project_path]

    build_dir = next((build_dir for d in build_dirs for build_dir in [os.path.join(project_path, d)] if os.path.exists(build_dir)), None)
    if build_dir != None:
        project_options[project_path] = ['-x', 'c++'] + accumulate_options(build_dir, exclude_options) + additional_options
    else:
        project_options[project_path] = ['-x', 'c++'] + default_options + additional_options

    # debug_print(project_path, project_options[project_path])
    return project_options[project_path]

def get_args(view):
    project_path = get_project_path(view)
    additional_options = get_setting(view, "additional_options", [])
    exclude_options = get_setting(view, "exclude_options", [])
    build_dir = get_build_dir(view)
    default_options = get_setting(view, "default_options", ["-std=c++11"])
    debug_print(get_options(project_path, additional_options, exclude_options, build_dir, default_options))
    return get_options(project_path, additional_options, exclude_options, build_dir, default_options)

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
        debug_print("Can't clear includes")

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
    result = []
    if includes_lock.acquire(blocking=False):
        try:
            project_path = get_project_path(view)
            if project_path not in project_includes:
                project_includes[project_path] = find_includes(view, project_path)
            result = project_includes[project_path]
        except:
            pass
        finally:
            includes_lock.release()
    else:
        debug_print("Includes locked: return nothing")
    return result

def parse_slash(path, index):
    last = path.find('/', index)
    if last == -1: return path[index:]
    return path[index:last + 1]

def complete_includes(view, prefix):
    slash_index = prefix.rfind('/') + 1
    paths = find_prefix(get_includes(view), prefix)
    return sorted(set([parse_slash(path, slash_index) for path in paths]))



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

def is_view_visible(view, window=None):
    ret = view != None and view.window() != None
    if ret and window:
        ret = view.window().id() == window.id()
    return ret

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
        return is_view_visible(self.view, window)

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
    try:
        caret = view.sel()[0].a
        language = language_regex.search(view.scope_name(caret))
        if language == None:
            return None
        return language.group(0)
    except:
        return None

def is_supported_language(view):
    language = get_language(view)
    if language == None or (language != "c++" and
                            language != "c" and
                            language != "objc" and
                            language != "objc++"):
        return False
    return True



member_regex = re.compile(r"(([a-zA-Z_]+[0-9_]*)|([\)\]])+)((\.)|(->))$")
not_code_regex = re.compile("(string.)|(comment.)")

def convert_completion(x):
    if '\n' in x:
        c = x.split('\n', 1)
        return (c[0], c[1])
    else:
        return (x, x)

def convert_completions(completions):
    return [convert_completion(x) for x in completions]

# def is_member_completion(view, caret):
#     line = view.substr(sublime.Region(view.line(caret).a, caret))
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
        debug_print("Find Uses")
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

class ClangCompleteComplete(sublime_plugin.TextCommand):
    def show_complete(self):
        self.view.run_command("hide_auto_complete")
        sublime.set_timeout(lambda: self.view.run_command("auto_complete"), 1)

    def run(self, edit, characters):
        debug_print("ClangCompleteComplete")
        regions = [a for a in self.view.sel()]
        self.view.sel().clear()
        for region in reversed(regions):
            pos = 0
            region.end() + len(characters)
            if region.size() > 0:
                self.view.replace(edit, region, characters)
                pos = region.begin() + len(characters)
            else:
                self.view.insert(edit, region.end(), characters)
                pos = region.end() + len(characters)

            self.view.sel().add(sublime.Region(pos, pos))
        caret = self.view.sel()[0].begin()
        word = self.view.substr(self.view.word(caret)).strip()
        debug_print("Complete", word)
        triggers = ['->', '::', '.']
        if word in triggers:
            debug_print("Popup completions")
            self.show_complete()

build_panel_window_id = None

def is_build_panel_visible(window):
    return build_panel_window_id != None and window != None and window.id() == build_panel_window_id

class ClangCompleteAutoComplete(sublime_plugin.EventListener):
    def complete_at(self, view, prefix, location, timeout):
        debug_print("complete_at", prefix)
        filename = view.file_name()
        # The view hasnt finsished loading yet
        if (filename is None): return []
        if not is_supported_language(view):
            return []

        completions = []

        line = view.substr(view.line(location))

        if line.startswith("#include") or line.startswith("# include"):
            row, col = view.rowcol(location - len(prefix))
            start = find_any_of(line, ['<', '"'])
            if start != -1: completions = convert_completions(complete_includes(view, line[start+1:col] + prefix))
        else:
            r = view.word(location - len(prefix))
            word = view.substr(r)
            # Skip completions for single colon or dash, since we want to
            # optimize for completions after the `::` or `->` characters
            if word == ':' or word == '-': return []
            p = 0
            if re.match('^\w+$', word):  p = r.begin()
            else: p = r.end() - 1
            row, col = view.rowcol(p)
            # debug_print("complete: ", row, col, word)
            completions = convert_completions(get_completions(filename, get_args(view), row+1, col+1, "", timeout, get_unsaved_buffer(view)))

        return completions


    def diagnostics(self, view):
        filename = view.file_name()  
        # The view hasnt finsished loading yet
        if (filename is None): return []
        diagnostics = get_diagnostics(filename, get_args(view))
        # If there are errors in the precompiled headers, then we will free
        # the tu, and reload the diagnostics
        for diag in diagnostics:
            if "has been modified since the precompiled header" in diag or "modified since it was first processed" in diag:
                free_tu(filename)
                diagnostics = get_diagnostics(filename, get_args(view))
                break
        return [diag for diag in diagnostics if "#pragma once in main file" not in diag]

    def show_diagnostics(self, view):
        output = '\n'.join(self.diagnostics(view))
        clang_error_panel.set_data(output)
        window = view.window()
        if not window is None and len(output) > 1:
            window.run_command("clang_toggle_panel", {"show": True})

    def on_window_command(self, window, command_name, args):
        global build_panel_window_id
        debug_print(command_name, args)
        if command_name == 'show_panel' and args['panel'] == 'output.exec':
            if 'toggle' in args and args['toggle'] == True and build_panel_window_id != None: build_panel_window_id=None
            else: build_panel_window_id = window.id()
        if command_name == 'hide_panel':
            if build_panel_window_id != None or args != None and ('panel' in args and args['panel'] == 'output.exec'):
                build_panel_window_id = None
        return None


    def on_post_text_command(self, view, name, args):
        if not is_supported_language(view): return
        
        if 'delete' in name: return
        
        pos = view.sel()[0].begin()
        self.complete_at(view, "", pos, 0)
        

    def on_query_completions(self, view, prefix, locations):
        if not is_supported_language(view):
            return []
            
        completions = self.complete_at(view, prefix, locations[0], get_setting(view, "timeout", 200))
        debug_print("on_query_completions:", prefix, len(completions))
        if (get_setting(view, "inhibit_sublime_completions", True)):
            return (completions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        else:
            return (completions)

    def on_activated_async(self, view):
        debug_print("on_activated_async")
        if not is_supported_language(view): return
        
        debug_print("on_activated_async: get_includes")
        get_includes(view)
        debug_print("on_activated_async: complete_at")
        self.complete_at(view, "", view.sel()[0].begin(), 0)


    def on_post_save_async(self, view):
        if not is_supported_language(view): return

        show_panel = None
        show_diagnostics_on_save = get_setting(view, "show_diagnostics_on_save", "no_build")
        if show_diagnostics_on_save == 'always': show_panel = True
        elif show_diagnostics_on_save == 'never': show_panel = False
        else: show_panel = not is_build_panel_visible(view.window())
        
        if show_panel: self.show_diagnostics(view)
        
        pos = view.sel()[0].begin()
        self.complete_at(view, "", pos, 0)

    def on_close(self, view):
        if is_supported_language(view):
            free_tu(view.file_name())

    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "clangcomplete_supported_language":
            if view == None: view = sublime.active_window().active_view()
            return is_supported_language(view)
        elif key == "clangcomplete_is_code":
            return not_code_regex.search(view.scope_name(view.sel()[0].begin())) == None
        elif key == "clangcomplete_panel_visible":
            return clang_error_panel.is_visible()
