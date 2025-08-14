# How to debug bmv2 with gdb

gdb --args /behavioral-model/targets/tor_switch/.libs/tor_switch \
-i 0@tor1-eth0 -i 10@tor1-eth10 --thrift-port 9092 --nanolog ipc:///tmp/bm-2-log.ipc --device-id 2 /openoptics/p4/tor/tor.json --debugger --log-console -- --nb-time-slices 4 --time-slice-duration-ms 128 --calendar-queue-mode 1 --tor-id 1