from ctypes import cdll
from ctypes import c_char_p
from ctypes import py_object
import os
current_path = os.path.dirname(os.path.abspath(__file__))
complete = cdll.LoadLibrary('%s/libcomplete.so' % current_path)

#
#
# Clang c api wrapper
#
#

complete.clang_complete_get_completions.restype = py_object
complete.clang_complete_get_diagnostics.restype = py_object
complete.clang_complete_get_usage.restype = py_object
complete.clang_complete_get_definition.restype = py_object
complete.clang_complete_get_type.restype = py_object

def convert_to_c_string_array(a):
    result = (c_char_p * len(a))()
    result[:] = [x.encode('utf-8') for x in a]
    return result

def get_completions(filename, args, line, col, prefix, timeout, unsaved_buffer):
    buffer = None
    if (unsaved_buffer is not None): buffer = unsaved_buffer.encode("utf-8")
    buffer_len = 0
    if (buffer is not None): buffer_len = len(buffer)

    return complete.clang_complete_get_completions(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col, prefix.encode('utf-8'), timeout, buffer, buffer_len)

def get_diagnostics(filename, args):
    return complete.clang_complete_get_diagnostics(filename.encode('utf-8'), convert_to_c_string_array(args), len(args))

def get_usage(filename, args):
    return complete.clang_complete_get_usage(filename.encode('utf-8'), convert_to_c_string_array(args), len(args))

def get_definition(filename, args, line, col):
    return complete.clang_complete_get_definition(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col)

def get_type(filename, args, line, col):
    return complete.clang_complete_get_type(filename.encode('utf-8'), convert_to_c_string_array(args), len(args), line, col)

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