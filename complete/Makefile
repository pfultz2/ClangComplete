CXX=g++
FLAGS=`pkg-config --cflags python-3.3`
LIBS=-lclang `pkg-config --cflags python-3.3`

all:
	$(CXX) -std=gnu++0x $(FLAGS) -Os -c -fPIC complete.cpp -o complete.o
	$(CXX) -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o $(LIBS)
debug:
	$(CXX) -std=gnu++0x $(FLAGS) -g -c -fPIC -DCLANG_COMPLETE_LOG complete.cpp -o complete.o
	$(CXX) -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o $(LIBS)
log:
	$(CXX) -std=gnu++0x $(FLAGS) -Os -c -fPIC -DCLANG_COMPLETE_LOG complete.cpp -o complete.o
	$(CXX) -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o $(LIBS)