CXX=g++
PYTHON_FLAGS=$(shell pkg-config --cflags python-3.3)
PYTHON_LIBS=$(shell pkg-config --libs python-3.3)

CLANG_INC_DIR := $(shell llvm-config --includedir)
CLANG_LIB_DIR := $(shell llvm-config --libdir)
CLANG_FLAGS=-I$(CLANG_INC_DIR)
CLANG_LIBS=-L$(CLANG_LIB_DIR) -Wl,-rpath=$(CLANG_LIB_DIR) -lclang


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
