// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this file,
// You can obtain one at http://mozilla.org/MPL/2.0/.
// 
// Copyright (c) 2013, Paul Fultz II

#ifndef CLANGCOMPLETE_COMPLETE_H
#define CLANGCOMPLETE_COMPLETE_H

extern "C"
{
    typedef unsigned int clang_complete_string;
    const char * clang_complete_string_value(clang_complete_string s);
    void clang_complete_string_free(clang_complete_string s);

    typedef unsigned int clang_complete_string_list;
    void clang_complete_string_list_free(clang_complete_string_list list);
    int clang_complete_string_list_len(clang_complete_string_list list);
    const char * clang_complete_string_list_at(clang_complete_string_list list, int index);

    clang_complete_string_list clang_complete_get_completions(
        const char * filename, 
        const char ** args, 
        int argv, 
        unsigned line, 
        unsigned col, 
        const char * prefix, 
        int timeout,
        const char * buffer, 
        unsigned len);

    clang_complete_string_list clang_complete_find_uses(const char * filename, const char ** args, int argv, unsigned line, unsigned col, const char * search);

    clang_complete_string_list clang_complete_get_diagnostics(const char * filename, const char ** args, int argv);

    // clang_complete_string_list clang_complete_get_usage(const char * filename, const char ** args, int argv);

    clang_complete_string clang_complete_get_definition(const char * filename, const char ** args, int argv, unsigned line, unsigned col);

    clang_complete_string clang_complete_get_type(const char * filename, const char ** args, int argv, unsigned line, unsigned col);

    void clang_complete_reparse(const char * filename, const char ** args, int argv, const char * buffer, unsigned len);

    void clang_complete_free_tu(const char * filename);

    void clang_complete_free_all();
}

#endif