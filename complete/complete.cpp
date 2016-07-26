// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this file,
// You can obtain one at http://mozilla.org/MPL/2.0/.
// 
// Copyright (c) 2013, Paul Fultz II


#ifndef CLANG_UTILS_TRANSLATION_UNIT_H
#define CLANG_UTILS_TRANSLATION_UNIT_H

// #include <Python.h>
#include <clang-c/Index.h>
#include <iostream>
#include <fstream>
#include <sstream>
#include <set>
#include <memory>
#include <future>
#include <mutex>
#include <iterator>
#include <algorithm>
#include <unordered_map>
#include <cstring>
#include <cassert>
#include <vector>

#include "complete.h"

#ifdef CLANG_COMPLETE_LOG
std::ofstream dump_log("clang_log", std::ios_base::app);
#define DUMP(x) dump_log << std::string(__PRETTY_FUNCTION__) << ": " << #x << " = " << x << std::endl

#define TIMER() timer dump_log_timer(true);

#define DUMP_TIMER() DUMP(dump_log_timer)

#define DUMP_LOG_TIME(x) dump_log << x << ": " << dump_log_timer.reset().count() << std::endl

#else

#define DUMP(x)

#define TIMER()

#define DUMP_TIMER()

#define DUMP_LOG_TIME(x)

#endif


namespace std {

string& to_string(string& s)
{
    return s;
}

const string& to_string(const string& s)
{
    return s;
}

}

class timer 
{
    typedef typename std::conditional<std::chrono::high_resolution_clock::is_steady,
            std::chrono::high_resolution_clock,
            std::chrono::steady_clock>::type clock_type;
    typedef std::chrono::milliseconds milliseconds;
public:
    explicit timer(bool run = false)
    {
        if (run) this->reset();
    }
    milliseconds reset()
    {
        milliseconds x = this->elapsed();
        this->start = clock_type::now();
        return x;
    }
    milliseconds elapsed() const
    {
        return std::chrono::duration_cast<milliseconds>(clock_type::now() - this->start);
    }
    template <typename Stream>
    friend Stream& operator<<(Stream& out, const timer& self)
    {
        return out << self.elapsed().count();
    }
private:
    clock_type::time_point start;
};
 
// An improved async, that doesn't block
template< class Function, class... Args>
std::future<typename std::result_of<Function(Args...)>::type>
detach_async( Function&& f, Args&&... args )
{
    typedef typename std::result_of<Function(Args...)>::type result_type;
    std::packaged_task<result_type(Args...)> task(std::forward<Function>(f));
    auto fut = task.get_future(); 
    std::thread(std::move(task)).detach();
    return std::move(fut);
}

inline bool starts_with(const char *str, const char *pre)
{
    size_t lenpre = strlen(pre),
           lenstr = strlen(str);
    return lenstr < lenpre ? false : strncmp(pre, str, lenpre) == 0;
}

inline bool istarts_with(const std::string& str, const std::string& pre)
{
    return str.length() < pre.length() ? false : 
        std::equal(pre.begin(), pre.end(), str.begin(), [](char a, char b) { return std::tolower(a) == std::tolower(b); });
}

std::string get_line_at(const std::string& str, unsigned int line)
{
    int n = 1;
    std::string::size_type pos = 0;
    std::string::size_type prev = 0;
    while ((pos = str.find('\n', prev)) != std::string::npos)
    {
        if (n == line) return str.substr(prev, pos - prev);
        prev = pos + 1;
        n++;
    }

    // To get the last line
    if (n == line) return str.substr(prev);
    else return "";
}

CXIndex get_index(bool clear=false)
{
    static std::shared_ptr<void> index = std::shared_ptr<void>(clang_createIndex(1, 1), &clang_disposeIndex);
    if (clear) index = std::shared_ptr<void>(clang_createIndex(1, 1), &clang_disposeIndex);
    return index.get();
}

class translation_unit
{
    // CXIndex index;
    CXTranslationUnit tu;
    std::string filename;
    std::timed_mutex m;

    CXUnsavedFile unsaved_buffer(const char * buffer, unsigned len)
    {
        CXUnsavedFile result;
        result.Filename = this->filename.c_str();
        result.Contents = buffer;
        result.Length = len;
        return result;
    }

    static std::string to_std_string(CXString str)
    {
        std::string result;
        const char * s = clang_getCString(str);
        if (s != nullptr) result = s;
        clang_disposeString(str);
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

        std::size_t size() const
        {
            if (results == nullptr) return 0;
            else return results->NumResults;
        }

        iterator begin()
        {
            if (results == nullptr) return nullptr;
            else return results->Results;
        }

        iterator end()
        {
            if (results == nullptr) return nullptr;
            else return results->Results + results->NumResults;
        }
    };

    template<class F>
    static void for_each_completion_string(CXCompletionResult& c, F f)
    {
        if ( clang_getCompletionAvailability( c.CompletionString ) == CXAvailability_Available )
        {
            int num = clang_getNumCompletionChunks(c.CompletionString);
            for(int i=0;i<num;i++)
            {
                auto str = clang_getCompletionChunkText(c.CompletionString, i);
                auto kind = clang_getCompletionChunkKind(c.CompletionString, i);
                f(to_std_string(str), kind);
            }
        }
    }

    static std::string get_typed_text(CXCompletionResult& c)
    {
        if ( clang_getCompletionAvailability( c.CompletionString ) == CXAvailability_Available )
        {
            int num = clang_getNumCompletionChunks(c.CompletionString);
            for(int i=0;i<num;i++)
            {
                auto str = clang_getCompletionChunkText(c.CompletionString, i);
                auto kind = clang_getCompletionChunkKind(c.CompletionString, i);
                if (kind == CXCompletionChunk_TypedText) return to_std_string(str);
            }
        }
        return {};
    }

    static unsigned code_complete_options()
    {
        return CXCodeComplete_IncludeMacros | CXCodeComplete_IncludeCodePatterns | CXCodeComplete_IncludeBriefComments;
    }

    completion_results completions_at(unsigned line, unsigned col, const char * buffer, unsigned len)
    {
        if (buffer == nullptr) 
        {
            return clang_codeCompleteAt(this->tu, this->filename.c_str(), line, col, nullptr, 0, code_complete_options());
        }
        else
        {
            auto unsaved = this->unsaved_buffer(buffer, len);
            return clang_codeCompleteAt(this->tu, this->filename.c_str(), line, col, &unsaved, 1, code_complete_options());
        }
    }

    static unsigned parse_options()
    {
        return 
            CXTranslationUnit_DetailedPreprocessingRecord | 
            CXTranslationUnit_IncludeBriefCommentsInCodeCompletion |
            CXTranslationUnit_Incomplete | 
            CXTranslationUnit_PrecompiledPreamble | 
            CXTranslationUnit_CacheCompletionResults;
    }

    void unsafe_reparse(const char * buffer=nullptr, unsigned len=0)
    {
        if (buffer == nullptr) clang_reparseTranslationUnit(this->tu, 0, nullptr, parse_options());
        else
        {
            auto unsaved = this->unsaved_buffer(buffer, len);
            clang_reparseTranslationUnit(this->tu, 1, &unsaved, parse_options());
        }
    }
public:
    struct cursor
    {
        CXCursor c;
        CXTranslationUnit tu;

        cursor(CXCursor c, CXTranslationUnit tu) : c(c), tu(tu)
        {}

        CXCursorKind get_kind()
        {
            return clang_getCursorKind(this->c);
        }

        cursor get_reference()
        {
            return cursor(clang_getCursorReferenced(this->c), this->tu);
        }

        cursor get_definition()
        {
            return cursor(clang_getCursorDefinition(this->c), this->tu);
        }

        cursor get_type()
        {
            return cursor(clang_getTypeDeclaration(clang_getCanonicalType(clang_getCursorType(this->c))), this->tu);
        }

        std::string get_display_name()
        {
            return to_std_string(clang_getCursorDisplayName(this->c));
        }

        std::string get_spelling()
        {
            return to_std_string(clang_getCursorSpelling(this->c));
        }

        std::string get_type_name()
        {
            return to_std_string(clang_getTypeSpelling(clang_getCanonicalType(clang_getCursorType(this->c))));
        }

        CXSourceLocation get_location()
        {
            return clang_getCursorLocation(this->c);
        }

        std::string get_location_path()
        {
            CXFile f;
            unsigned line, col, offset;
            clang_getSpellingLocation(this->get_location(), &f, &line, &col, &offset);
            return to_std_string(clang_getFileName(f)) + ":" + std::to_string(line) + ":" + std::to_string(col);
        }

        std::string get_include_file()
        {
            CXFile f = clang_getIncludedFile(this->c);
            return to_std_string(clang_getFileName(f));
        }

        std::vector<cursor> get_overloaded_cursors()
        {
            std::vector<cursor> result = {*this};
            if (clang_getCursorKind(this->c) == CXCursor_OverloadedDeclRef)
            {
                for(int i=0;i<clang_getNumOverloadedDecls(this->c);i++)
                {
                    result.emplace_back(clang_getOverloadedDecl(this->c, i), this->tu);
                }
            }
            return result;
        }

        template<class F>
        struct find_references_trampoline
        {
            F f;
            cursor * self;

            find_references_trampoline(F f, cursor * self) : f(f), self(self)
            {}
            CXVisitorResult operator()(CXCursor c, CXSourceRange r) const
            {
                f(cursor(c, self->tu), r);
                return CXVisit_Continue;
            }
        };

        template<class F>
        void find_references(const char* name, F f)
        {
            CXFile file = clang_getFile(this->tu, name);
            find_references_trampoline<F> trampoline(f, this);
            CXCursorAndRangeVisitor visitor = {};
            visitor.context = &trampoline;
            visitor.visit = [](void *context, CXCursor c, CXSourceRange r) -> CXVisitorResult
            {
                return (*(reinterpret_cast<find_references_trampoline<F>*>(context)))(c, r);
            };
            clang_findReferencesInFile(this->c, file, visitor);
        }

        bool is_null()
        {
            return clang_Cursor_isNull(this->c);
        }
    };
    translation_unit(const char * filename, const char ** args, int argv) : filename(filename)
    {
        // this->index = clang_createIndex(1, 1);
        this->tu = clang_parseTranslationUnit(get_index(), filename, args, argv, NULL, 0, parse_options());
        detach_async([=]() { this->reparse(); });
    }

    translation_unit(const translation_unit&) = delete;

    cursor get_cursor_at(unsigned long line, unsigned long col, const char * name=nullptr)
    {
        if (name == nullptr) name = this->filename.c_str();
        CXFile f = clang_getFile(this->tu, name);
        CXSourceLocation loc = clang_getLocation(this->tu, f, line, col);
        return cursor(clang_getCursor(this->tu, loc), this->tu);
    }

    void reparse(const char * buffer=nullptr, unsigned len=0)
    {
        std::lock_guard<std::timed_mutex> lock(this->m);
        this->unsafe_reparse(buffer, len);
    }

    struct usage
    {
        CXTUResourceUsage u;

        typedef CXTUResourceUsageEntry* iterator;

        usage(CXTUResourceUsage u) : u(u)
        {}

        usage(const usage&) = delete;


        iterator begin()
        {
            return u.entries;
        }

        iterator end()
        {
            return u.entries + u.numEntries;
        }

        ~usage()
        {
            clang_disposeCXTUResourceUsage(u);
        }
    };

    std::unordered_map<std::string, unsigned long> get_usage()
    {
        std::lock_guard<std::timed_mutex> lock(this->m);
        std::unordered_map<std::string, unsigned long> result;
        auto u = std::make_shared<usage>(clang_getCXTUResourceUsage(this->tu));
        for(CXTUResourceUsageEntry e:*u)
        {
            result.insert(std::make_pair(clang_getTUResourceUsageName(e.kind), e.amount));
        }
        return result;

    }


    typedef std::tuple<std::size_t, std::string, std::string> completion;

    std::vector<completion> complete_at(unsigned line, unsigned col, const char * prefix, const char * buffer=nullptr, unsigned len=0)
    {
        std::lock_guard<std::timed_mutex> lock(this->m);
        TIMER();
        std::vector<completion> results;

        std::string display;
        std::string replacement;
        std::string description;
        char buf[1024];
        auto completions = this->completions_at(line, col, buffer, len);
        DUMP_LOG_TIME("Clang to complete");
        results.reserve(completions.size());
        for(auto& c:completions)
        {
            auto priority = clang_getCompletionPriority(c.CompletionString);
            auto ck = c.CursorKind;
            auto num = clang_getNumCompletionChunks(c.CompletionString);

            display.reserve(num*8);
            replacement.reserve(num*8);
            description.clear();

            std::size_t idx = 1;
            for_each_completion_string(c, [&](const std::string& text, CXCompletionChunkKind kind)
            {
                switch (kind) 
                {
                case CXCompletionChunk_LeftParen:
                case CXCompletionChunk_RightParen:
                case CXCompletionChunk_LeftBracket:
                case CXCompletionChunk_RightBracket:
                case CXCompletionChunk_LeftBrace:
                case CXCompletionChunk_RightBrace:
                case CXCompletionChunk_LeftAngle:
                case CXCompletionChunk_RightAngle:
                case CXCompletionChunk_CurrentParameter:
                case CXCompletionChunk_Colon:
                case CXCompletionChunk_Comma:
                case CXCompletionChunk_HorizontalSpace:
                case CXCompletionChunk_VerticalSpace:
                    display += text;
                    replacement += text;
                    break;
                case CXCompletionChunk_TypedText:
                    display += text;
                    replacement += text;
                    if (ck == CXCursor_Constructor)
                    {
                        std::snprintf(buf, 1024, "%lu", idx++);
                        replacement.append(" ${").append(buf).append(":v}");
                    }
                    break;
                case CXCompletionChunk_Placeholder:
                    display += text;
                    std::snprintf(buf, 1024, "%lu", idx++);
                    replacement.append("${").append(buf).append(":").append(text).append("}");
                    break;
                case CXCompletionChunk_ResultType:
                case CXCompletionChunk_Text:
                case CXCompletionChunk_Informative:
                case CXCompletionChunk_Equal:
                    description.append(text).append(" ");
                    break;
                case CXCompletionChunk_Optional:
                case CXCompletionChunk_SemiColon:
                    break;
                }
            });
            display.append("\t").append(description);
            // Lower priority for completions that start with `operator` and `~`
            if (starts_with(display.c_str(), "operator") or starts_with(display.c_str(), "~")) priority = std::numeric_limits<decltype(priority)>::max();
            if (not display.empty() and not replacement.empty() and starts_with(display.c_str(), prefix)) 
                results.emplace_back(priority, std::move(display), std::move(replacement));
        }
        std::sort(results.begin(), results.end());
        // Perhaps a reparse can help rejuvenate clang?
        // if (results.size() == 0) this->unsafe_reparse(buffer, len);
        DUMP_LOG_TIME("Process completions");
        DUMP(results.size());
        return results;
    }

    std::vector<std::string> get_diagnostics(int timeout=-1)
    {
        std::unique_lock<std::timed_mutex> lock(this->m, std::defer_lock);
        if (timeout < 0)
        {
            lock.lock();
        }
        else
        {
            if (!lock.try_lock_for(std::chrono::milliseconds(timeout))) return {};
        }
        std::vector<std::string> result;
        auto n = clang_getNumDiagnostics(this->tu);
        for(int i=0;i<n;i++)
        {
            auto diag = std::shared_ptr<void>(clang_getDiagnostic(this->tu, i), &clang_disposeDiagnostic);
            if (diag != nullptr and clang_getDiagnosticSeverity(diag.get()) != CXDiagnostic_Ignored)
            {
                auto str = clang_formatDiagnostic(diag.get(), clang_defaultDiagnosticDisplayOptions());
                result.push_back(to_std_string(str));
            }
        }
        return result;
    }

    std::string get_definition(unsigned line, unsigned col)
    {
        std::lock_guard<std::timed_mutex> lock(this->m);
        std::string result;
        cursor c = this->get_cursor_at(line, col);
        DUMP(c.get_display_name());
        cursor ref = c.get_reference();
        DUMP(ref.is_null());
        if (!ref.is_null())
        {
            DUMP(ref.get_display_name());
            result = ref.get_location_path();
        }
        else if (c.get_kind() == CXCursor_InclusionDirective)
        {
            result = c.get_include_file();
        }
        return result;
    }

    std::string get_type(unsigned line, unsigned col)
    {
        std::lock_guard<std::timed_mutex> lock(this->m);

        return this->get_cursor_at(line, col).get_type_name();

    }

    std::set<std::string> find_uses_in(unsigned line, unsigned col, const char * name=nullptr)
    {
        std::lock_guard<std::timed_mutex> lock(this->m);
        std::set<std::string> result;
        if (name == nullptr) name = this->filename.c_str();
        auto c = this->get_cursor_at(line, col);
        for(auto oc:c.get_overloaded_cursors())
        {
            oc.find_references(name, [&](cursor ref, CXSourceRange r)
            {
                result.insert(ref.get_location_path());
            });
        }
        return result;
    }
    
    ~translation_unit()
    {
        std::lock_guard<std::timed_mutex> lock(this->m);
        clang_disposeTranslationUnit(this->tu);
    }
};

class async_translation_unit : public translation_unit, public std::enable_shared_from_this<async_translation_unit>
{

    struct query
    {
        std::future<std::vector<completion>> results_future;
        std::vector<completion> results;
        unsigned line;
        unsigned col;

        query() : line(0), col(0)
        {}

        std::pair<unsigned, unsigned> get_loc()
        {
            return std::make_pair(this->line, this->col);
        }

        void set(std::future<std::vector<completion>> && results_future, unsigned line, unsigned col)
        {
            this->results = {};
            this->results_future = std::move(results_future);
            this->line = line;
            this->col = col;
        }

        std::vector<completion> get(int timeout)
        {
            if (results_future.valid() and this->ready(timeout))
            {
                this->results = this->results_future.get();
                // Force another query if completion results are empty
                if (this->results.size() == 0) std::tie(line, col) = std::make_pair(0, 0);
            }
            return this->results;
        }

        bool ready(int timeout = 10)
        {
            if (results_future.valid()) return (timeout > 0 and results_future.wait_for(std::chrono::milliseconds(timeout)) == std::future_status::ready);
            else return true;
        }

    };
    std::timed_mutex async_mutex;
    query q;

public:
    async_translation_unit(const char * filename, const char ** args, int argv) : translation_unit(filename, args, argv)
    {}


    std::vector<completion> async_complete_at(unsigned line, unsigned col, const char * prefix, int timeout, const char * buffer=nullptr, unsigned len=0)
    {
        
        std::unique_lock<std::timed_mutex> lock(this->async_mutex, std::defer_lock);
        if (!lock.try_lock_for(std::chrono::milliseconds(20))) return {};
        
        if (std::make_pair(line, col) != q.get_loc())
        {
            // If we are busy with a query, lets avoid making lots of new queries
            if (not this->q.ready()) return {};
            
            std::weak_ptr<async_translation_unit> self = this->shared_from_this();
            std::string buffer_as_string(buffer, buffer+len);
            this->q.set(detach_async([=]
            {
                auto b = buffer_as_string.c_str();
                if (buffer == nullptr) b = nullptr;
                // TODO: Should we always reparse?
                // else this->reparse(b, len);
                if (auto s = self.lock())
                {
                    return s->complete_at(line, col, "", b, buffer_as_string.length());
                }
                else
                {
                    return std::vector<completion>();
                }
            }), line, col);
        }
        auto completions = q.get(timeout);
        if (prefix != nullptr and *prefix != 0)
        {
            std::string pre = prefix;
            std::vector<completion> results;
            std::copy_if(completions.begin(), completions.end(), inserter(results, results.begin()), [&](const completion& x)
            { 
                return istarts_with(std::get<2>(x), pre); 
            });
            return std::move(results);
        }
        else
        {
            return std::move(completions);
        }
    }
};

std::timed_mutex tus_mutex;
std::unordered_map<std::string, std::shared_ptr<async_translation_unit>> tus;

std::shared_ptr<async_translation_unit> get_tu(const char * filename, const char ** args, int argv, int timeout=-1)
{
    std::unique_lock<std::timed_mutex> lock(tus_mutex, std::defer_lock);
    if (timeout < 0) lock.lock();
    else if (!lock.try_lock_for(std::chrono::milliseconds(timeout))) return {};

    if (tus.find(filename) == tus.end())
    {
        tus[filename] = std::make_shared<async_translation_unit>(filename, args, argv);
    }
    return tus[filename];
}

template<class T>
std::mutex& get_allocations_mutex()
{
    static std::mutex m;
    return m;
}

template<class T>
std::unordered_map<unsigned int, T>& get_allocations()
{
    static std::mutex m;
    static std::unordered_map<unsigned int, T> allocations;
    return allocations;
};

template<class T>
unsigned int new_wrapper()
{
    std::unique_lock<std::mutex> lock(get_allocations_mutex<T>());
    unsigned int id = (get_allocations<T>().size() * 8 + sizeof(T)) % std::numeric_limits<unsigned int>::max();
    while (get_allocations<T>().count(id) > 0 and id < (std::numeric_limits<unsigned int>::max() - 1)) id++;
    assert(get_allocations<T>().count(id) == 0);
    get_allocations<T>().emplace(id, T());
    return id;
} 

template<class T>
T& unwrap(unsigned int i)
{
    assert(i > 0);
    std::unique_lock<std::mutex> lock(get_allocations_mutex<T>());
    return get_allocations<T>().at(i);
}

template<class T>
void free_wrapper(unsigned int i)
{
    std::unique_lock<std::mutex> lock(get_allocations_mutex<T>());
    get_allocations<T>().erase(i);
} 

std::string& get_string(clang_complete_string s)
{
    return unwrap<std::string>(s);
}

unsigned int new_string(const std::string& s)
{
    auto i = new_wrapper<std::string>();
    unwrap<std::string>(i) = std::string(s);
    return i;
}

typedef std::vector<std::string> slist;

slist& get_slist(clang_complete_string_list list)
{
    static slist empty_vec;
    assert(empty_vec.empty());
    if (list == 0) return empty_vec;
    else return unwrap<slist>(list);
}

unsigned int new_slist()
{
    return new_wrapper<slist>();
}

unsigned int empty_slist()
{
    return 0;
}

template<class Range>
clang_complete_string_list export_slist(const Range& r)
{
    auto id = new_slist();
    auto& list = get_slist(id);

    for (const auto& s:r)
    {
        list.push_back(s);
    }

    return id;
}

template<class Range>
clang_complete_string_list export_slist_completion(const Range& r)
{
    auto id = new_slist();
    auto& list = get_slist(id);

    for (const auto& s:r)
    {
        list.push_back(std::get<1>(s) + "\n" + std::get<2>(s));
    }

    return id;
}

extern "C" {

const char * clang_complete_string_value(clang_complete_string s)
{
    return get_string(s).c_str();
}
void clang_complete_string_free(clang_complete_string s)
{
    free_wrapper<std::string>(s);
}
void clang_complete_string_list_free(clang_complete_string_list list)
{
    free_wrapper<slist>(list);
}
int clang_complete_string_list_len(clang_complete_string_list list)
{
    if (list == 0) return 0;
    else return get_slist(list).size();
}
const char * clang_complete_string_list_at(clang_complete_string_list list, int index)
{
    if (list == 0) return nullptr;
    else return get_slist(list).at(index).c_str();
}

clang_complete_string_list clang_complete_get_completions(
        const char * filename, 
        const char ** args, 
        int argv, 
        unsigned line, 
        unsigned col, 
        const char * prefix, 
        int timeout,
        const char * buffer, 
        unsigned len)
{
    auto tu = get_tu(filename, args, argv, 200);
    if (tu == nullptr) return empty_slist();
    else return export_slist_completion(tu->async_complete_at(line, col, prefix, timeout, buffer, len));
}

clang_complete_string_list clang_complete_find_uses(const char * filename, const char ** args, int argv, unsigned line, unsigned col, const char * search)
{
    auto tu = get_tu(filename, args, argv);

    return export_slist(tu->find_uses_in(line, col, search));
}

clang_complete_string_list clang_complete_get_diagnostics(const char * filename, const char ** args, int argv)
{
    auto tu = get_tu(filename, args, argv, 200);
    if (tu == nullptr) return empty_slist();
    else
    {
        tu->reparse(nullptr, 0);
        return export_slist(tu->get_diagnostics(250));
    }
}

clang_complete_string clang_complete_get_definition(const char * filename, const char ** args, int argv, unsigned line, unsigned col)
{
    auto tu = get_tu(filename, args, argv);

    return new_string(tu->get_definition(line, col));
}

clang_complete_string clang_complete_get_type(const char * filename, const char ** args, int argv, unsigned line, unsigned col)
{
    auto tu = get_tu(filename, args, argv);

    return new_string(tu->get_type(line, col));
}

void clang_complete_reparse(const char * filename, const char ** args, int argv, const char * buffer, unsigned len)
{
    auto tu = get_tu(filename, args, argv);
    tu->reparse();
}

void clang_complete_free_tu(const char * filename)
{
    std::string name = filename;
    detach_async([=]
    {
        std::lock_guard<std::timed_mutex> lock(tus_mutex);
        if (tus.find(name) != tus.end())
        {
            tus.erase(name);
        }
    });
}

void clang_complete_free_all()
{
    std::lock_guard<std::timed_mutex> lock(tus_mutex);
    tus.clear();
    get_index(true);
}
}


#endif
