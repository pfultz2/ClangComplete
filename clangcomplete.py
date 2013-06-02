import sublime, sublime_plugin

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

def get_completions(filename, args, line, col, prefix, buffer):
    buffer_len = 0
    if (buffer is not None): buffer_len = len(buffer)
    res = complete.clang_complete_get_completions(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col, prefix.encode('utf-8'), buffer, buffer_len)
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


class ClangCompleteCompletion(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        filename = view.file_name()
        if not is_supported_language(view):
            return []

        row, col = view.rowcol(locations[0] - len(prefix))
        unsaved_buffer = None
        if view.is_dirty():
            unsaved_buffer = view.substr(sublime.Region(0, view.size()))

        # print(unsaved_buffer)
        # print(row, col, prefix)
        completions = get_completions(filename, ["-std=c++11"], row, col, prefix, unsaved_buffer)
        # print("Found ", len(completions))
        # for c in completions:
        #     print(c)

        return (completions,sublime.INHIBIT_EXPLICIT_COMPLETIONS)