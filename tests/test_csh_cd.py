import subprocess

cmd = "cd /tmp ; echo $PWD ; echo $cwd"
p = subprocess.Popen(["csh", "-c", cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out, _ = p.communicate()
print("csh -c 'cd /tmp ; echo ...'")
print(out.decode())
