all:
	g++ -std=c++11 -g -c -fPIC complete.cpp -o complete.o
	g++ -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o -lclang