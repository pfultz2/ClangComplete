CXX=g++

CLANG_INC_DIR := $(shell llvm-config --includedir)
CLANG_LIB_DIR := $(shell llvm-config --libdir)
CLANG_FLAGS=-I$(CLANG_INC_DIR)
CLANG_LIBS=-L$(CLANG_LIB_DIR) -Wl,-rpath=$(CLANG_LIB_DIR) -lclang


FLAGS=$(CLANG_FLAGS)
LIBS=$(CLANG_LIBS)

LIB_NAME=libcomplete
SRC=complete

all:
	$(CXX) -std=gnu++0x $(FLAGS) -DNDEBUG -Os -c -fPIC complete.cpp -o $(SRC).o
	$(CXX) -shared -Wl,-soname,$(LIB_NAME).so -o $(LIB_NAME).so $(SRC).o $(LIBS)
debug:
	$(CXX) -std=gnu++0x $(FLAGS) -g -c -fPIC -DCLANG_COMPLETE_LOG $(SRC).cpp -o $(SRC).o
	$(CXX) -shared -Wl,-soname,$(LIB_NAME).so -o $(LIB_NAME).so $(SRC).o $(LIBS)
log:
	$(CXX) -std=gnu++0x $(FLAGS) -Os -c -fPIC -DCLANG_COMPLETE_LOG $(SRC).cpp -o $(SRC).o
	$(CXX) -shared -Wl,-soname,$(LIB_NAME).so -o $(LIB_NAME).so $(SRC).o $(LIBS)
