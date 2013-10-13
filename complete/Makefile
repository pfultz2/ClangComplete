all:
	g++ -std=c++11 -Os -c -fPIC complete.cpp -o complete.o
	g++ -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o -lclang -lpython3.3m
debug:
	g++ -std=c++11 -g -c -fPIC -DCLANG_COMPLETE_LOG complete.cpp -o complete.o
	g++ -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o -lclang -lpython3.3m
log:
	g++ -std=c++11 -Os -c -fPIC -DCLANG_COMPLETE_LOG complete.cpp -o complete.o
	g++ -shared -Wl,-soname,libcomplete.so -o libcomplete.so complete.o -lclang -lpython3.3m