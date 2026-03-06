import subprocess
import os

with open("test_source.csh", "w") as f:
    f.write('set script_dir = `dirname $0`\n')
    f.write('setenv MY_PATH $script_dir\n')
    f.write('echo "Inside source 0: $0"\n')
    f.write('echo "Inside source MY_PATH: $MY_PATH"\n')

os.chmod("test_source.csh", 0o755)

print("Test 1: Normal shell=True executable=csh")
cmd = "source ./test_source.csh ; printenv MY_PATH"
p = subprocess.Popen(cmd, shell=True, executable="/bin/csh" if os.path.exists("/bin/csh") else "csh", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out, _ = p.communicate()
print(out.decode())

print("Test 2: Passing as arg0 to -c")
cmd = 'source "$0" ; printenv MY_PATH'
# python passes the args: ['csh', '-c', cmd, './test_source.csh']
p = subprocess.Popen(["/bin/csh" if os.path.exists("/bin/csh") else "csh", "-c", cmd, "./test_source.csh"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out, _ = p.communicate()
print(out.decode())
