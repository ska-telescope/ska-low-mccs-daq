mkdir build
cd build

nvcc -arch=sm_60 -dc -c ../DeviceCode.cu -Xcompiler '-fPIC'
nvcc -lib DeviceCode.o -o devicelib.a -lcufft_static -lculibos
nvcc -arch=sm_60 -dlink -o DeviceCode_link.o DeviceCode.o -Xcompiler '-fPIC' -lcufft_static -lculibos

g++ -shared -o libaavsdaq.so -O3 -mavx -fPIC -D WITH_CORRELATOR=ON -D WITH_CHANNELISER=ON -I/usr/local/cuda/include -L/usr/local/cuda/lib64 ../AntennaData.cpp ../BeamformedData.cpp ../BiralesData.cpp ../ChannelisedData.cpp ../Correlator.cpp ../Daq.cpp ../DoubleBuffer.cpp ../NetworkReceiver.cpp ../RingBuffer.cpp ../StationData.cpp DeviceCode_link.o DeviceCode.o -L. -lxgpu -lpthread -lcufft_static -lculibos  

g++ -o network_receiver -D WITH_CORRELATOR=ON -D WITH_CHANNELISER=ON ../main.cpp -laavsdaq -L. -lpthread

sudo cp libaavsdaq.so /opt/aavs/lib/

rm *.o
