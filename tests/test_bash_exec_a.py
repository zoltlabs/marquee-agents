import subprocess

with open("test_source.csh", "w") as f:
    f.write('set script_dir = `dirname $0`\n')
    f.write('echo "0 is $0"\n')
    f.write('echo "DIR is $script_dir"\n')

cmd = 'bash -c \'exec -a "./foobar" csh -c "source test_source.csh"\''
p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out, _ = p.communicate()
print("bash exec -a trick:")
print(out.decode())
