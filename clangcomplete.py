import sublime, sublime_plugin

from threading import Timer

from ctypes import cdll
from ctypes import POINTER
from ctypes import c_char_p
from ctypes import create_unicode_buffer
from ctypes import create_string_buffer
import os, re
current_path = os.path.dirname(os.path.abspath(__file__))
complete = cdll.LoadLibrary('%s/complete/libcomplete.so' % current_path)

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
    res = complete.clang_complete_get_completions(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col, prefix.encode('utf-8'), timeout, buffer, buffer_len)
    results = []
    i = 0
    while(len(res[i]) is not 0):
        results.append(res[i])
        i = i + 1
    return results

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

    def complete_at(self, view, prefix, location, timeout):
        filename = view.file_name()
        if not is_supported_language(view):
            return []

        row, col = view.rowcol(location - len(prefix))
        unsaved_buffer = None
        if view.is_dirty():
            unsaved_buffer = view.substr(sublime.Region(0, view.size()))

        # print(unsaved_buffer)
        print(row, col, prefix)
        completions = get_completions(filename, ["-std=c++11"], row, col, prefix, timeout, unsaved_buffer)
        print("Found ", len(completions))
        for c in completions:
            print(c)

        return completions;
    def on_post_text_command(self, view, name, args):
        global timer
        pos = view.sel()[0].begin()
        if (timer is not None): timer.cancel()
        timer = Timer(0.1, lambda: self.complete_at(view, "", pos, 0))
        timer.start()
        


    def on_query_completions(self, view, prefix, locations):
        completions = self.complete_at(view, prefix, locations[0], 200)

        return ([(c, c) for c in completions], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)