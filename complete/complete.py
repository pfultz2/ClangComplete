from ctypes import cdll
from ctypes import POINTER
from ctypes import c_char_p
from ctypes import create_unicode_buffer
from ctypes import create_string_buffer
import os, re, sys
current_path = os.path.dirname(os.path.abspath(__file__))
complete = cdll.LoadLibrary('%s/libcomplete.so' % current_path)

#
#
# Clang c api wrapper
#
#

complete.clang_complete_get_completions.restype = POINTER(c_char_p)
complete.clang_complete_get_diagnostics.restype = POINTER(c_char_p)
complete.clang_complete_get_definition.restype = c_char_p
complete.clang_complete_get_type.restype = c_char_p

def convert_to_c_string_array(a):
    result = (c_char_p * len(a))()
    result[:] = [x.encode('utf-8') for x in a]
    return result

def convert_from_c_string_array(a):
    results = []
    i = 0
    while(len(a[i]) is not 0):
        results.append(a[i].decode("utf-8"))
        i = i + 1
    return results

def get_completions(filename, args, line, col, prefix, timeout, unsaved_buffer):
    buffer = None
    if (unsaved_buffer is not None): buffer = unsaved_buffer.encode("utf-8")
    buffer_len = 0
    if (buffer is not None): buffer_len = len(buffer)

    results = complete.clang_complete_get_completions(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col, prefix.encode('utf-8'), timeout, buffer, buffer_len)
    return convert_from_c_string_array(results)

def get_diagnostics(filename, args):
    results = complete.clang_complete_get_diagnostics(filename.encode('utf-8'), convert_to_c_string_array(args), len(args))
    return convert_from_c_string_array(results)

def get_definition(filename, args, line, col):
    result = complete.clang_complete_get_definition(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col)
    return result.decode("utf-8")

def get_type(filename, args, line, col):
    result = complete.clang_complete_get_type(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col)
    return result.decode("utf-8")

def reparse(filename, args, unsaved_buffer):
    buffer = None
    if (unsaved_buffer is not None): buffer = unsaved_buffer.encode("utf-8")
    buffer_len = 0
    if (buffer is not None): buffer_len = len(buffer)

    complete.clang_complete_reparse(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), buffer, buffer_len)

def free_tu(filename):
    complete.clang_complete_free_tu(filename.encode('utf-8'))

def free_all():
    complete.clang_complete_free_all()