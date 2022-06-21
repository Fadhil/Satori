import requests
import json


def main():
    url = "http://moontree.com:50002"
    payload = {
        #"method": "blockchain.scripthash.get_asset_balance",
        "method": "blockchain.relayfee",
        #"params": "76a9147a2c53a541c5d4396209e18c7cd0ce4aff9f375388ac",
        "jsonrpc": "2.0",
        "id": 0,
    }
    response = requests.post(url, json=payload).json()
    print(response)
    #assert response["result"] == "echome!"
    #assert response["jsonrpc"]
    #assert response["id"] == 0


import socket
import json
from time import sleep

port = 50002
#host = 'http://moontree.com'
#host = 'rvn4lyfe.com'
host = 'testnet.rvn.rocks'
#content = {
#    "method": "blockchain.transaction.get",
#    "params": ["6870e1524f12d54e942197e656d9b514c691cc1b9f60901b38bb7fdd43b3bc27", True],
#    "id": 0
#}
content = {
    "method": "blockchain.relayfee",
    "id": 0
}

def electrumx(host, port, content):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.sendall(json.dumps(content).encode('utf-8')+b'\n')
    sleep(0.5)
    sock.shutdown(socket.SHUT_WR)
    res = ""
    while True:
        data = sock.recv(1024)
        print(data)
        if (not data):
            break
        res += data.decode()
    print(res)
    sock.close()

electrumx(host, port, content)



import grappler
from base58 import b58decode_check
from binascii import hexlify
from hashlib import sha256
import codecs

OP_DUP = b'76'
OP_HASH160 = b'a9'
BYTES_TO_PUSH = b'14'
OP_EQUALVERIFY = b'88'
OP_CHECKSIG = b'ac'
DATA_TO_PUSH = lambda address: hexlify(b58decode_check(address)[1:])
sig_script_raw = lambda address: b''.join((OP_DUP, OP_HASH160, BYTES_TO_PUSH, DATA_TO_PUSH(address), OP_EQUALVERIFY, OP_CHECKSIG))
script_hash = lambda address: sha256(codecs.decode(sig_script_raw(address), 'hex_codec')).digest()[::-1].hex()



a = grappler.ElectrumXConnector(
    # host="fortress.qtornado.com", # bitcoin mainnet
    host='tn.not.fyi',
    port=55002,
    # port=443,
    ssl=True,
    timeout=5
)


a.send("server.version")
a.send("server.banner")
a.send('blockchain.scripthash.get_balance', script_hash('mksHkTDsauAP1L79rLZUQA3u36J3ntLtJx'))
a.send('blockchain.scripthash.get_mempool', script_hash('mksHkTDsauAP1L79rLZUQA3u36J3ntLtJx'))
a.send('blockchain.scripthash.subscribe', script_hash('mksHkTDsauAP1L79rLZUQA3u36J3ntLtJx'))

print()
print('RVuaiv475RtZ9zKYobTQS8DHfKW5NNB3vf')
print(script_hash('RVuaiv475RtZ9zKYobTQS8DHfKW5NNB3vf'))
print()
b = grappler.ElectrumXConnector(
    # host="fortress.qtornado.com", # bitcoin mainnet
    host='rvn4lyfe.com',
    port=50002,
    # port=443,
    ssl=True,
    timeout=5
)
b.send("server.version", 'Meta', '1.10')
b.send("blockchain.scripthash.get_asset_balance", script_hash('REsQeZT8KD8mFfcD4ZQQWis4Ju9eYjgxtT'))
b.send("blockchain.asset.get_meta", 'SATORI')

# unneeded
b.send("server.banner")
b.send("blockchain.relayfee")
b.send('blockchain.scripthash.get_balance', script_hash('n1issueAssetXXXXXXXXXXXXXXXXWdnemQ'))
b.send("blockchain.scripthash.list_assets", script_hash('RVuaiv475RtZ9zKYobTQS8DHfKW5NNB3vf'))
b.send("blockchain.scripthash.list_assets", script_hash('REsQeZT8KD8mFfcD4ZQQWis4Ju9eYjgxtT'))