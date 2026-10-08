import subprocess
import re
import sys 
import os
import time
import sys
import urllib.parse

# Detect connected mtp devices, take the first one
result = subprocess.run(
    ["gio", "mount", "-l"],
    capture_output=True,
    text=True
)

uris = re.findall(r"mtp://[^\s]+", result.stdout)

device = uris[0] if uris else None

# Now we need to check if the device has allowed filesystem access
# There seems to be no obvious way to do this, but it seems that when filesystem access
# is allowed, the gio info output lists the filesystem size

result = subprocess.run(
	["gio", "info", device],
	capture_output=True,
	text= True
	)

if 'filesystem::size' not in result.stdout:
	print("Device has not allowed access")
	sys.exit()

# We have to now ensure that adb can see the device. Sometimes adb bugs out for some weird reason.
# We will do three attempts at this.

device_id = device.split("_")[-1][:-1]
for i in range(1, 4):
	output = subprocess.run(['adb', 'devices'], capture_output = True, text = True).stdout
	if device_id not in output:
		print(f"Device not found in adb devices. (Attempt #{i})")
		if i == 3:
			print("Cannot find device in adb list, please try reconnecting.")
			sys.exit()
		subprocess.run(['adb', 'kill-server'])
		subprocess.run(['adb', 'start-server'])
	else:
		break

cmd = ['adb', 'shell', 'am', 'broadcast', '-a', 'com.serenity.BEAM', '--es', 'content', urllib.parse.quote(sys.argv[1])]
# os.system(f'notify-send hi "{' '.join(cmd)}"')
# Now that we are sure that we can access the device, Let's try to initiate a handshake
subprocess.run(cmd, capture_output = True, text = True)
time.sleep(5)

response = subprocess.run(['gio', 'cat', os.path.join(device, "Internal storage", 'serenity', 'response.txt')], capture_output = True, text = True)
print(response.stdout)