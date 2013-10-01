ClangComplete
=============

Description
-----------

Clang completion for Sublime Text 3. Additionally, it provides diagnostics and some simple navigation capabilites.

Installation
------------

First, clone this repo into your sublime packages folder(it doesn't use Package Control). Then cd into the `complete` directory and type:

    make

This will build the `complete.so` binary. It requires development versions of Clang and Python 3.3 to build(packages `python3.3-dev` and `libclang-dev` on debian-based distros).

Usage
-----

ClangComplete provides code completion for C, C++, and Objective-C files. To figure out the compiler flags needed to parse the file, ClangComplete looks into the `build` directory in the project folder for the cmake build settings. If the build directory is placed somewhere else the `build_dir` can be set to the actual build directory. Also if cmake is not used, options can be manually set by setting the `default_options` setting.

ClangComplete also shows diagnostics whenever a file is saved, and provides `Goto Definition` functionality. Here are the default shortcuts for ClangComplete:

|      Key     |      Action      |
|--------------|------------------|
| alt+d, alt+d | Go to definition |
| alt+d, alt+c | Clear cache      |
| alt+d, alt+t | Show type        |


