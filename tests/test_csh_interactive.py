import pty
import os

# Simulate an interactive shell sourcing the script
master, slave = pty.openpty()
pid = os.fork()

if pid == 0:  # Child
    os.setsid()
    os.dup2(slave, 0)
    os.dup2(slave, 1)
    os.dup2(slave, 2)
    os.close(master)
    os.close(slave)
    os.execlp("csh", "csh", "-i")
else:  # Parent
    os.close(slave)
    # write to interactive shell
    os.write(master, b"source ./test_source.csh\n")
    os.write(master, b"printenv MY_PATH\n")
    os.write(master, b"exit\n")
    
    out = b""
    while True:
        try:
            data = os.read(master, 1024)
            if not data:
                break
            out += data
        except OSError:
            break
            
    print("Interactive shell output:")
    print(out.decode())
    os.waitpid(pid, 0)
