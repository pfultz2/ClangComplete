CXX=g++
PYTHON_FLAGS=`pkg-config --cflags python-3.3`
PYTHON_LIBS=`pkg-config --libs python-3.3`

CLANG_VERSION=$(shell (cd /usr/lib/llvm-3.5/ && echo 3.5) 2> /dev/null || (cd /usr/lib/llvm-3.4/ && echo 3.4) 2> /dev/null || (cd /usr/lib/llvm-3.3/ && echo 3.3) 2> /dev/null)
CLANG_PREFIX=/usr/lib/llvm-$(CLANG_VERSION)
CLANG_FLAGS=-I$(CLANG_PREFIX)/include/
CLANG_LIBS=-L$(CLANG_PREFIX)/lib/ -Wl,-rpath=$(CLANG_PREFIX)/lib -lclang

FLAGS=$(PYTHON_FLAGS) $(CLANG_FLAGS)
LIBS=$(PYTHON_LIBS) $(CLANG_LIBS)

all:
	$(CXX) -std=gnu++0x $(FLAGS) -Os -c -fPIC complete.cpp -o complete.o
	$(CXX) -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o $(LIBS)
debug:
	$(CXX) -std=gnu++0x $(FLAGS) -g -c -fPIC -DCLANG_COMPLETE_LOG complete.cpp -o complete.o
	$(CXX) -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o $(LIBS)
log:
	$(CXX) -std=gnu++0x $(FLAGS) -Os -c -fPIC -DCLANG_COMPLETE_LOG complete.cpp -o complete.o
	$(CXX) -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o $(LIBS)
