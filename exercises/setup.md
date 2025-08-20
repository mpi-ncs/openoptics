# SSH to VM
Add your SSH key to the ssh-agent

```
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/your_key
```

## Enter the VM with VSCode remote
Add the config to your ssh config file (.ssh/config)
```
Host tutorial-0
    HostName sigcomm-tutorial-0.mpi-inf.mpg.de
    User root
    ProxyJump contact
    ForwardAgent yes
    LocalForward localhost:8001 localhost:8001
```

## or with bash
```
ssh -L localhost:8001:localhost:8001 -A root@sigcomm-tutorial-X
```

# Install Docker

## Add Docker's official GPG key:
```
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

## Add the repository to Apt sources:
```
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
```

## Install
```
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

# Enter OpenOptics Development Conatiner

## Clone Repo
```
git clone -b tutorial git@gitlab.mpi-klsb.mpg.de:ylei/openoptics.git
```

## Pull the Docker Image
```
docker pull ymlei/openoptics:latest
```

## Enter the Container
### With VSCode devcontainer
Open openoptics folder with VSCode remote.
With Docker and the VS Code Dev Containers extension installed, simply press Ctrl+Shift+P or Command+Shift+P (Mac) in your VS Code and run the “Dev Containers: Reopen in Container” command to open the repository inside the container. After that, Optics-Mininet is ready to go.

### Or with bash
```
cd /openoptics
docker run --privileged -dit --network host \
  --name openoptics \
  -v "$PWD:/openoptics" \
  optics-mininet /bin/bash
docker exec -dit openoptics bash
```

## Initialize the Dashboard
```
cd /openoptics/openoptics/dashboard
bash init.sh
```

# Enjoy!
Exercises for the tutorial are under /openoptics/exercises.

If you would like to explore more, you could try out more sophisticated examples under /openoptics/example,
and openoptics source code under /openoptics/openoptics