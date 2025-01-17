import json 
from satori.lib import wallet
from satori.lib.apis.server import ClientConnection

def establishConnection(wallet: wallet.Wallet):
    ''' establishes a connection to the satori server, returns connection object '''
    #connectionPayload = wallet.authPayload()
    print(f'establishing a connection...')# with payload: {connectionPayload}')
    return ClientConnection(
        url='ws://localhost:8000', # mock_server.py
        #url='ws://localhost:4000', # satori server? 
        #payload=connectionPayload, # authentication payload, not implemented yet on server api
        )

if __name__ == '__main__':
    randomWallet = wallet.Wallet(temporary=True)()
    connection = establishConnection(randomWallet)
    while True:
        connection.send(input('what should the client say to the server? '))