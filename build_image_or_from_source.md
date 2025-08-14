
# Building Docker Images

We also provide a Dockerfile if you prefer to build the image yourself. Simply run the following in the project folder:
```
docker build -t openoptics .
```
And enter the container as in QuickStart.

# Build OpenOptics from Source

[BMv2](https://github.com/p4lang/behavioral-model) is the P4-programmable reference software switch. Optics-Mininet contains two custom BMv2 targets in the `targets/` directory, and their accompanying compiled p4 files in the `p4/` directory. To build BMv2 for Optics-Mininet: 
1. Clone the BMv2 repo and move it into the Optics-Mininet directory
2. Checkout commit 8e183a39b372cb9dc563e9d0cf593323249cd88b of BMv2
3. Copy the `optical_switch` and `tor_switch` target directories into the `behavioral-model/targets/` directory
4. Install BMv2's dependencies, either by manually following the instructions in BMv2's README, or by running the script `behavioral-model/install_deps.sh`
5. Replace `behavioral-model/configure.ac` with `targets/configure.ac`
6. Replace `behavioral-model/targets/Makefile.am` with `targets/Makefile.am`
7. `cd` into `behavioral-model/` and compile BMv2 by running:
```
./autogen.sh && ./configure && make -j8
```
8. Install Optics-Mininet' Python dependencies by navigating to `src/` and running:
```
pip3 install -r requirements.txt
```