import hashlib
import base64
import hmac
import time
import os

class BadToken(Exception):
	pass

def b64_encode(obj):
	s = base64.b64encode(str(obj).encode("ascii")).decode("ascii")
	return s[:-(s.count("="))] if "=" in s else s

def b64_decode(obj):
	try:
		return base64.b64decode(str(obj).encode('ascii') + b"==").decode("ascii")
	except Exception as e:
		raise BadToken()

def generate_token(node_id, secret):
	node_id = b64_encode(str(node_id))
	iat = b64_encode(str(int(time.time())))
	msg = f"{node_id}.{iat}"

	signature = b64_encode(
		hmac.new(
			bytes(secret, "ascii"),
			msg = bytes(msg, "ascii"),
			digestmod = hashlib.sha3_224
		).hexdigest()
	)

	return f"{msg}.{signature}"

def decode_token(token, secret):
	try:
		node_id, iat, signature = token.split(".")

		node_id_data = b64_decode(node_id)
		iat_data = b64_decode(iat)
		msg = f"{node_id}.{iat}"

		compare = b64_encode(
			hmac.new(
				bytes(secret, "ascii"),
				msg = bytes(msg, "ascii"),
				digestmod = hashlib.sha3_224
			).hexdigest()
		)

		if signature != compare:
			raise BadToken()
	except UnicodeDecodeError:
		raise BadToken()

	return node_id_data, int(iat_data)


#print(decode_token(token, "lmaoXD"))