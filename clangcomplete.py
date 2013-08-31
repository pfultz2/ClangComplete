import sublime, sublime_plugin
from threading import RLock
from threading import Timer
from threading import Condition

from .clang.cindex import Index
from .clang.cindex import TranslationUnit
from .clang.cindex import Diagnostic
from .clang.cindex import Cursor
from .clang.cindex import CursorKind
from .clang.cindex import SourceLocation

from ctypes import cdll
from ctypes import POINTER
from ctypes import c_char_p
from ctypes import create_unicode_buffer
from ctypes import create_string_buffer
import os, re, sys



class LockedVariable(object):
    def __init__(self, value, lock=None):
        self._value = value
        self._lock = lock if lock else RLock()
        self._locked = False

    @property
    def locked(self):
        return self._locked

    def assign(self, value):
        with self:
            self._value = value

    def __enter__(self):
        self._lock.__enter__()
        self._locked = True
        return self._value

    def __exit__(self, *args, **kwargs):
        self._locked = False
        return self._lock.__exit__(*args, **kwargs)

def try_call(callback):
    try:
        return callback()
    except:
        return None

class Future(object):
    """Represents the result of an asynchronous computation."""

    PENDING                = 1
    RUNNING                = 2
    FINISHED               = 5

    def __init__(self):
        self._condition = Condition()
        self._state = Future.PENDING
        self._exception = None
        self._result = None

    def valid(self):
        with self._condition:
            return self._state != Future.PENDING

    def running(self):
        with self._condition:
            return self._state == Future.RUNNING

    def done(self, timeout=None):
        print("done")
        if timeout != None:
            with self._condition:
                if self._state != Future.FINISHED: 
                    print("done.wait", timeout*0.001)
                    self._condition.wait(timeout*0.001)
                    print("done:", self._state)
        with self._condition:
            print("Finished")
            return self._state == Future.FINISHED

    def result(self, timeout=None):
        print("result")
        with self._condition:
            if self._state == Future.FINISHED:
                return self.__get_result()
            print("result.wait", timeout*0.001)
            self._condition.wait(timeout*0.001)
            print("result:", self._state)
            if self._state == Future.FINISHED:
                return self.__get_result()
            else:
                return None

    def __get_result(self):
        print("__get_result", self._exception)
        if self._exception != None:
            print("Throw exception")
            raise self._exception
        else:
            return self._result

    def set_running(self):
        with self._condition:
            if self._state == Future.PENDING:
                self._state = Future.RUNNING
                return True
            else:
                raise RuntimeError('Future in unexpected state')

    def set_result(self, result, exception):
        with self._condition:
            print("set_result")
            self._result = result
            self._exception = exception
            self._state = Future.FINISHED
            print("Notify")
            self._condition.notify_all()


class Worker(object):
    def __init__(self, f, callback):
        self.f = f
        self.callback = callback

    def run(self):
        self.f.set_running()
        result = None
        exception = None
        try:
            result = self.callback()
        except Exception as e:
            print("Exception thrown", e)
            exception = e
        self.f.set_result(result, exception)

def async_timeout(callback, delay):
    f = Future()
    w = Worker(f, callback)
    sublime.set_timeout_async(w.run, delay)
    return f


def get_typed_text(result):
    # print("get_typed_text start")
    # print(result.kind)
    # return ""
    # print(result.obj)
    print("completionString", result.completionString)
    print("completionString obj", result.string.obj)
    print("completionString len", len(result.string))
    for chunk in result.string:
        if chunk.isKindTypedText():
            return chunk.spelling

def format_severity(severity):
    if severity is Diagnostic.Note: return "note"
    elif severity is Diagnostic.Warning: return "warning"
    elif severity is Diagnostic.Error: return "error"
    elif severity is Diagnostic.Fatal: return "fatal error"

def format_diagnostic(diag):
    f = diag.location
    filename = ""
    if f.file != None:
        filename = f.file.name

    return "%s:%d:%d: %s: %s" % (filename.decode("utf-8"), f.line, f.column,
                                  format_severity(diag.severity),
                                  diag.spelling.decode("utf-8"))

def format_cursor_location(cursor):
    return "%s:%d:%d" % (cursor.location.file.name, cursor.location.line,
                         cursor.location.column)


class Unit(object):
    def __init__(self, filename, args):
        self.filename = filename
        if filename is None: self.filename = ""
        self.index = Index.create()
        self.tu = self.index.parse(self.filename, args, None, TranslationUnit.PARSE_PRECOMPILED_PREAMBLE | TranslationUnit.PARSE_CACHE_COMPLETION_RESULTS)

    def reparse(self, buffer=None):
        if buffer is None: self.tu.reparse()
        else: self.tu.reparse([(self.filename, buffer)])

    def complete_at(self, line, col, buffer=None):
        print("complete_at_start")
        unsaved_files = None
        if buffer is not None: unsaved_files = [(self.filename, buffer)]
        completions = set()
        results = self.tu.codeComplete(self.filename, line, col, unsaved_files, True).results
        print("results", len(results))
        # print("results availability", str(results[0].string.availability))
        # for completion in [get_typed_text(result) for result in results if str(result.string.availability) == "Available"]:
        for completion in [get_typed_text(result) for result in results]:
            completions.add(completion)
        print("complete_at:", len(completions))
        return completions

    def get_diagnostics(self):
        return [format_diagnostic(diag) for diag in self.tu.diagnostics if diag != None and diag.severity != Diagnostic.Ignored]
        # result = [format_diagnostic(diag) for diag in self.tu.diagnostics if diag != None and diag.severity != Diagnostic.Ignored]
        # return result
        # print("get_diagnostics", len(result))

    def cursor_at(self, line, col):
        return Cursor.from_location(self.tu, SourceLocation.from_position(self.tu, self.filename, line, col))

    def get_definition(self, line, col):
        c = self.cursor_at(line, col)
        cursor_ref = c.referenced
        if cursor_ref != None:
            return format_cursor_location(cursor_ref)
        # elif c.kind == CursorKind.INCLUSION_DIRECTIVE:
        #     return c.get_included_file()
        return ""

def get_sync_completions(locked_tu, line, col, buffer):
    with locked_tu as tu:
        tu.complete_at(line, col, buffer)


class Query(object):
    def __init__(self):
        self.future = Future()
        self.filename = ''
        self.line = 0
        self.col = 0

    def set(self, future, filename, line, col):
        self.future = future
        self.filename = filename
        self.line = line
        self.col = col

    def ready(self, timeout=10):
        if self.future.valid(): return timeout > 0 and self.future.done(timeout)
        else: return True

    def get(self, timeout):
        result = self.future.result(timeout)
        if result is None: return []
        else: return result

    def get_completions(self, locked_tu, filename, line, col, prefix, timeout, buffer=None):
        if ((filename, line, col) != (self.filename, self.col, self.line)):
            # If we are busy with a query, lets avoid making lots of new queries
            if not self.ready(): 
                print("Busy")
                return []
            self.set(async_timeout(lambda: get_sync_completions(locked_tu, line, col, buffer), 1), filename, line, col)
        print("get_completions:", timeout)
        completions = self.get(timeout)
        return [completion for completion in completions if completion.startswith(prefix)]

completion_query = LockedVariable(Query())

tus = LockedVariable({})

def get_tu(filename, args):
    with tus as d:
        if filename not in d: d[filename] = LockedVariable(Unit(filename, args))
        return d[filename]

def free_tu(filename):
    with tus as d:
        if filename in d: del d[filename]

def free_all():
    with tus as d:
        d.clear()

def reparse(filename, args, buffer):
    with get_tu(filename, args) as tu:
        tu.reparse(buffer)

# def get_completions(filename, args, line, col, prefix, timeout, buffer):
#     if completion_query.locked: return []
#     with completion_query as q:
#         return q.get_completions(get_tu(filename, args), filename, line, col, prefix, timeout, buffer)

def get_completions(filename, args, line, col, prefix, timeout, buffer):
    with get_tu(filename, args) as tu:
        return tu.complete_at(line, col, buffer)

def get_diagnostics(filename, args):
    with get_tu(filename, args) as tu:
        tu.reparse()
        return tu.get_diagnostics()

def get_definition(filename, args, line, col):
    with get_tu(filename, args) as tu:
        return tu.get_definition(line, col)

# TODO
def get_type(filename, args, line, col):
    with get_tu(filename, args) as tu:
        return tu.get_definition(line, col)



#
#
# Clang c api wrapper
#
#
# current_path = os.path.dirname(os.path.abspath(__file__))
# complete = cdll.LoadLibrary('%s/complete/libcomplete.so' % current_path)

# complete.clang_complete_get_completions.restype = POINTER(c_char_p)
# complete.clang_complete_get_diagnostics.restype = POINTER(c_char_p)
# complete.clang_complete_get_definition.restype = c_char_p
# complete.clang_complete_get_type.restype = c_char_p

# def convert_to_c_string_array(a):
#     result = (c_char_p * len(a))()
#     result[:] = [x.encode('utf-8') for x in a]
#     return result

# def convert_from_c_string_array(a):
#     results = []
#     i = 0
#     while(len(a[i]) is not 0):
#         results.append(a[i].decode("utf-8"))
#         i = i + 1
#     return results

# def get_completions(filename, args, line, col, prefix, timeout, unsaved_buffer):
#     buffer = None
#     if (unsaved_buffer is not None): buffer = unsaved_buffer.encode("utf-8")
#     buffer_len = 0
#     if (buffer is not None): buffer_len = len(buffer)

#     results = complete.clang_complete_get_completions(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col, prefix.encode('utf-8'), timeout, buffer, buffer_len)
#     return convert_from_c_string_array(results)

# def get_diagnostics(filename, args):
#     results = complete.clang_complete_get_diagnostics(filename.encode('utf-8'), convert_to_c_string_array(args), len(args))
#     return convert_from_c_string_array(results)

# def get_definition(filename, args, line, col):
#     result = complete.clang_complete_get_definition(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col)
#     return result.decode("utf-8")

# def get_type(filename, args, line, col):
#     result = complete.clang_complete_get_type(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col)
#     return result.decode("utf-8")

# def reparse(filename, args, unsaved_buffer):
#     buffer = None
#     if (unsaved_buffer is not None): buffer = unsaved_buffer.encode("utf-8")
#     buffer_len = 0
#     if (buffer is not None): buffer_len = len(buffer)

#     complete.clang_complete_reparse(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), buffer, buffer_len)

# def free_tu(filename):
#     complete.clang_complete_free_tu(filename.encode('utf-8'))

# def free_all():
#     complete.clang_complete_free_all()




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

def get_options(project_path, additional_options, build_dir, default_options):
    if project_path in project_options: return project_options[project_path]

    build_dir = os.path.join(project_path, build_dir)
    if os.path.exists(build_dir):
        project_options[project_path] = ['-x', 'c++'] + accumulate_options(build_dir) + additional_options
    else:
        project_options[project_path] = ['-x', 'c++'] + default_options + additional_options

    # print(project_path, project_options[project_path])
    return project_options[project_path]

#
#
# Retrieve include files
#
#

project_includes = {}

def search_include(path):
    start = len(path)
    if path[-1] is not '/': start = start + 1
    result = []
    for root, dirs, filenames in os.walk(path):
        for f in filenames:
            full_name = os.path.join(root, f)
            result.append(full_name[start:])
    return result

def find_includes(project_path):
    result = set()
    is_path = False
    for option in get_options(project_path):
        if option == '-isystem': is_path = True
        else: is_path = False 
        if option.startswith('-I'): result.update(search_include(option[2:]))
        if is_path: result.update(search_include(option))
    project_includes[project_path] = sorted(result)

def complete_includes(project_path, prefix):
    pass


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

# def is_member_completion(view, caret):
#     line = view.substr(Region(view.line(caret).a, caret))
#     if member_regex.search(line) != None:
#         return True
#     elif get_language(view).startswith("objc"):
#         return re.search(r"\[[\.\->\s\w\]]+\s+$", line) != None
#     return False

def get_settings():
    return sublime.load_settings("ClangComplete.sublime-settings")

def get_setting(view, key, default=None):
    try:
        s = view.settings()
        if s.has("clangcomplete_%s" % key):
            return s.get("clangcomplete_%s" % key)
    except:
        pass
    return get_settings().get(key, default)

def get_args(view):
    project_path = view.window().folders()[0]
    additional_options = get_setting(view, "additional_options", [])
    build_dir = get_setting(view, "build_dir", "build")
    default_options = get_setting(view, "default_options", ["-std=c++11"])
    return get_options(project_path, additional_options, build_dir, default_options)

def get_unsaved_buffer(view):
    buffer = None
    if view.is_dirty():
        buffer = view.substr(sublime.Region(0, view.size()))
    return buffer

class ClangCompleteClearCache(sublime_plugin.TextCommand):
    def run(self, edit):
        global project_options
        sublime.status_message("Clearing cache...")
        project_options = {}
        free_all()

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
        if not get_setting(view, "enable_completions", True): return []
        print("clang_complete_at", prefix)
        filename = view.file_name()
        if not is_supported_language(view):
            return []

        row, col = view.rowcol(location - len(prefix))

        # completions = get_completions(filename, get_args(view), row+1, col+1, "", timeout, unsaved_buffer)
        completions = get_completions(filename, get_args(view), row+1, col+1, prefix, timeout, get_unsaved_buffer(view))

        return completions;

    def diagnostics(self, view):
        if not get_setting(view, "enable_diagnostics", True): return []
        filename = view.file_name()   
        result = get_diagnostics(filename, get_args(view))
        print("Diagnostics: ", len(result))
        return result

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
            return ([(c, c) for c in completions], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        else:
            return ([(c, c) for c in completions])

    def on_activated_async(self, view):
        self.complete_at(view, "", view.sel()[0].begin(), 0)

    def on_post_save_async(self, view):
        if not is_supported_language(view): return
        
        self.show_diagnostics(view)
        
        pos = view.sel()[0].begin()
        self.complete_at(view, "", pos, 0)

    def on_close(self, view):
        if is_supported_language(view):
            free_tu(view.file_name())