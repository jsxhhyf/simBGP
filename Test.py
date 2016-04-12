import multiprocessing, socket, threading

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', 51234))
s.listen(1)
print 'listening...'

def process(pipe):
    data = pipe.recv()
    print 'first', data
    data = pipe.recv()
    print 'second', data

def handle(sock, addr, pipe):
    print 'Accept new connection from %s:%s...' % addr
    pipe.send("test1")
    pipe.send("test2")
    while True:
        sock_data = sock.recv(1024)
        if sock_data:
            print 'sock_data received is', sock_data
            pipe.send(sock_data)
        pipe_data = pipe.recv()
        if pipe_data:
            print 'pipe_data received is', pipe_data
            sock.send(str(pipe_data))

while True:
    sock, addr = s.accept()
    pipe = multiprocessing.Pipe()
    p_simu = multiprocessing.Process(target=process, args=(pipe[0], ))
    t = threading.Thread(target=handle, args=(sock, addr, pipe[1]))
    p_simu.start()
    t.start()