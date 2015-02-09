ClangComplete
=============

Description
-----------

Clang completion for Sublime Text 3. Additionally, it provides diagnostics and some simple navigation capabilites.

Installation
------------

First, clone this repo into your sublime packages folder(it doesn't use Package Control). Then cd into the `complete` directory and type:

    make

This will build the `complete.so` binary. It requires the development version of Clang to build(the package `libclang-dev` on debian-based distros).


Installation Mac
------------
Download [Homebrew] (http://www.brew.sh) and install llvm using brew by running 
`brew install llvm`
then cd into the `complete` directory and type:
    mv Makefile.mac Makefile
    make
Usage
-----

ClangComplete provides code completion for C, C++, and Objective-C files. To figure out the compiler flags needed to parse the file, ClangComplete looks into the `build` directory in the project folder for the cmake build settings. If the build directory is placed somewhere else the `build_dir` can be set to the actual build directory. Also if cmake is not used, options can be manually set by setting the `default_options` setting.

ClangComplete also shows diagnostics whenever a file is saved, and provides `Goto Definition` functionality. Here are the default shortcuts for ClangComplete:

|      Key     |      Action      |
|--------------|------------------|
| alt+d, alt+d | Go to definition |
| alt+d, alt+c | Clear cache      |
| alt+d, alt+t | Show type        |

Support
-------

[Donate](https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=HMB5AGA7DQ9NS&lc=US&item_name=Donation%20to%20clang%20complete&button_subtype=services&currency_code=USD&bn=PP%2dBuyNowBF%3abtn_paynow_LG%2egif%3aNonHosted)
