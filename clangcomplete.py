import sublime, sublime_plugin

from threading import Timer

from ctypes import cdll
from ctypes import POINTER
from ctypes import c_char_p
from ctypes import create_unicode_buffer
from ctypes import create_string_buffer
import os, re, sys
current_path = os.path.dirname(os.path.abspath(__file__))
complete = cdll.LoadLibrary('%s/complete/libcomplete.so' % current_path)

# sys.stdout
class RedirectStdStreams(object):
    def __init__(self, stdout=None, stderr=None):
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr

    def __enter__(self):
        self.old_stdout, self.old_stderr = sys.stdout, sys.stderr
        self.old_stdout.flush(); self.old_stderr.flush()
        sys.stdout, sys.stderr = self._stdout, self._stderr

    def __exit__(self, exc_type, exc_value, traceback):
        self._stdout.flush(); self._stderr.flush()
        sys.stdout = self.old_stdout
        sys.stderr = self.old_stderr




# complete = cdll.LoadLibrary('./complete/libcomplete.so')
complete.clang_complete_get_completions.restype = POINTER(c_char_p)

def convert_to_c_string_array(a):
    result = (c_char_p * len(a))()
    result[:] = [x.encode('utf-8') for x in a]
    return result

def get_completions(filename, args, line, col, prefix, timeout, unsaved_buffer):
    buffer = None
    if (unsaved_buffer is not None): buffer = unsaved_buffer.encode("utf-8")
    buffer_len = 0
    if (buffer is not None): buffer_len = len(buffer)
    with RedirectStdStreams(stderr=sys.stdout):
        res = complete.clang_complete_get_completions(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col, prefix.encode('utf-8'), timeout, buffer, buffer_len)
    results = []
    i = 0
    while(len(res[i]) is not 0):
        results.append(res[i].decode("utf-8"))
        i = i + 1
    return results

def free_tu(filename):
    complete.clang_complete_free_tu(filename.encode('utf-8'))


def parse_flags(f):
    flags = []
    data = open(f).readlines()
    whitespace = re.compile('\s')
    for line in open(f).readlines():
        if line.startswith('CXX_FLAGS') or line.startswith('CXX_DEFINES'):
            flags.extend(line[line.index('=')+1:].split())
    return flags

def accumulate_options(path):
    flags = []
    for root, dirs, filenames in os.walk(path):
        for f in filenames:
            if f.endswith('flags.make'): flags.extend(parse_flags(os.path.join(root, f)))
    return flags

project_options = {}

def get_options(project_path):
    if project_path in project_options: return project_options[project_path]

    build_dir = os.path.join(project_path, "build")
    if os.path.exists(build_dir):
        project_options[project_path] = accumulate_options(build_dir)
    else:
        project_options[project_path] = ["-std=c++11"]
    return project_options[project_path]


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

timer = None

class ClangCompleteCompletion(sublime_plugin.EventListener):
    def complete_at(self, view, prefix, location, timeout, args=[]):
        filename = view.file_name()
        if not is_supported_language(view):
            return []

        row, col = view.rowcol(location - len(prefix))
        unsaved_buffer = None
        if view.is_dirty():
            unsaved_buffer = view.substr(sublime.Region(0, view.size()))

        completions = get_completions(filename, args, row+1, col+1, prefix, timeout, unsaved_buffer)

        return completions;
    def on_post_text_command(self, view, name, args):
        global timer

        if 'delete' in name: return
        
        pos = view.sel()[0].begin()
        if (timer is not None): timer.cancel()
        timer = Timer(0.1, lambda: self.complete_at(view, "", pos, 0))
        timer.start()
        

    def on_query_completions(self, view, prefix, locations):
        completions = self.complete_at(view, prefix, locations[0], 200)
        return ([(c, c) for c in completions], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

    def on_activated_async(self, view):
        self.complete_at(view, "", view.sel()[0].begin(), 0, get_options(view.window().folders()[0]))

    def on_close(self, view):
        if is_supported_language(view):
            free_tu(view.file_name())