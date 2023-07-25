import ssl
import socket
import requests

def check_ssl_version(host, port):
    context = ssl.create_default_context()

    with socket.create_connection((host, port)) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
            print('Server SSL version:', ssock.version())
    

# Replace 'www.google.com' and 443 with your server's host and port
check_ssl_version('www.google.com', 443)

print('my ssl version:')
print(ssl.OPENSSL_VERSION)
print('requests version', requests.__version__)
