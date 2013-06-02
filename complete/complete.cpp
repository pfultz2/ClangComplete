#ifndef CLANG_UTILS_TRANSLATION_UNIT_H
#define CLANG_UTILS_TRANSLATION_UNIT_H


#include <clang-c/Index.h>
#include <iostream>
#include <fstream>
#include <set>
#include <memory>
#include <future>
#include <mutex>
#include <iterator>
#include <algorithm>
#include <unordered_map>
#include <cstring>

#include "complete.h"

inline bool starts_with(const char *str, const char *pre)
{
    size_t lenpre = strlen(pre),
           lenstr = strlen(str);
    return lenstr < lenpre ? false : strncmp(pre, str, lenpre) == 0;
}

class translation_unit
{
    CXTranslationUnit tu;
    const char * filename;

    CXUnsavedFile unsaved_buffer(const char * buffer, unsigned len)
    {
        CXUnsavedFile result;
        result.Filename = this->filename;
        result.Contents = buffer;
        result.Length = len;
        return result;
    }

    struct completion_results
    {
        std::shared_ptr<CXCodeCompleteResults> results;
        typedef CXCompletionResult* iterator;

        completion_results(CXCodeCompleteResults* r)
        {
            this->results = std::shared_ptr<CXCodeCompleteResults>(r, &clang_disposeCodeCompleteResults);
        }

        iterator begin()
        {
            return results->Results;
        }

        iterator end()
        {
            return results->Results + results->NumResults;
        }
    };

    template<class F>
    static void for_each_completion_string(CXCompletionResult& c, F f)
    {
        if ( clang_getCompletionAvailability( c.CompletionString ) != CXAvailability_NotAccessible )
        {
            int num = clang_getNumCompletionChunks(c.CompletionString);
            for(int i=0;i<num;i++)
            {
                auto str = clang_getCompletionChunkText(c.CompletionString, i);
                auto kind = clang_getCompletionChunkKind(c.CompletionString, i);
                const char * s = clang_getCString(str);
                if (s != nullptr) f(s, kind);
                clang_disposeString(str);
            }
        }
    }

    completion_results completions_at(unsigned line, unsigned col, const char * buffer, unsigned len)
    {
        if (buffer == nullptr) 
        {
            return clang_codeCompleteAt(this->tu, this->filename, line, col, nullptr, 0, CXCodeComplete_IncludeMacros);
        }
        else
        {
            auto unsaved = this->unsaved_buffer(buffer, len);
            return clang_codeCompleteAt(this->tu, this->filename, line, col, &unsaved, 1, CXCodeComplete_IncludeMacros);
        }
    }
public:
    translation_unit(const char * filename, const char ** args, int argv) : filename(filename)
    {
        CXIndex index = clang_createIndex(1, 1);
        this->tu = clang_parseTranslationUnit(index, filename, args, argv, NULL, 0, clang_defaultEditingTranslationUnitOptions());
    }

    translation_unit(const translation_unit&) = delete;


    // void reparse(const char * buffer, unsigned len)
    // {
    //     CXUnsavedFile unsaved_file;
    //     unsaved_file.Filename = this->filename;
    //     unsaved_file.Contents = buffer;
    //     unsaved_file.Length = len;
    //     clang_reparseTranslationUnit(this->tu, 1, clang_defaultReparseOptions(this->tu));
    // }

    std::set<std::string> complete_at(unsigned line, unsigned col, const char * prefix, const char * buffer=nullptr, unsigned len=0)
    {
        std::set<std::string> results;
        for(auto& c:this->completions_at(line, col, buffer, len))
        {
            std::string r;
            for_each_completion_string(c, [&](const char * s, CXCompletionChunkKind kind)
            {
                if (kind == CXCompletionChunk_TypedText)
                {
                    r += s;
                    r += ' ';
                }
            });
            if (!r.empty() and starts_with(r.c_str(), prefix)) results.insert(r);
        }
        return results;
    }

    ~translation_unit()
    {
        clang_disposeTranslationUnit(tu);
    }
};

#ifndef CLANG_COMPLETE_ASYNC_WAIT_MS
#define CLANG_COMPLETE_ASYNC_WAIT_MS 200
#endif

class async_translation_unit : public translation_unit
{

    struct query
    {
        std::mutex m;
        std::future<std::set<std::string>> results;
        unsigned line;
        unsigned col;

        query() : line(0), col(0)
        {}

        std::pair<unsigned, unsigned> get_loc()
        {
            // std::lock_guard<std::mutex> lock(this->m);
            return std::make_pair(this->line, this->col);
        }

        void set(std::future<std::set<std::string>> && results, unsigned line, unsigned col)
        {
            // std::lock_guard<std::mutex> lock(this->m);
            this->results = std::move(results);
            this->line = line;
            this->col = col;
        }

        std::set<std::string> get()
        {
            // std::lock_guard<std::mutex> lock(this->m);
            if (results.valid() and results.wait_for(std::chrono::milliseconds(CLANG_COMPLETE_ASYNC_WAIT_MS)) == std::future_status::ready)
            {
                return results.get();
            }
            else
            {
                return {};
            }
        }

    };

    query q;

public:
    async_translation_unit(const char * filename, const char ** args, int argv) : translation_unit(filename, args, argv)
    {}


    std::set<std::string> async_complete_at(unsigned line, unsigned col, const char * prefix, const char * buffer=nullptr, unsigned len=0)
    {
        if (std::make_pair(line, col) != q.get_loc())
        {
            q.set(std::async(std::launch::async, [=]{ return this->complete_at(line, col, "", buffer, len); }), line, col);
        }
        auto completions = q.get();
        std::set<std::string> results;
        std::copy_if(completions.begin(), completions.end(), inserter(results, results.begin()), [&](const std::string& x)
        { 
            return starts_with(x.c_str(), prefix); 
        });
        return results;
    }
};


#ifndef CLANG_COMPLETE_MAX_RESULTS
#define CLANG_COMPLETE_MAX_RESULTS 4096
#endif

struct translation_unit_data
{
    translation_unit_data(const char * filename, const char ** args, int argv) : tu(filename, args, argv)
    {}

    async_translation_unit tu;
    std::set<std::string> last_results;
    const char * results[CLANG_COMPLETE_MAX_RESULTS+1];
};

std::unordered_map<std::string, std::shared_ptr<translation_unit_data>> tus;
// std::set<std::string> last_results;

// std::set<std::string> get_completions(const char * filename, const char ** args, int argv, unsigned line, unsigned col, const char * prefix, const char * buffer=nullptr, unsigned len = 0)
// {
//     if (tus.find(filename) == tus.end())
//     {
//         tus[filename] = std::make_shared<async_translation_unit>(filename, args, argv);
//     }
//     return tus[filename]->async_complete_at(line, col, prefix, buffer, len);
// }

#define DUMP(x) log << #x << ": " << x << std::endl;

extern "C" {
const char ** clang_complete_get_completions(
        const char * filename, 
        const char ** args, 
        int argv, 
        unsigned line, 
        unsigned col, 
        const char * prefix, 
        const char * buffer, 
        unsigned len)
{
    // std::ofstream log("/home/paul/clang_log");
    // if (buffer != nullptr) DUMP(buffer);
    if (tus.find(filename) == tus.end())
    {
        // log << "Create a new translation unit" << std::endl;
        tus[filename] = std::make_shared<translation_unit_data>(filename, args, argv);
    }
    auto tud = tus[filename];
    tud->last_results = tud->tu.async_complete_at(line, col, prefix, buffer, len);

    auto overflow = tud->last_results.size() > CLANG_COMPLETE_MAX_RESULTS;
    if (overflow) printf("Overflow: %lu\n", tud->last_results.size());

    auto first = tud->last_results.begin();
    auto last = overflow ? std::next(first, CLANG_COMPLETE_MAX_RESULTS) : tud->last_results.end();
    std::transform(first, last, tud->results, [](const std::string& x) { return x.c_str(); });

    tud->results[std::distance(first, last)] = ""; 

    return tud->results;
}
}


#endif