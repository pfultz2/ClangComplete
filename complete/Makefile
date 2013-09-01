all:
	g++ -std=c++11 -Os -c -fPIC complete.cpp -o complete.o
	g++ -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o -lclang -lpython3.3m