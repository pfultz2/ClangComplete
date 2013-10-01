// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this file,
// You can obtain one at http://mozilla.org/MPL/2.0/.
// 
// Copyright (c) 2013, Paul Fultz II

#ifndef CLANGCOMPLETE_COMPLETE_H
#define CLANGCOMPLETE_COMPLETE_H

#include <python3.3/object.h>

extern "C"
{
    PyObject* clang_complete_get_completions(
        const char * filename, 
        const char ** args, 
        int argv, 
        unsigned line, 
        unsigned col, 
        const char * prefix, 
        int timeout,
        const char * buffer, 
        unsigned len);

    PyObject* clang_complete_get_diagnostics(const char * filename, const char ** args, int argv);

    PyObject* clang_complete_get_usage(const char * filename, const char ** args, int argv);

    PyObject* clang_complete_get_definition(const char * filename, const char ** args, int argv, unsigned line, unsigned col);

    PyObject* clang_complete_get_type(const char * filename, const char ** args, int argv, unsigned line, unsigned col);

    void clang_complete_reparse(const char * filename, const char ** args, int argv, const char * buffer, unsigned len);

    void clang_complete_free_tu(const char * filename);

    void clang_complete_free_all();
}

#endif