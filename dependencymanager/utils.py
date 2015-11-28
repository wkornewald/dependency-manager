from .repo import ProcessError
from threading import Thread
# Use the system PRNG if possible
import hashlib, random, time
try:
    r = random.SystemRandom()
    r.getstate()
    random = r
    using_sysrandom = True
except NotImplementedError:
    using_sysrandom = False

def get_random_string(length=12, allowed_chars='abcdefghijklmnopqrstuvwxyz'
                                               'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'):
    """
    Returns a securely generated random string.

    The default length of 12 with the a-z, A-Z, 0-9 character set returns
    a 71-bit value. log_2((26+26+10)^12) =~ 71 bits
    """
    return ''.join([random.choice(allowed_chars) for i in range(length)])

def get_secure_random_string(*args, **kwargs):
    if not using_sysrandom:
        # This is ugly, and a hack, but it makes things better than
        # the alternative of predictability. This re-seeds the PRNG
        # using a value that is hard for an attacker to predict, every
        # time a random string is required. This may change the
        # properties of the chosen random sequence slightly, but this
        # is better than absolute predictability.
        random.seed(hashlib.sha256("%s%s%s" %
                                   (random.getstate(), time.time(), __file__)).digest())
    return get_random_string(*args, **kwargs)

class AsyncResult(object):
    def __init__(self, func, args=(), kwargs=None):
        if kwargs is None:
            kwargs = {}
        self.func = func
        self.thread = Thread(target=self.run, args=args, kwargs=kwargs)
        self.thread.start()

    def run(self, *args, **kwargs):
        try:
            self.result = self.func(*args, **kwargs)
        except ProcessError as e:
            self.result = e

    def do(self):
        self.thread.join()
        return self.result

def with_lock(func, lock):
    def wrapper(*args, **kwargs):
        with lock:
            return func(*args, **kwargs)
    return wrapper
