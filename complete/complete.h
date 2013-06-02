#ifndef CLANGCOMPLETE_COMPLETE_H
#define CLANGCOMPLETE_COMPLETE_H


extern "C"
{
    const char ** clang_complete_get_completions(
        const char * filename, 
        const char ** args, 
        int argv, 
        unsigned line, 
        unsigned col, 
        const char * prefix, 
        int timeout,
        const char * buffer, 
        unsigned len);
}

#endif