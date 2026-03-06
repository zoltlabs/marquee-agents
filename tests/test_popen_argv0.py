import subprocess

with open("test_source.csh", "w") as f:
    f.write('set script_dir = `dirname $0`\n')
    f.write('echo "0 is $0"\n')
    f.write('echo "DIR is $script_dir"\n')

csh_path = "/bin/csh"
# args[0] will be "./test_source.csh"
args = ["./test_source.csh", "-c", "source test_source.csh"]
p = subprocess.Popen(args, executable=csh_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out, _ = p.communicate()
print("Python Popen args[0] trick:")
print(out.decode())
