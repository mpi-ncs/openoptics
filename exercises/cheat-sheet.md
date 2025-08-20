### How do I exit OpenOptics CLI?

```
Ctrl+D
```
or in Mac
```
Command+D
```

### Where is my dashboard?

Open http://localhost:8001 on your browser

### Why doesn't it work?
Check if you enable port forwarding:  
`-L localhost:8001:localhost:8001` in ssh or  
LocalForward 8001 localhost:8001 in your host's .ssh/config  

### Exception: Error creating interface pair (ocs-eth0,tor0-eth0): RTNETLINK answers: File exists

```
mn -c
```

