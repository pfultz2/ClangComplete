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

// #define CLANG_COMPLETE_LOG

#ifdef CLANG_COMPLETE_LOG
std::ofstream dump_log("/home/paul/clang_log", std::ios_base::app);
#define DUMP(x) dump_log << std::string(__PRETTY_FUNCTION__) << ": " << #x << " = " << x << std::endl

#define TIMER() timer dump_log_timer(true);

#define DUMP_TIMER() DUMP(dump_log_timer)

#else

#define DUMP(x)

#define TIMER()

#define DUMP_TIMER()

#endif

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
    void reset()
    {
        this->start = clock_type::now();
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

class translation_unit
{
    CXIndex index;
    CXTranslationUnit tu;
    const char * filename;
    std::mutex m;

    CXUnsavedFile unsaved_buffer(const char * buffer, unsigned len)
    {
        CXUnsavedFile result;
        result.Filename = this->filename;
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

    void unsafe_reparse(const char * buffer=nullptr, unsigned len=0)
    {
        if (buffer == nullptr) clang_reparseTranslationUnit(this->tu, 0, nullptr, clang_defaultReparseOptions(this->tu));
        else
        {
            auto unsaved = this->unsaved_buffer(buffer, len);
            clang_reparseTranslationUnit(this->tu, 1, &unsaved, clang_defaultReparseOptions(this->tu));
        }
    }
public:
    struct cursor
    {
        CXCursor c;

        cursor(CXCursor c) : c(c)
        {}

        CXCursorKind get_kind()
        {
            return clang_getCursorKind(this->c);
        }

        cursor get_reference()
        {
            return cursor(clang_getCursorReferenced(this->c));
        }

        cursor get_definition()
        {
            return cursor(clang_getCursorDefinition(this->c));
        }

        std::string get_display_name()
        {
            return to_std_string(clang_getCursorDisplayName(this->c));
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

        bool is_null()
        {
            return clang_Cursor_isNull(this->c);
        }
    };
    translation_unit(const char * filename, const char ** args, int argv) : filename(filename)
    {
        this->index = clang_createIndex(1, 1);
        this->tu = clang_parseTranslationUnit(index, filename, args, argv, NULL, 0, clang_defaultEditingTranslationUnitOptions());
        detach_async([=]() { this->reparse(); });
    }

    translation_unit(const translation_unit&) = delete;

    cursor get_cursor_at(unsigned long line, unsigned long col, const char * name=nullptr)
    {
        if (name == nullptr) name = this->filename;
        CXFile f = clang_getFile(this->tu, name);
        CXSourceLocation loc = clang_getLocation(this->tu, f, line, col);
        return cursor(clang_getCursor(this->tu, loc));
    }

    void reparse(const char * buffer=nullptr, unsigned len=0)
    {
        std::lock_guard<std::mutex> lock(this->m);
        this->unsafe_reparse(buffer, len);
    }

    std::set<std::string> complete_at(unsigned line, unsigned col, const char * prefix, const char * buffer=nullptr, unsigned len=0)
    {
        std::lock_guard<std::mutex> lock(this->m);
        TIMER();
        std::set<std::string> results;
        for(auto& c:this->completions_at(line, col, buffer, len))
        {
            std::string r;
            for_each_completion_string(c, [&](const std::string& s, CXCompletionChunkKind kind)
            {
                if (kind == CXCompletionChunk_TypedText)
                {
                    r = s;
                }
            });
            if (!r.empty() and starts_with(r.c_str(), prefix)) results.insert(r);
        }
        // Perhaps a reparse can help rejuvenate clang?
        if (results.size() == 0) this->unsafe_reparse(buffer, len);
        DUMP(results.size());
        DUMP_TIMER();
        // if (buffer != nullptr) dump_log << get_line_at(std::string(buffer, len), line) << std::endl;
        return results;
    }

    std::vector<std::string> get_diagnostics()
    {
        std::lock_guard<std::mutex> lock(this->m);
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
            // else if (diag != nullptr) 
            // {
            //     auto str = clang_formatDiagnostic(diag.get(), clang_defaultDiagnosticDisplayOptions());
            //     DUMP(to_std_string(str));
            // }
        }
        return result;
    }

    std::string get_definition(unsigned line, unsigned col)
    {
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
    
    ~translation_unit()
    {
        clang_disposeTranslationUnit(this->tu);
        clang_disposeIndex(this->index);
    }
};

#ifndef CLANG_COMPLETE_ASYNC_WAIT_MS
#define CLANG_COMPLETE_ASYNC_WAIT_MS 200
#endif

class async_translation_unit : public translation_unit
{

    struct query
    {
        std::future<std::set<std::string>> results_future;
        std::set<std::string> results;
        unsigned line;
        unsigned col;

        query() : line(0), col(0)
        {}

        std::pair<unsigned, unsigned> get_loc()
        {
            return std::make_pair(this->line, this->col);
        }

        void set(std::future<std::set<std::string>> && results_future, unsigned line, unsigned col)
        {
            this->results = {};
            this->results_future = std::move(results_future);
            this->line = line;
            this->col = col;
        }

        std::set<std::string> get(int timeout)
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

    query q;

public:
    async_translation_unit(const char * filename, const char ** args, int argv) : translation_unit(filename, args, argv)
    {}


    std::set<std::string> async_complete_at(unsigned line, unsigned col, const char * prefix, int timeout, const char * buffer=nullptr, unsigned len=0)
    {

        if (std::make_pair(line, col) != q.get_loc())
        {
            // If we are busy with a query, lets avoid making lots of new queries
            if (not this->q.ready()) return {};
            
            std::string buffer_as_string(buffer, buffer+len);
            this->q.set(detach_async([=]
            {
                auto b = buffer_as_string.c_str();
                if (buffer == nullptr) b = nullptr;
                // TODO: Should we always reparse?
                // else this->reparse(b, len);
                return this->complete_at(line, col, "", b, buffer_as_string.length()); 
            }), line, col);
        }
        auto completions = q.get(timeout);
        std::set<std::string> results;
        std::string pre = prefix;
        std::copy_if(completions.begin(), completions.end(), inserter(results, results.begin()), [&](const std::string& x)
        { 
            return istarts_with(x, pre); 
        });
        return results;
    }
};



#ifndef CLANG_COMPLETE_MAX_RESULTS
#define CLANG_COMPLETE_MAX_RESULTS 8192
#endif

struct translation_unit_data
{
    translation_unit_data(const char * filename, const char ** args, int argv) : tu(filename, args, argv)
    {}

    async_translation_unit tu;

    std::set<std::string> last_completions;
    const char * completions[CLANG_COMPLETE_MAX_RESULTS+2];

    std::vector<std::string> last_diagnostics;
    const char * diagnostics[CLANG_COMPLETE_MAX_RESULTS+2];

    std::string last_definition;
};

std::timed_mutex global_mutex;

std::unordered_map<std::string, std::shared_ptr<translation_unit_data>> tus;

std::shared_ptr<translation_unit_data> get_tud(const char * filename, const char ** args, int argv)
{
    if (tus.find(filename) == tus.end())
    {
        tus[filename] = std::make_shared<translation_unit_data>(filename, args, argv);
    }
    return tus[filename];
}

template<class Range, class Array>
void export_array(const Range& r, Array& out)
{
    auto overflow = r.size() > CLANG_COMPLETE_MAX_RESULTS;
    
    auto first = r.begin();
    auto last = overflow ? std::next(first, CLANG_COMPLETE_MAX_RESULTS) : r.end();
    std::transform(first, last, out, [](const std::string& x) { return x.c_str(); });

    out[std::distance(first, last)] = ""; 
}


extern "C" {
const char ** clang_complete_get_completions(
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
    static const char * empty_result[1] = { "" };
    std::unique_lock<std::timed_mutex> lock(global_mutex, std::defer_lock);
    if (!lock.try_lock_for(std::chrono::milliseconds(10))) return empty_result;

    auto tud = get_tud(filename, args, argv);
    tud->last_completions = tud->tu.async_complete_at(line, col, prefix, timeout, buffer, len);
    
    export_array(tud->last_completions, tud->completions);

    return tud->completions;
}

const char ** clang_complete_get_diagnostics(const char * filename, const char ** args, int argv)
{
    static const char * empty_result[1] = { "" };
    std::unique_lock<std::timed_mutex> lock(global_mutex, std::defer_lock);
    if (!lock.try_lock_for(std::chrono::milliseconds(250))) return empty_result;

    auto tud = get_tud(filename, args, argv);
    tud->tu.reparse(nullptr, 0);

    tud->last_diagnostics = tud->tu.get_diagnostics();
    
    export_array(tud->last_diagnostics, tud->diagnostics);

    return tud->diagnostics;
}

const char * clang_complete_get_definition(const char * filename, const char ** args, int argv, unsigned line, unsigned col)
{
    std::lock_guard<std::timed_mutex> lock(global_mutex);
    auto tud = get_tud(filename, args, argv);

    tud->last_definition = tud->tu.get_definition(line, col);

    return tud->last_definition.c_str();
}

void clang_complete_reparse(const char * filename, const char ** args, int argv, const char * buffer, unsigned len)
{
    std::lock_guard<std::timed_mutex> lock(global_mutex);
    auto tud = get_tud(filename, args, argv);

    tud->tu.reparse(buffer, len);
}

void clang_complete_free_tu(const char * filename)
{
    std::lock_guard<std::timed_mutex> lock(global_mutex);
    if (tus.find(filename) != tus.end())
    {
        tus.erase(filename);
    }
}

void clang_complete_free_all()
{
    std::lock_guard<std::timed_mutex> lock(global_mutex);
    tus.clear();
}
}


#endif