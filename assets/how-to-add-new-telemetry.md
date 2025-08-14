## How to add new network telemetry to OpenOptics
python -> thrift_api -> tor_switch.cpp functions

We need to define thrift apis in tor_switch.thrift

Add function in tor_switch.cpp


Add server API at targets/tor_switch/thrift/src/TorSwitch_server.cpp

```python
void get_device_metric(std::string& _return) {
bm::Logger::get()->trace("get_device_metric");
switch_->get_device_metric(_return);
}
```


targets/tor_switch/main.cpp
Add parser


Update TorSwitch_server.cpp
Define thrift return struct.




Update dashboard

views.py